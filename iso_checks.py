"""Conservative checks on decoded OPN audit fields, not a wire ISO decoder."""
from __future__ import annotations

import re
from collections import defaultdict
from diagnostic_common import (AuditMessage as IsoMessage, normalized, different,
                               problem_row_tag, check_original_transactions)


# Explicit supported request/response pairs; proprietary MTIs are not guessed.
RESPONSE_MTIS = {
    '0100': '0110', '0120': '0130', '0121': '0130',
    '0200': '0210', '0220': '0230', '0221': '0230',
    '0400': '0410', '0420': '0430', '0421': '0430',
    '0500': '0510', '0520': '0530', '0521': '0530',
    '0800': '0810', '0820': '0830',
}
ALIASES = {
    'mti': ('msgid', 'mti'),
    'stan': ('stan', 'auditnumber'),
    'amount': ('transactionamt', 'transactionamount', 'amt', 'amount'),
    'currency': ('currency', 'currencycode', 'currcode'),
    'tid': ('tid', 'terminal', 'terminalid', 'trmid'),
    'mid': ('mid', 'merchantid', 'cardacceptorid', 'merchant'),
    'rc': ('responsecode',),
    'rrn': ('retrievrefnumber', 'retrievalreferencenumber', 'rrn'),
    'original': ('originaldataelements', 'originaldata', 'originaldataelement'),
    'original_stan': ('origauditnumber', 'originalstan', 'origstan'),
    'original_rrn': ('originalrrn', 'origrrn'),
    'transmission_time': ('transmissiondatetime', 'transdatetime'),
    'bitmap': ('bitmap', 'primarybitmap', 'secondarybitmap'),
}
FIELD_NUMBERS = {4: 'amount', 7: 'transmission_time', 11: 'stan', 37: 'rrn', 39: 'rc',
                 41: 'tid', 42: 'mid', 49: 'currency', 90: 'original'}
NAME_KEYS = {alias: key for key, aliases in ALIASES.items() for alias in aliases}
LINE_FIELD = re.compile(r'^\s*(?:(\d+)\.\s*)?([^:\r\n]+)\s*:\s*(.*?)\s*$', re.M)
XML_FIELD = re.compile(r'<field\b[^>]*\bname=[\'"]([^\'"]+)[\'"][^>]*>(.*?)</field>', re.I)


def parse_iso_message(text: str, process: str, flow_type: str, message_type: str) -> IsoMessage | None:
    phase = re.match(r'^(request|response)\b', flow_type.strip(), re.I)
    if not process.upper().startswith('OPN') or not phase:
        return None
    message = IsoMessage(process.upper(), phase[1].lower())
    collected: dict[str, list[tuple[int, str]]] = defaultdict(list)

    def collect(name: str, value: str, number: str | None = None) -> None:
        name = re.sub(r'[ _-]', '', name).lower()
        de = re.fullmatch(r'de0*(\d+)', name)
        field_number = int(number) if number else int(de[1]) if de else None
        key = FIELD_NUMBERS.get(field_number) if field_number is not None else NAME_KEYS.get(name)
        if not key:
            return
        value = value.strip()
        wrapped = re.fullmatch(r'(asc|int|hex)<(.*?)>', value, re.I)
        integer = bool(wrapped and wrapped[1].lower() == 'int')
        if wrapped:
            value = wrapped[2].strip()
            if wrapped[1].lower() == 'hex' and key != 'bitmap':
                # Explicit numeric ISO fields in these audits use packed decimal.
                # Decode only an exact-width, decimal-only BCD representation.
                digits = {4: 12, 7: 10, 11: 6, 49: 3, 90: 42}.get(field_number)
                if not digits or len(value) != digits + digits % 2 or not re.fullmatch(r'[0-9]+', value):
                    return
                if digits % 2:
                    if value[0] != '0':
                        return
                    value = value[1:]
        if not value or value.lower() in {'n/a', 'na', 'not available'}:
            return
        # Binary dumps cannot be interpreted without the bank's encoding profile.
        if re.match(r'\w+<', value):
            return
        priority = 3 if field_number is not None else 2 if name == 'msgid' else 1
        collected[key].append((priority, value))
        # Only explicitly numbered DEs have a reliable wire-field identity.
        numeric_lengths = {4: 12, 11: 6, 49: 3, 90: 42}
        length = numeric_lengths.get(field_number)
        if length and (not re.fullmatch(r'[0-9]+', value)
                       or len(value) > length or (not integer and len(value) != length)):
            message.invalid_fields.add(f'DE{field_number}')
        if key == 'bitmap' and not (re.fullmatch(r'[0-9A-Fa-f]{16}(?:[0-9A-Fa-f]{16})?', value)
                                   or re.fullmatch(r'[01]{64}(?:[01]{64})?', value)):
            message.invalid_fields.add('bitmap')

    # Nested EMV components also use numbered labels (e.g. "4. applicationCryptogram").
    # Their dot column is deeper than the top-level ISO fields; they are not DE4.
    lines = [(line, LINE_FIELD.fullmatch(line)) for line in text.splitlines()]
    numbered_columns = [line.index('.') for line, match in lines if match and match[1]]
    top_column = min(numbered_columns) if numbered_columns else None
    indents = [len(line) - len(line.lstrip()) for line, match in lines if match and match[1]]
    top_indent = min(indents) if indents else None
    for line, match in lines:
        if match and (not match[1] or line.index('.') == top_column
                      or len(line) - len(line.lstrip()) == top_indent):
            collect(match[2], match[3], match[1])
    for match in XML_FIELD.finditer(text):
        collect(match[1], match[2])
    for key, candidates in collected.items():
        priority = max(p for p, _ in candidates)
        values = {v for p, v in candidates if p == priority}
        if len(values) == 1:
            message.values[key] = values.pop()
        # Ambiguous audit representations are deliberately not compared.
    if 'mti' not in message.values:
        header = re.search(r'\bMTI\s*=\s*(\d{4})\b', message_type, re.I)
        if header and (header[1] in RESPONSE_MTIS or header[1] in RESPONSE_MTIS.values()):
            message.values['mti'] = header[1]
    for key, length in (('mti', 4), ('rc', 2)):
        value = message.values.get(key, '')
        if value.isascii() and value.isdigit():
            message.values[key] = value.zfill(length)
    original = message.values.get('original', '')
    if re.fullmatch(r'[0-9]{42}', original):
        message.values['original_mti'] = original[:4]
        message.values['original_stan'] = original[4:10]
        message.values['original_time'] = original[10:20]
    return message


def check_iso_messages(messages: list[IsoMessage]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    processes: dict[str, list[IsoMessage]] = defaultdict(list)
    for message in messages:
        processes[message.process].append(message)
        if message.invalid_fields:
            errors.append('invalid ISO message format (' + ', '.join(sorted(message.invalid_fields)) + ')')
    for process_messages in processes.values():
        requests = [m for m in process_messages if m.phase == 'request']
        responses = [m for m in process_messages if m.phase == 'response']
        if requests and not responses:
            warnings.append('missing ISO response (incomplete log or timeout)')
        if responses and not requests:
            warnings.append('ISO response without request (incomplete log)')
        for response in responses:
            mti = response.values.get('mti')
            if mti in RESPONSE_MTIS.values() and not response.values.get('rc'):
                warnings.append('missing response code')
            candidates = [r for r in requests if RESPONSE_MTIS.get(r.values.get('mti')) == mti and mti]
            known_requests = [r for r in requests if r.values.get('mti') in RESPONSE_MTIS]
            if mti in (set(RESPONSE_MTIS) | set(RESPONSE_MTIS.values())) and known_requests and not candidates:
                errors.append('unexpected response MTI')
            if not candidates:
                # Compare a single exchange even if its MTI is absent/proprietary.
                candidates = requests if len(requests) == 1 else []
            if len(candidates) > 1 and response.values.get('stan'):
                matching = [r for r in candidates if r.values.get('stan') and not different(r, response, 'stan')]
                if matching:
                    candidates = matching
            signatures = {tuple(sorted(r.values.items())) for r in candidates}
            if len(signatures) != 1:
                if candidates:
                    warnings.append('ambiguous ISO request/response pairing')
                continue
            request = candidates[0]
            for key, label in (('stan', 'different STAN on the same transaction'),
                               ('currency', 'currency mismatch'),
                               ('tid', 'terminal or merchant mismatch'),
                               ('mid', 'terminal or merchant mismatch')):
                if different(request, response, key):
                    errors.append(label)
            if different(request, response, 'amount'):
                # A changed amount can be a legitimate partial approval/adjustment.
                warnings.append('amount mismatch (check partial approval/adjustment)')
        outcomes: dict[tuple[str, str], set[str]] = defaultdict(set)
        for response in responses:
            v = response.values
            if v.get('mti') and v.get('stan') and v.get('rc'):
                outcomes[(v['mti'], normalized('stan', v['stan']))].add(v['rc'])
        if any(len(codes) > 1 for codes in outcomes.values()):
            errors.append('conflicting responses')
    return list(dict.fromkeys(errors)), list(dict.fromkeys(warnings))


