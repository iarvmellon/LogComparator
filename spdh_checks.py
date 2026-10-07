"""Checks for decoded PTMS/SPDH fields; no ISO DE numbering is applied here.

Echo semantics follow ACI SPDH R6.0v10. Sequence resynchronization is permitted,
so sequence differences are warnings, not proof of a malformed response.
"""
from __future__ import annotations

import re
from collections import defaultdict
from diagnostic_common import AuditMessage, different, normalized


ALIASES = {
    'transmission': ('xchgid', 'transmissionnumber', 'transmissionno'),
    'sequence': ('transseqno', 'sequencenumber', 'rcnclttxnseqno'),
    'original_sequence': ('origintransseqno', 'originalsequencenumber', 'invoiceorigintransseqno'),
    'batch': ('rcncltprdid', 'disttrmbatchno', 'batchnumber'),
    'shift': ('disttrmshiftno', 'shiftnumber'),
    'stan': ('auditnumber', 'stan'),
    'tid': ('trmid', 'terminalid', 'terminal', 'tid'),
    'mid': ('merchantid', 'cardacceptorid', 'mid'),
    'rc': ('responsecode',),
    'amount': ('transactionamt', 'transactionamount', 'amount', 'amt'),
    'currency': ('currencycode', 'transcurrencycode', 'currency'),
    'message_class': ('prtclmsgclass',),
    'message_subclass': ('prtclmsgsubclass',),
    'transaction_code': ('prtcltranstype',),
    'device': ('devicetype',),
}
KEYS = {name: key for key, names in ALIASES.items() for name in names}
LINE = re.compile(r'^\s*(?:(?:\d+\.|\[[^\]]+\])\s*)?([\w -]+)\s*:\s*(.*?)\s*$', re.M)
XML = re.compile(r'<field\b[^>]*\bname=[\'"]([^\'"]+)[\'"][^>]*>(.*?)</field>', re.I)


def parse_spdh_message(text: str, process: str, flow_type: str) -> AuditMessage | None:
    phase = re.match(r'^(request|response)\b', flow_type.strip(), re.I)
    if not process.upper().startswith('PTMS') or not phase:
        return None
    message = AuditMessage(process.upper(), phase[1].lower())
    candidates = defaultdict(list)
    for pattern, priority in ((LINE, 2), (XML, 1)):
        for match in pattern.finditer(text):
            name = re.sub(r'[ _-]', '', match[1]).lower()
            key = KEYS.get(name)
            if not key:
                continue
            value = match[2].strip()
            wrapped = re.fullmatch(r'(asc|int)<(.*?)>', value, re.I)
            if wrapped:
                value = wrapped[2].strip()
            if not value or re.match(r'\w+<', value) or value.lower() in {'n/a', 'na', 'not available'}:
                continue
            # Prefer full transSeqNo over its reconciliation counter subfield.
            rank = priority * 10 + (2 if name == 'transseqno' else 1)
            candidates[key].append((rank, value))
            if key in {'transmission', 'transaction_code', 'rc'}:
                limit = 3 if key == 'rc' else 2
                if not re.fullmatch(r'[0-9]{1,' + str(limit) + r'}', value):
                    message.invalid_fields.add(key)
    for key, items in candidates.items():
        rank = max(p for p, _ in items)
        values = {v for p, v in items if p == rank}
        if len(values) == 1:
            message.values[key] = values.pop()
    if message.values.get('rc', '').isdigit():
        message.values['rc'] = message.values['rc'].zfill(3)
    return message


def check_spdh_messages(messages: list[AuditMessage]) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    processes = defaultdict(list)
    for message in messages:
        processes[message.process].append(message)
        if message.invalid_fields:
            errors.append('invalid SPDH message format (' + ', '.join(sorted(message.invalid_fields)) + ')')
    for group in processes.values():
        requests = [m for m in group if m.phase == 'request']
        responses = [m for m in group if m.phase == 'response']
        if requests and not responses:
            warnings.append('missing SPDH response (incomplete log or timeout)')
        if responses and not requests:
            warnings.append('SPDH response without request (incomplete log)')
        for response in responses:
            if not response.values.get('rc'):
                warnings.append('missing response code')
            candidates = requests
            if len(candidates) > 1:
                for key in ('transmission', 'sequence'):
                    matched = [m for m in candidates if m.values.get(key) and response.values.get(key)
                               and not different(m, response, key)]
                    if matched:
                        candidates = matched
            if len({tuple(sorted(m.values.items())) for m in candidates}) != 1:
                if candidates:
                    warnings.append('ambiguous SPDH request/response pairing')
                continue
            request = candidates[0]
            for key, label in (
                ('transmission', 'transmission number mismatch'),
                ('tid', 'terminal or merchant mismatch'), ('mid', 'terminal or merchant mismatch'),
                ('currency', 'currency mismatch'), ('stan', 'different STAN on the same transaction'),
                ('message_class', 'message class mismatch'), ('message_subclass', 'message subclass mismatch'),
                ('transaction_code', 'transaction code mismatch'),
            ):
                if different(request, response, key):
                    errors.append(label)
            for key in ('sequence', 'batch', 'shift'):
                if different(request, response, key):
                    warnings.append(key + ' mismatch (check resynchronization)')
            if different(request, response, 'amount'):
                warnings.append('amount mismatch (check partial approval/adjustment)')
        outcomes = defaultdict(set)
        for response in responses:
            v = response.values
            identity = v.get('transmission') or v.get('sequence')
            if identity and v.get('rc'):
                outcomes[(v.get('tid', ''), v.get('transaction_code', ''), normalized('transmission', identity))].add(v['rc'])
        if any(len(codes) > 1 for codes in outcomes.values()):
            errors.append('conflicting responses')
    return list(dict.fromkeys(errors)), list(dict.fromkeys(warnings))
