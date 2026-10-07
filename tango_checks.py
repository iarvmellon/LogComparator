"""Stream explicit Tango diagnostics; associate only exact transaction IDs."""
from __future__ import annotations

import gzip
import re
from pathlib import Path


UID = re.compile(r'\btrans_?uid\s*[=:]\s*[\'\"]?([\w.-]+)', re.I)
MISSING = re.compile(
    r'\b(?:missing|absent)\s+(?:mandatory\s+|required\s+|optional\s+)?(?:identification\s+)?(?:field|element|tag)\b'
    r'|\b(?:field|element|tag)\b[^|\r\n]{0,90}\b(?:missing|absent|not\s+(?:present|found|provided|set))\b', re.I)
FIELD_NAMES = (
    re.compile(r'\b(?:field|element|tag)\s*[:=#]\s*[\'\"]?([\w.-]+)', re.I),
    re.compile(r'\b(?:field|element|tag)\s+[\'\"]?([\w.-]+)[\'\"]?\s+(?:is\s+)?(?:missing|absent|not\s+(?:present|found|provided|set))', re.I),
    re.compile(r'\bmissing\s+(?:mandatory\s+|required\s+|optional\s+)?(?:field|element|tag)\s+[\'\"]?([\w.-]+)', re.I),
)


def diagnostic(line: str) -> tuple[str, str] | None:
    if re.search(r'\b(?:no\s+(?:missing|absent)\s+fields?|not\s+missing|not\s+absent)\b', line, re.I):
        return None
    if MISSING.search(line):
        names = []
        for pattern in FIELD_NAMES:
            for match in pattern.finditer(line):
                name = match[1]
                if name.lower() not in {'in', 'is', 'was', 'the', 'from', 'for', 'not', 'missing', 'absent'}:
                    names.append(name[:64])
        label = 'missing field' + (': ' + ', '.join(dict.fromkeys(names)) if names else ' (name not logged)')
        return ('warning' if re.search(r'\boptional\b', line, re.I) else 'error', label)
    for pattern, severity, label in (
        (r'\b(?:invalid\s+MAC|MAC\s+(?:verification|validation|check)\s+(?:failed|failure|error))\b', 'error', 'MAC verification failed'),
        (r'\bHSM\b[^|\r\n]{0,60}\b(?:unavailable|failure|failed|timeout|timed out)\b', 'error', 'HSM failure'),
        (r'\b(?:network|connection|socket|host|response)\b[^|\r\n]{0,40}\b(?:timeout|timed out)\b', 'warning', 'communication timeout'),
    ):
        if re.search(pattern, line, re.I):
            return severity, label
    return None


def line_protocol(line: str) -> str | None:
    parts = line.split('|')
    header = ' '.join(parts[1:3]) if len(parts) >= 7 else ''
    for text in (header, line):
        iso = bool(re.search(r'\b(?:OPN\w*|ISO(?:8583)?)\b', text, re.I))
        spdh = bool(re.search(r'\b(?:PTMS\w*|SPDH)\b', text, re.I))
        if iso or spdh:
            return 'ISO' if iso and not spdh else 'SPDH' if spdh and not iso else None
    return None


def scan_tango_diagnostics(paths: list[Path], transaction_uids: set[str], progress=None) -> dict:
    findings: dict[str, dict[str | None, list[tuple[str, str]]]] = {}
    if not transaction_uids:
        return findings
    # Prefer an extracted copy over the corresponding gzip file.
    sources = {}
    for path in paths:
        key = str(path.with_suffix('')) if path.suffix.lower() == '.gz' else str(path)
        if key not in sources or path.suffix.lower() != '.gz':
            sources[key] = path
    for path in sources.values():
        opener = gzip.open if path.suffix.lower() == '.gz' else open
        if progress:
            progress(85, 'Check Tango diagnostics: ' + path.name)
        with opener(path, 'rt', encoding='utf-8', errors='replace') as handle:
            for index, line in enumerate(handle):
                if progress and index and index % 100000 == 0:
                    progress(85, 'Check Tango diagnostics: ' + path.name)
                # Extract known UID positions before expensive diagnostic regexes.
                parts = line.split('|', 7)
                candidates = {parts[6].strip()} if len(parts) >= 8 else set()
                candidates.update(UID.findall(line))
                matches = candidates & transaction_uids
                if len(matches) != 1:
                    continue
                result = diagnostic(line)
                if result is None:
                    continue
                uid = matches.pop()
                entries = findings.setdefault(uid, {}).setdefault(line_protocol(line), [])
                if result not in entries:
                    entries.append(result)
    return findings
