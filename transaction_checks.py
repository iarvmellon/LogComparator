"""Transaction-level checks and protocol diagnostic orchestration."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Iterable
from iso_checks import check_iso_messages, is_one_way_echo, is_logon_pair, is_inbound_logon, RESPONSE_MTIS
from diagnostic_common import check_original_transactions, normalized
from spdh_checks import check_spdh_messages

if TYPE_CHECKING:
    from log_core import Transaction


def is_one_way_heartbeat(transaction: Transaction) -> bool:
    return (bool(transaction.iso_messages) and not transaction.spdh_messages
            and all(is_one_way_echo(message) for message in transaction.iso_messages))


def select_transaction_operation(transaction):
    # Runtime import avoids coupling parser construction to diagnostic imports.
    from log_core import select_transaction_operation as select_operation
    return select_operation(transaction)


def is_successful_protocol_only(transaction: Transaction) -> bool:
    if is_one_way_heartbeat(transaction):
        return True
    if transaction.iso_messages and not transaction.spdh_messages:
        requests = [m for m in transaction.iso_messages if m.phase == 'request']
        responses = [m for m in transaction.iso_messages if m.phase == 'response']
        echo = (select_transaction_operation(transaction) == 'Echo_Test'
                or (bool(requests) and all(m.values.get('network_management_code', '').lstrip('0') == '301'
                                          for m in requests)))
        if echo and requests and responses:
            def paired(request, response):
                return (request.process == response.process
                        and RESPONSE_MTIS.get(request.values.get('mti')) == response.values.get('mti')
                        and bool(response.values.get('mti')))
            return (all(any(paired(request, response) for response in responses) for request in requests)
                    and all(any(paired(request, response) for request in requests) for response in responses)
                    and all(m.values.get('rc') in {'00', '000'} for m in responses))
    if select_transaction_operation(transaction) == 'Logon' and transaction.iso_messages:
        if all(is_inbound_logon(message) for message in transaction.iso_messages):
            return True
        requests = [m for m in transaction.iso_messages if m.phase == 'request']
        responses = [m for m in transaction.iso_messages if m.phase == 'response']
        return (bool(requests and responses)
                and all(any(is_logon_pair(request, response) for response in responses) for request in requests)
                and all(any(is_logon_pair(request, response) for request in requests) for response in responses)
                and all(m.values.get('rc', '') in {'', '00'} for m in responses))
    if transaction.iso_messages or select_transaction_operation(transaction) not in {'Close_Batch', 'Generate_Key'}:
        return False
    by_process = {}
    for message in transaction.spdh_messages:
        by_process.setdefault(message.process, []).append(message)
    return bool(by_process) and all(
        any(message.phase == 'request' for message in messages)
        and any(message.phase == 'response' for message in messages)
        and all(message.values.get('rc') == '000' for message in messages if message.phase == 'response')
        for messages in by_process.values()
    )



def successful_local_reversal_uids(transactions):
    """Recognize completed local reversals using unique explicit SPDH references."""
    transactions = list(transactions)
    by_uid = {t.trans_uid: t for t in transactions}
    reversal = {t.trans_uid: bool(re.search(r'(?:^|_)Reversal(?:_|$)',
                                          select_transaction_operation(t), re.I)) for t in transactions}
    originals = check_original_transactions(
        [(t.trans_uid, t.spdh_messages, bool(re.search(r'(?:^|_)(?:Reversal|Void)(?:_|$)',
                                                      select_transaction_operation(t), re.I)))
         for t in transactions], use_rrn=False)
    by_stan, by_sequence = {}, {}
    for t in transactions:
        if re.search(r'(?:^|_)(?:Reversal|Void)(?:_|$)', select_transaction_operation(t), re.I):
            continue
        for m in t.spdh_messages:
            if m.phase != 'request':
                continue
            v = m.values
            if v.get('stan'):
                by_stan.setdefault((m.process, normalized('stan', v['stan'])), set()).add(t.trans_uid)
            if v.get('sequence') and v.get('tid'):
                by_sequence.setdefault((m.process, v['tid'], normalized('sequence', v['sequence'])), set()).add(t.trans_uid)
    successful = set()
    for t in transactions:
        if not reversal[t.trans_uid] or t.iso_messages or originals.get(t.trans_uid) != ([], []):
            continue
        processes = {m.process for m in t.spdh_messages}
        if not processes or any(
            not any(m.phase == 'request' and m.process == process for m in t.spdh_messages)
            or not any(m.phase == 'response' and m.process == process for m in t.spdh_messages)
            for process in processes
        ) or any(m.values.get('rc') != '000' for m in t.spdh_messages if m.phase == 'response'):
            continue
        matched = set()
        valid = True
        for m in t.spdh_messages:
            if m.phase != 'request':
                continue
            v = m.values
            if v.get('original_stan'):
                candidates = by_stan.get((m.process, normalized('stan', v['original_stan'])), set())
            elif v.get('original_sequence') and v.get('tid'):
                candidates = by_sequence.get((m.process, v['tid'], normalized('sequence', v['original_sequence'])), set())
            else:
                valid = False
                break
            if len(candidates) != 1:
                valid = False
                break
            matched.update(candidates)
        if not valid or len(matched) != 1:
            continue
        original = by_uid[next(iter(matched))]
        if (original.iso_messages or any(p.upper().startswith('OPN') for p in original.process_names)
                or any(p.startswith('ISO:') for p in original.operation_flows)):
            continue
        original_time = original.request_timestamp or original.first_timestamp
        reversal_time = t.request_timestamp or t.first_timestamp
        if original_time and reversal_time:
            preceding = original_time < reversal_time
        else:
            preceding = original.first_index < t.first_index
        if preceding:
            successful.add(t.trans_uid)
    return successful


def emv_completeness_applies(transaction):
    return select_transaction_operation(transaction) in {
        'Purchase', 'Purchase_with_Cashback', 'Cash_Advance',
        'Pre-auth', 'Pre-auth_Request', 'Authorization_Request', 'Financial_Request',
    }


def iso_rrn_phases(transaction: Transaction) -> dict[str, dict[str, set[str]]]:
    phases = {process: {phase: set(values) for phase, values in flows.items()}
              for process, flows in transaction.rrns_by_flow.items() if process.upper().startswith('OPN')}
    for message in transaction.iso_messages:
        if message.process.upper().startswith('OPN') and (rrn := message.values.get('rrn')):
            phases.setdefault(message.process, {}).setdefault(message.phase, set()).add(rrn)
    return phases


def transactions_with_shared_rrns(transactions: Iterable[Transaction]) -> set[str]:
    owners: dict[str, str] = {}
    shared: set[str] = set()
    for transaction in transactions:
        operation = select_transaction_operation(transaction)
        if re.search(r"(?:^|_)(?:Reversal|Void)(?:_|$)", operation, re.IGNORECASE):
            continue
        for value in {v for phases in iso_rrn_phases(transaction).values()
                      for values in phases.values() for v in values}:
            rrn = value.strip()
            if not rrn or re.fullmatch(r"\w+<\s*>", rrn):
                continue
            owner = owners.setdefault(rrn, transaction.trans_uid)
            if owner != transaction.trans_uid:
                shared.update((owner, transaction.trans_uid))
    return shared


def original_transaction_problems(transactions: Iterable[Transaction]) -> dict[str, tuple[list[str], list[str]]]:
    return check_original_transactions([
        (t.trans_uid, t.iso_messages, bool(re.search(
            r"(?:^|_)(?:Reversal|Void)(?:_|$)", select_transaction_operation(t), re.IGNORECASE)))
        for t in transactions
    ])


def select_possible_problem(transaction: Transaction, shared_rrn: bool = False,
                            original_problems: tuple[list[str], list[str]] | None = None) -> str:
    problems = []
    for phases in iso_rrn_phases(transaction).values():
        requests = phases.get("request", set())
        responses = phases.get("response", set())
        if requests and responses and requests != responses:
            problems.append("differentRRN on the same transaction")
            break
    if shared_rrn:
        problems.append("RRN identical with other transaction")
    errors, warnings = check_iso_messages(transaction.iso_messages, check_emv_completeness=emv_completeness_applies(transaction))
    problems.extend(errors)
    if original_problems:
        problems.extend(original_problems[0])
        warnings.extend(original_problems[1])
    problems.extend('warning: ' + warning for warning in warnings)
    return "; ".join(dict.fromkeys(problems))


def build_problem_columns(transactions: Iterable[Transaction], tango_findings: dict | None = None, *, checkpoint=None) -> dict[str, tuple[str, str]]:
    """Return ISO/SPDH findings, keeping protocol-specific evidence separate."""
    transactions = list(transactions)
    exempt = {t.trans_uid: bool(re.search(r'(?:^|_)(?:Reversal|Void)(?:_|$)',
                                         select_transaction_operation(t), re.I)) for t in transactions}
    columns = {t.trans_uid: [] for t in transactions}
    for protocol, prefix, attribute, checker in (
        ('ISO', 'OPN', 'iso_messages', check_iso_messages),
        ('SPDH', 'PTMS', 'spdh_messages', check_spdh_messages),
    ):
        shared = transactions_with_shared_rrns(transactions) if protocol == 'ISO' else set()
        originals = check_original_transactions(
            [(t.trans_uid, getattr(t, attribute), exempt[t.trans_uid]) for t in transactions],
            use_rrn=protocol == 'ISO')
        for t in transactions:
            if checkpoint:
                checkpoint()
            errors, warnings = checker(getattr(t, attribute), check_emv_completeness=emv_completeness_applies(t))
            phases_by_process = iso_rrn_phases(t) if protocol == 'ISO' else {}
            if any(p.get('request') and p.get('response') and p['request'] != p['response']
                   for p in phases_by_process.values()):
                errors.append('differentRRN on the same transaction')
            if t.trans_uid in shared:
                errors.append('RRN identical with other transaction')
            original_errors, original_warnings = originals.get(t.trans_uid, ([], []))
            errors.extend(original_errors)
            warnings.extend(original_warnings)
            tango = (tango_findings or {}).get(t.trans_uid, {})
            for source in (protocol, None):
                for severity, label in tango.get(source, []):
                    text = ('Tango: ' if source else 'Tango (protocol unspecified): ') + label
                    (errors if severity == 'error' else warnings).append(text)
            columns[t.trans_uid].append('; '.join(dict.fromkeys(errors + ['warning: ' + w for w in warnings])))
    return {uid: tuple(values) for uid, values in columns.items()}


