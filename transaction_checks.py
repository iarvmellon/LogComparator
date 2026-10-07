"""Transaction-level checks and protocol diagnostic orchestration."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Iterable
from iso_checks import check_iso_messages
from diagnostic_common import check_original_transactions
from spdh_checks import check_spdh_messages

if TYPE_CHECKING:
    from log_core import Transaction


def select_transaction_operation(transaction):
    # Runtime import avoids coupling parser construction to diagnostic imports.
    from log_core import select_transaction_operation as select_operation
    return select_operation(transaction)


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
    errors, warnings = check_iso_messages(transaction.iso_messages)
    problems.extend(errors)
    if original_problems:
        problems.extend(original_problems[0])
        warnings.extend(original_problems[1])
    problems.extend('warning: ' + warning for warning in warnings)
    return "; ".join(dict.fromkeys(problems))


def build_problem_columns(transactions: Iterable[Transaction], tango_findings: dict | None = None) -> dict[str, tuple[str, str]]:
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
            errors, warnings = checker(getattr(t, attribute))
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


