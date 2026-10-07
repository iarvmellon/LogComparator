"""Shared diagnostic metadata and conservative comparison helpers."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation


@dataclass
class AuditMessage:
    process: str
    phase: str
    values: dict[str, str] = field(default_factory=dict)
    invalid_fields: set[str] = field(default_factory=set)


def normalized(key: str, value: str) -> str:
    if key in {'stan', 'original_stan', 'currency', 'transmission', 'sequence', 'batch', 'shift', 'transaction_code'} and value.isascii() and value.isdigit():
        return str(int(value))
    if key == 'amount':
        try:
            return str(Decimal(value).normalize())
        except InvalidOperation:
            pass
    return value.strip()


def different(left: AuditMessage, right: AuditMessage, key: str) -> bool:
    a, b = left.values.get(key), right.values.get(key)
    return bool(a and b and normalized(key, a) != normalized(key, b))


def problem_row_tag(problem: str, spdh_rc: str, iso_rc: str) -> str:
    parts = [part for part in problem.split('; ') if part]
    if any(not part.startswith('warning: ') for part in parts):
        return 'problem'
    if parts:
        return 'warning'
    return 'approved' if spdh_rc == 'Approved(000)' and iso_rc == 'Approved(00)' else ''


def check_original_transactions(
    transactions: list[tuple[str, list[AuditMessage], bool]],
    *, use_rrn: bool = True,
) -> dict[str, tuple[list[str], list[str]]]:
    """Link reversals/voids using explicit original references or an observed RRN.

    An absent or ambiguous original is a warning, never proof of a bad reversal.
    Amount equality is not required because partial reversals are valid.
    """
    by_stan: dict[tuple[str, str], list[tuple[str, AuditMessage]]] = defaultdict(list)
    by_rrn: dict[tuple[str, str], list[tuple[str, AuditMessage]]] = defaultdict(list)
    by_sequence: dict[tuple[str, str, str], list[tuple[str, AuditMessage]]] = defaultdict(list)
    for uid, messages, exempt in transactions:
        if exempt:
            continue
        for message in messages:
            if message.phase != 'request':
                continue
            if message.values.get('sequence') and message.values.get('tid'):
                by_sequence[(message.process, message.values['tid'], normalized('sequence', message.values['sequence']))].append((uid, message))
            for key, index in (('stan', by_stan), ('rrn', by_rrn)):
                if key == 'rrn' and not use_rrn:
                    continue
                if value := message.values.get(key):
                    index[(message.process, normalized(key, value))].append((uid, message))
    results = {}
    for uid, messages, exempt in transactions:
        if not exempt:
            continue
        errors, warnings = [], []
        for message in messages:
            if message.phase != 'request':
                continue
            v = message.values
            if v.get('original_stan'):
                candidates = by_stan.get((message.process, normalized('stan', v['original_stan'])), [])
            elif v.get('original_sequence') and v.get('tid'):
                candidates = by_sequence.get((message.process, v['tid'], normalized('sequence', v['original_sequence'])), [])
            elif use_rrn and (v.get('original_rrn') or v.get('rrn')):
                candidates = by_rrn.get((message.process, v.get('original_rrn') or v['rrn']), [])
            else:
                warnings.append('original transaction cannot be checked (missing reference)')
                continue
            candidates = [(other_uid, original) for other_uid, original in candidates if other_uid != uid]
            # DE90's transmission timestamp disambiguates reused STANs when DE7 is available.
            if v.get('original_time'):
                candidates = [(other_uid, original) for other_uid, original in candidates
                              if not original.values.get('transmission_time')
                              or original.values['transmission_time'] == v['original_time']]
            unique = {(other_uid, tuple(sorted(original.values.items()))) for other_uid, original in candidates}
            if not unique:
                warnings.append('original transaction not found (incomplete log)')
                continue
            if len(unique) != 1:
                warnings.append('ambiguous original transaction')
                continue
            original = candidates[0][1]
            mismatches = []
            for key, label in (('tid', 'TID'), ('mid', 'MID'), ('currency', 'currency')):
                if different(message, original, key):
                    mismatches.append(f'{label}: current={v[key]}, original={original.values[key]}')
            for ref, key in (('original_mti', 'mti'), ('original_rrn', 'rrn')):
                if key == 'rrn' and not use_rrn:
                    continue
                if v.get(ref) and original.values.get(key) and v[ref] != original.values[key]:
                    mismatches.append(f'{ref}: referenced={v[ref]}, observed={original.values[key]}')
            if mismatches:
                errors.append('original transaction mismatch (' + ', '.join(mismatches) + ')')
        results[uid] = (list(dict.fromkeys(errors)), list(dict.fromkeys(warnings)))
    return results
