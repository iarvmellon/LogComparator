"""EMV diagnostics on explicitly decoded tags and complete BER-TLV containers.

Missing common online tags are warnings: acquirer requirements and log completeness
cannot be inferred from generic EMV rules. Raw SPDH fixed-layout fields are not TLV.
"""
from __future__ import annotations

import re
from datetime import datetime

# Byte widths for standard EMV data objects. Proprietary data is left opaque.
WIDTHS = {'9F26': (8, 8), '9F27': (1, 1), '9F36': (2, 2),
          '9F37': (4, 4), '95': (5, 5), '82': (2, 2), '9A': (3, 3),
          '9C': (1, 1), '9F02': (6, 6), '9F03': (6, 6), '5F2A': (2, 2),
          '9F1A': (2, 2), '9F10': (1, 32), '9F33': (3, 3),
          '9F34': (3, 3), '9F35': (1, 1), '9F09': (2, 2),
          '9F1E': (8, 8), '9F66': (4, 4), '84': (5, 16), '4F': (5, 16),
          '5F34': (1, 1), '9B': (2, 2), '8A': (2, 2), '91': (8, 16)}
NUMERIC = {'9A', '9C', '9F02', '9F03', '5F2A', '9F1A', '5F34'}
COMMON_ONLINE = {'9F26', '9F36', '9F37', '95', '9A', '9C', '9F02', '5F2A', '82', '9F1A'}
ALIASES = {'applicationcryptogram': '9F26', 'cryptograminformationdata': '9F27',
           'applicationtransactioncounter': '9F36', 'unpredictablenumber': '9F37',
           'terminalverificationresults': '95', 'applicationinterchangeprofile': '82',
           'terminaltransdate': '9A', 'transactiondate': '9A',
           'amountauthorised': '9F02', 'amountauthorized': '9F02',
           'issuerapplicationdata': '9F10', 'terminalcapabilities': '9F33',
           'cvmresults': '9F34', 'terminaltype': '9F35', 'terminalcountrycode': '9F1A',
           'transactioncurrencycode': '5F2A', 'transcurrencycode': '5F2A',
           'cid': '9F27', 'aip': '82', 'atc': '9F36', 'tvr': '95',
           'amtauthorized': '9F02', 'amtother': '9F03', 'transactiontype': '9C'}
CONTAINERS = {'iccdata', 'emvdata', 'chipdata', 'emvtlv', 'de55', 'de055'}
FIELDS = re.compile(r'^[ \t]*(?:\d+\.[ \t]*)?([^:\r\n]+):[ \t]*(.*?)[ \t]*$', re.M)
XML = re.compile(r'<field\b[^>]*\bname=[\'"]([^\'"]+)[\'"][^>]*>(.*?)</field>', re.I)


def parse_emv(text):
    tags, errors = {}, []
    strict_tags, ambiguous_names = set(), set()
    def add(tag, value, strict=True):
        if not strict:
            if tag in strict_tags or tag in ambiguous_names:
                return
            if tag in tags and tags[tag] != value:
                tags.pop(tag)
                ambiguous_names.add(tag)
                return
        elif tag not in strict_tags:
            tags.pop(tag, None)
        if strict:
            strict_tags.add(tag)
        if tag in tags and tags[tag] != value:
            errors.append(f'conflicting EMV tag {tag}')
        tags.setdefault(tag, value)

    def tlv(data, depth=0):
        if depth > 8:
            raise ValueError('nesting too deep')
        offset = 0
        while offset < len(data):
            first = data[offset]
            offset += 1
            if first in (0, 255):
                raise ValueError('invalid tag')
            tag_bytes = bytearray([first])
            if first & 31 == 31:
                while True:
                    if offset >= len(data) or len(tag_bytes) >= 4:
                        raise ValueError('truncated or oversized tag')
                    part = data[offset]
                    offset += 1
                    tag_bytes.append(part)
                    if len(tag_bytes) == 2 and part & 127 == 0:
                        raise ValueError('invalid tag continuation')
                    if not part & 128:
                        break
            if offset >= len(data):
                raise ValueError('missing length')
            length = data[offset]
            offset += 1
            if length & 128:
                count = length & 127
                if not count or count > 3 or offset + count > len(data):
                    raise ValueError('invalid length encoding')
                length = int.from_bytes(data[offset:offset + count], 'big')
                offset += count
            if offset + length > len(data):
                raise ValueError('value shorter than declared length')
            value = data[offset:offset + length]
            offset += length
            if first & 32:
                tlv(value, depth + 1)
            else:
                add(tag_bytes.hex().upper(), value.hex().upper())

    for match in list(FIELDS.finditer(text)) + list(XML.finditer(text)):
        name = re.sub(r'[^a-zA-Z0-9]', '', match[1]).lower()
        if re.fullmatch(r'de\d+', name) and name not in CONTAINERS:
            continue
        value = match[2].strip()
        wrapped = re.fullmatch(r'(hex|asc|int)<(.*?)>', value, re.I)
        encoding = wrapped[1].lower() if wrapped else None
        if not wrapped and match.re is XML:
            xml_type = re.search(r'\btype=[\'"]([^\'"]+)[\'"]', match[0], re.I)
            if xml_type:
                encoding = 'asc' if xml_type[1].upper() == 'A' else 'opaque'
        if wrapped:
            value = wrapped[2].strip()
        explicit = re.fullmatch(r'(?:emvtag|tag|emv)?((?:[0-9a-f]{2}){1,4})', name)
        tag = explicit[1].upper() if explicit else ALIASES.get(name)
        if name in CONTAINERS and encoding == 'hex':
            try:
                compact = re.sub(r'\s+', '', value)
                if not re.fullmatch(r'(?:[0-9A-Fa-f]{2})*', compact):
                    raise ValueError('non-hexadecimal or odd-length payload')
                tlv(bytes.fromhex(compact))
            except ValueError as exc:
                errors.append(f'invalid EMV TLV ({exc})')
            continue
        if not tag or (not explicit and 'icc' not in text.lower() and 'emv' not in text.lower()):
            continue
        if encoding in {'int', 'opaque'} or re.match(r'\w+<', value):
            continue  # Numeric audit rendering loses byte widths; opaque dumps are not guessed.
        compact = re.sub(r'\s+', '', value).upper()
        if encoding == 'asc' and tag not in NUMERIC and not explicit:
            # Named binary values may be fixed-layout/padded audit representations.
            # Accept only a known fixed width; variable IAD is not a wire tag here.
            width = WIDTHS.get(tag)
            if (not width or width[0] != width[1]
                    or len(compact) != width[0] * 2
                    or not re.fullmatch(r'[0-9A-F]+', compact)):
                continue
        # Decoded numeric audit fields omit the packed-decimal padding nibble.
        # This applies only to named ASCII country/currency fields, not wire tags.
        if not explicit and encoding == 'asc' and tag in {'9F1A', '5F2A'}:
            if re.fullmatch(r'[0-9]{1,3}', compact):
                compact = compact.zfill(4)
        add(tag, compact, strict=bool(explicit or encoding == 'hex'))
    return tags, list(dict.fromkeys(errors))


def check_emv(message, *, check_completeness=True):
    errors = list(message.emv_errors)
    warnings = []
    for tag, value in message.emv_tags.items():
        if not re.fullmatch(r'(?:[0-9A-F]{2})+', value):
            errors.append(f'invalid EMV tag {tag} (expected even-length hexadecimal value)')
            continue
        if tag in WIDTHS:
            minimum, maximum = WIDTHS[tag]
            size = len(value) // 2
            if not minimum <= size <= maximum:
                expected = str(minimum) if minimum == maximum else f'{minimum}-{maximum}'
                errors.append(f'invalid EMV tag {tag} length (expected {expected} bytes, observed {size})')
                continue
        if tag in NUMERIC and not value.isdigit():
            errors.append(f'invalid EMV tag {tag} format (expected packed decimal)')
        elif tag in {'5F2A', '9F1A'} and len(value) == 4 and value[0] != '0':
            errors.append(f'invalid EMV tag {tag} format (expected 3 digits with zero padding)')
        elif tag == '9A' and len(value) == 6:
            try:
                datetime.strptime(value, '%y%m%d')
            except ValueError:
                errors.append('invalid EMV tag 9A date')
    online = message.phase == 'request' and (
        message.process.startswith('OPN') and message.values.get('mti') in {'0100', '0200'}
        or message.process.startswith('PTMS') and message.emv_tags.get('9F27') == '80')
    if check_completeness and online and message.emv_tags and not message.emv_errors:
        missing = sorted(COMMON_ONLINE - message.emv_tags.keys())
        if missing:
            warnings.append('missing common online EMV tags: ' + ', '.join(missing)
                            + ' (verify acquirer requirements and log completeness)')
    chip_entry = message.values.get('entry_mode', '')[:2] in {'05', '07'}
    if check_completeness and message.phase == 'request' and chip_entry and not message.emv_tags and not message.emv_errors:
        if message.process.startswith('PTMS') or message.values.get('mti') in {'0100', '0200'}:
            warnings.append('chip entry mode without decoded EMV data (verify required EMV data and log completeness)')
    for tag, key in (('5F2A', 'currency'), ('9F02', 'amount')):
        value = message.emv_tags.get(tag, '')
        other = message.values.get(key, '')
        if value.isdigit() and other.isascii() and other.isdigit() and int(value) != int(other):
            warnings.append(f'EMV tag {tag} differs from message {key} (check currency/amount mapping)')
    return list(dict.fromkeys(errors)), warnings
