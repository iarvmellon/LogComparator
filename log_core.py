from __future__ import annotations

import argparse
import gzip
import io
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import tkinter as tk
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Iterator, TextIO

from tkcalendar import Calendar

from log_config import *

FIELD_RE = re.compile(
    r"<field\b[^>]*\bname=['\"](?P<name>[^'\"]+)['\"][^>]*>(?P<value>.*?)</field>",
    re.IGNORECASE,
)
AUDIT_VALUE_RE = re.compile(
    r"^\s*(?:(?:\[[^\]]+\]|\d+\.)\s*)?"
    r"(?P<name>[A-Za-z_][\w-]*)\s*:\s*"
    r"(?:asc|int)<(?P<value>[^>]*)>",
    re.IGNORECASE | re.MULTILINE,
)
PLAIN_VALUE_RE = re.compile(r"^\s*([A-Za-z][\w -]*)\s*:\s*(.*?)\s*$")
RECORD_DATE_RE = re.compile(
    r"^(?:RP|SP) date time(?: GMT)?\s*:\s*"
    r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})",
    re.MULTILINE,
)
RECORD_TIMESTAMP_RE = re.compile(
    r"^(?:RP|SP) date time(?: GMT)?\s*:.*?timestamp:\s*(\d{14,20})",
    re.MULTILINE,
)
HEADER_MTI_RE = re.compile(r"\bMTI\s*=\s*(\d{4})\b", re.IGNORECASE)
MESSAGE_MTI_RE = re.compile(
    r"^(?P<description>.*?),\s*MTI\s*=\s*(?P<mti>\d+)\s*$",
    re.IGNORECASE,
)
BUS_DATA_HEADER_RE = re.compile(r"^\s*Bus data:\s*$", re.IGNORECASE | re.MULTILINE)
RAW_DATA_HEADER_RE = re.compile(r"^\s*Raw data \(hex\):\s*$", re.IGNORECASE | re.MULTILINE)
DATA_SECTION_END_RE = re.compile(
    r"^\s*(?:Audit data|Bus data):\s*$",
    re.IGNORECASE | re.MULTILINE,
)
SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._()\\-]+")
SECTION_SEPARATOR = "#" * 79
TRANS_UID_MARKER_RE = re.compile(r"transUId|transUid")
FILE_TEXT_CACHE: dict[tuple[str, int, int], str] = {}
AUDIT_BLOCK_TEXT_CACHE: dict[
    tuple[tuple[str, int, int], ...],
    dict[str, list[tuple[int, str]]],
] = {}
LIST_FIELD_NAMES = {
    "transuid",
    "originmti",
    "tgoriginmti",
    "mti",
    "msgid",
    "retrievrefnumber",
    "retrievalreferencenumber",
    "rrn",
    "processingcode",
    "transactiontype",
    "responsecode",
    "acqid",
    "acquirerid",
    "acquiringinstid",
    "stan",
    "auditnumber",
    "origauditnumber",
    "transseqno",
    "sequence_number",
    "sequencenumber",
    "authcode",
    "authid",
    "approvalcode",
    "authorizationcode",
    "trmuid",
    "terminal",
    "terminalid",
    "tid",
    "trmid",
    "merchantid",
    "cardacceptorid",
    "merchant",
    "mid",
    "amount",
    "amt",
    "transactionamount",
    "transactionamt",
    "currency",
    "currencycode",
    "currcode",
    "msguid",
}
@dataclass
class BlockMeta:
    index: int
    timestamp: datetime | None
    is_request: bool
    message_type: str
    process_name: str
    flow_dir: str
    flow_type: str
    trans_uid: str | None
    mti_values: list[str]
    rrn_values: list[str]
    processing_codes: list[str]
    response_codes: list[str]
    tids: list[str]
    mids: list[str]
    amounts: list[str]
    currencies: list[str]
    acquirer_ids: set[str]
    identifiers: set[tuple[str, str]]


@dataclass
class Transaction:
    trans_uid: str
    first_index: int
    first_timestamp: datetime | None = None
    request_timestamp: datetime | None = None
    mtis: list[str] = field(default_factory=list)
    request_mtis: list[str] = field(default_factory=list)
    rrns: list[str] = field(default_factory=list)
    processing_codes: list[str] = field(default_factory=list)
    message_types: list[str] = field(default_factory=list)
    process_names: set[str] = field(default_factory=set)
    iso_response_codes: list[str] = field(default_factory=list)
    spdh_response_codes: list[str] = field(default_factory=list)
    tids: list[str] = field(default_factory=list)
    mids: list[str] = field(default_factory=list)
    amounts: list[str] = field(default_factory=list)
    currencies: list[str] = field(default_factory=list)
    acquirer_ids: set[str] = field(default_factory=set)
    identifiers: set[tuple[str, str]] = field(default_factory=set)

    def add(self, block: BlockMeta) -> None:
        if self.first_timestamp is None or (
            block.timestamp is not None and block.timestamp < self.first_timestamp
        ):
            self.first_timestamp = block.timestamp
        if block.is_request and block.timestamp is not None:
            if self.request_timestamp is None or block.timestamp < self.request_timestamp:
                self.request_timestamp = block.timestamp
        self.mtis.extend(block.mti_values)
        if block.is_request:
            self.request_mtis.extend(block.mti_values)
        self.rrns.extend(block.rrn_values)
        self.processing_codes.extend(block.processing_codes)
        self.tids.extend(block.tids)
        self.mids.extend(block.mids)
        self.amounts.extend(block.amounts)
        self.currencies.extend(block.currencies)
        if block.message_type:
            self.message_types.append(block.message_type)
        if block.process_name:
            self.process_names.add(block.process_name)
        flow_dir = block.flow_dir.upper().replace(" ", "")
        flow_type = block.flow_type.upper()
        if (
            block.process_name.upper().startswith("OPN")
            and "NETWORK-->TANGO" in flow_dir
            and "RESPONSE" in flow_type
        ):
            self.iso_response_codes.extend(block.response_codes)
        if (
            block.process_name.upper().startswith("PTMS")
            and "TANGO-->NETWORK" in flow_dir
            and "RESPONSE" in flow_type
        ):
            self.spdh_response_codes.extend(block.response_codes)
        self.acquirer_ids.update(block.acquirer_ids)
        self.identifiers.update(block.identifiers)


@dataclass
class GuiExportResult:
    summary: str
    output_dir: Path
    selected_trans_uids: list[str]


def iter_blocks(handle: TextIO) -> Iterator[str]:
    lines: list[str] = []
    pending_separator: str | None = None
    for line in handle:
        if line.startswith(SEPARATOR_PREFIX):
            if pending_separator is not None:
                lines.append(pending_separator)
            pending_separator = line
            continue

        if pending_separator is not None:
            if re.match(r"^(?:RP|SP) date time(?: GMT)?\s*:", line):
                if lines:
                    yield "".join(lines)
                lines = [pending_separator, line]
            else:
                lines.extend((pending_separator, line))
            pending_separator = None
        else:
            lines.append(line)
    if pending_separator is not None:
        lines.append(pending_separator)
    if lines:
        yield "".join(lines)


def without_bus_data(text: str) -> str:
    match = BUS_DATA_HEADER_RE.search(text)
    if not match:
        return text
    prefix = text[: match.start()]
    prefix = re.sub(
        r"(?:\r?\n)?-{20,}\s*\r?\n?\s*$",
        "",
        prefix,
    )
    return prefix.rstrip("\r\n") + "\n"


def without_raw_data(text: str) -> str:
    match = RAW_DATA_HEADER_RE.search(text)
    if not match:
        return text
    next_section = DATA_SECTION_END_RE.search(text, match.end())
    end = next_section.start() if next_section else len(text)
    prefix = text[: match.start()]
    suffix = text[end:]
    prefix = re.sub(
        r"(?:\r?\n)?-{20,}\s*\r?\n?\s*$",
        "",
        prefix,
    )
    return prefix.rstrip("\r\n") + "\n" + suffix.lstrip("\r\n")


def without_byte_data(text: str) -> str:
    return without_bus_data(without_raw_data(text))


def without_raw_data_fast(text: str) -> str:
    raw_start = -1
    for marker in ("\nRaw data (hex):", "\r\nRaw data (hex):"):
        raw_start = text.find(marker)
        if raw_start != -1:
            break
    if raw_start == -1:
        return text
    next_starts = [
        position
        for marker in (
            "\nAudit data:",
            "\r\nAudit data:",
            "\nBus data:",
            "\r\nBus data:",
        )
        if (position := text.find(marker, raw_start + 1)) != -1
    ]
    if not next_starts:
        return text[:raw_start]
    return text[:raw_start] + text[min(next_starts) :]


def format_flow_diagram(
    nodes: list[tuple[datetime, int, str]],
) -> str:
    if not nodes:
        return ""
    nodes.sort(key=lambda item: (item[0], item[1]))
    labels: list[str] = []
    last_network_state = ""
    for _, _, label in nodes:
        network_state = next(
            (
                state
                for state in (
                    "[ISO]  TANGO -> NETWORK",
                    "[ISO]  NETWORK -> TANGO",
                    "[SPDH] TANGO -> NETWORK",
                    "[SPDH] NETWORK -> TANGO",
                )
                if label.startswith(state)
            ),
            "",
        )
        is_network_state = bool(network_state)
        if is_network_state:
            if (
                network_state == "[ISO]  TANGO -> NETWORK"
                and label == network_state
                and network_state == last_network_state
            ):
                continue
            last_network_state = network_state
        if label.startswith("[INTERNAL]"):
            labels.append(f"        {label}")
        else:
            labels.append(label)
    return "\n".join(labels)


def unique_nonempty(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def values_for_names(
    fields: dict[str, list[str]],
    audit_values: dict[str, list[str]],
    plain: dict[str, list[str]],
    names: tuple[str, ...],
) -> list[str]:
    values: list[str] = []
    for name in names:
        values.extend(fields.get(name, []))
        values.extend(audit_values.get(name, []))
        values.extend(plain.get(name, []))
    return unique_nonempty(values)


def parse_timestamp(text: str) -> datetime | None:
    precise_match = RECORD_TIMESTAMP_RE.search(text)
    if precise_match:
        digits = precise_match.group(1)
        base = digits[:14]
        fraction = digits[14:20].ljust(6, "0")
        try:
            return datetime.strptime(base + fraction, "%Y%m%d%H%M%S%f")
        except ValueError:
            pass

    match = RECORD_DATE_RE.search(text)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def parse_block(text: str, index: int) -> BlockMeta:
    fields: dict[str, list[str]] = defaultdict(list)
    for match in FIELD_RE.finditer(text):
        fields[match.group("name").strip().lower()].append(match.group("value").strip())

    audit_values: dict[str, list[str]] = defaultdict(list)
    for match in AUDIT_VALUE_RE.finditer(text):
        audit_values[match.group("name").strip().lower()].append(
            match.group("value").strip()
        )

    plain: dict[str, list[str]] = defaultdict(list)
    message_type = ""
    process_name = ""
    flow_dir = ""
    flow_type = ""
    for line in text.splitlines()[:40]:
        match = PLAIN_VALUE_RE.match(line)
        if not match:
            continue
        name = match.group(1).strip().lower().replace(" ", "")
        value = match.group(2).strip()
        plain[name].append(value)
        if name == "messagetype":
            message_type = value
        elif name == "processname":
            process_name = value
        elif name == "flowdir":
            flow_dir = value
        elif name == "flowtype":
            flow_type = value

    trans_uids = unique_nonempty(fields.get("transuid", []) + plain.get("transuid", []))
    trans_uid = trans_uids[0] if trans_uids else None

    mti_values = unique_nonempty(
        fields.get("originmti", [])
        + fields.get("tgoriginmti", [])
        + fields.get("mti", [])
        + audit_values.get("originmti", [])
        + audit_values.get("tgoriginmti", [])
        + fields.get("msgid", [])
        + audit_values.get("msgid", [])
        + audit_values.get("mti", [])
        + HEADER_MTI_RE.findall(message_type)
    )
    rrn_values = unique_nonempty(
        fields.get("retrievrefnumber", [])
        + fields.get("retrievalreferencenumber", [])
        + fields.get("rrn", [])
        + audit_values.get("retrievrefnumber", [])
        + audit_values.get("retrievalreferencenumber", [])
        + audit_values.get("rrn", [])
        + plain.get("rrn", [])
    )
    processing_codes = unique_nonempty(
        fields.get("processingcode", [])
        + fields.get("transactiontype", [])
        + audit_values.get("processingcode", [])
        + audit_values.get("transactiontype", [])
    )
    response_codes = unique_nonempty(
        fields.get("responsecode", [])
        + audit_values.get("responsecode", [])
        + plain.get("responsecode", [])
    )
    tids = values_for_names(
        fields,
        audit_values,
        plain,
        ("tid", "terminal", "terminalid", "trmid", "trmuid"),
    )
    mids = values_for_names(
        fields,
        audit_values,
        plain,
        ("mid", "merchantid", "cardacceptorid", "merchant"),
    )
    amounts = values_for_names(
        fields,
        audit_values,
        plain,
        ("transactionamt", "transactionamount", "amt", "amount"),
    )
    currencies = values_for_names(
        fields,
        audit_values,
        plain,
        ("currency", "currencycode", "currcode"),
    )
    acquirer_ids = set(
        unique_nonempty(
            fields.get("acqid", [])
            + fields.get("acquirerid", [])
            + fields.get("acquiringinstid", [])
            + audit_values.get("acqid", [])
            + audit_values.get("acquirerid", [])
            + audit_values.get("acquiringinstid", [])
        )
    )

    identifiers: set[tuple[str, str]] = set()
    identifier_names = {
        "rrn": ("retrievrefnumber", "retrievalreferencenumber", "rrn"),
        "stan": ("stan", "auditnumber", "origauditnumber", "transseqno"),
        "sequence_number": ("sequence_number", "sequencenumber"),
        "authcode": ("authcode", "authid", "approvalcode", "authorizationcode"),
        "trmuid": ("trmuid",),
        "msguid": ("msguid",),
    }
    for canonical_name, names in identifier_names.items():
        for name in names:
            for value in (
                fields.get(name, [])
                + audit_values.get(name, [])
                + plain.get(name, [])
            ):
                clean_value = value.strip()
                if clean_value:
                    identifiers.add((canonical_name, clean_value))
    for canonical_name, values in (
        ("tid", tids),
        ("mid", mids),
        ("amount", amounts),
        ("currency", currencies),
    ):
        for value in values:
            identifiers.add((canonical_name, value))

    flow_values = plain.get("flowdir", [])
    is_request = any("REQUEST" in value.upper() for value in flow_values)
    is_request = is_request or any(
        "REQUEST" in value.upper() for value in plain.get("flowtype", [])
    )
    is_request = is_request or "REQUEST" in message_type.upper()

    return BlockMeta(
        index=index,
        timestamp=parse_timestamp(text),
        is_request=is_request,
        message_type=message_type,
        process_name=process_name,
        flow_dir=flow_dir,
        flow_type=flow_type,
        trans_uid=trans_uid,
        mti_values=mti_values,
        rrn_values=rrn_values,
        processing_codes=processing_codes,
        response_codes=response_codes,
        tids=tids,
        mids=mids,
        amounts=amounts,
        currencies=currencies,
        acquirer_ids=acquirer_ids,
        identifiers=identifiers,
    )


def parse_block_for_list(text: str, index: int) -> BlockMeta:
    parse_text = without_raw_data_fast(text)
    fields: dict[str, list[str]] = defaultdict(list)
    audit_values: dict[str, list[str]] = defaultdict(list)
    plain: dict[str, list[str]] = defaultdict(list)
    message_type = ""
    process_name = ""
    flow_dir = ""
    flow_type = ""
    timestamp: datetime | None = None
    for line_number, line in enumerate(parse_text.splitlines()):
        if line_number < 40:
            if ":" in line:
                plain_name, plain_value = line.split(":", 1)
                name = plain_name.strip().lower().replace(" ", "")
                value = plain_value.strip()
                if name in {
                    "messagetype",
                    "processname",
                    "flowdir",
                    "flowtype",
                    "transuid",
                    "rrn",
                    "responsecode",
                    "tid",
                    "terminal",
                    "terminalid",
                    "trmid",
                    "trmuid",
                    "mid",
                    "merchantid",
                    "cardacceptorid",
                    "merchant",
                    "amt",
                    "amount",
                    "transactionamount",
                    "transactionamt",
                    "currency",
                    "currencycode",
                    "currcode",
                }:
                    plain[name].append(value)
                if name == "messagetype":
                    message_type = value
                elif name == "processname":
                    process_name = value
                elif name == "flowdir":
                    flow_dir = value
                elif name == "flowtype":
                    flow_type = value
            if timestamp is None and (
                line.startswith("RP date time") or line.startswith("SP date time")
            ):
                precise_match = re.search(r"timestamp:\s*(\d{14,20})", line)
                if precise_match:
                    digits = precise_match.group(1)
                    base = digits[:14]
                    fraction = digits[14:20].ljust(6, "0")
                    try:
                        timestamp = datetime.strptime(
                            base + fraction,
                            "%Y%m%d%H%M%S%f",
                        )
                    except ValueError:
                        timestamp = None
                if timestamp is None:
                    date_match = re.search(
                        r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})",
                        line,
                    )
                    if date_match:
                        try:
                            timestamp = datetime.strptime(
                                date_match.group(1),
                                "%Y-%m-%d %H:%M:%S",
                            )
                        except ValueError:
                            timestamp = None
        if "<field" in line and "name=" in line:
            search_from = 0
            while True:
                name_pos = line.find("name=", search_from)
                if name_pos == -1:
                    break
                quote_pos = name_pos + 5
                if quote_pos >= len(line) or line[quote_pos] not in {"'", '"'}:
                    search_from = name_pos + 5
                    continue
                quote = line[quote_pos]
                name_end = line.find(quote, quote_pos + 1)
                if name_end == -1:
                    break
                name = line[quote_pos + 1 : name_end].strip().lower()
                value_start = line.find(">", name_end)
                value_end = line.find("</field>", value_start + 1)
                if (
                    name in LIST_FIELD_NAMES
                    and value_start != -1
                    and value_end != -1
                ):
                    fields[name].append(line[value_start + 1 : value_end].strip())
                search_from = name_end + 1
        if ":" in line and ("asc<" in line or "int<" in line):
            audit_name, audit_value = line.split(":", 1)
            audit_name = re.sub(
                r"^\s*(?:\[[^\]]+\]|\d+\.)\s*",
                "",
                audit_name,
            )
            name = audit_name.strip().lower()
            if name in LIST_FIELD_NAMES:
                value_start = audit_value.find("<")
                value_end = audit_value.find(">", value_start + 1)
                if value_start != -1 and value_end != -1:
                    audit_values[name].append(
                        audit_value[value_start + 1 : value_end].strip()
                    )

    trans_uids = unique_nonempty(fields.get("transuid", []) + plain.get("transuid", []))
    trans_uid = trans_uids[0] if trans_uids else None
    mti_values = unique_nonempty(
        fields.get("originmti", [])
        + fields.get("tgoriginmti", [])
        + fields.get("mti", [])
        + audit_values.get("originmti", [])
        + audit_values.get("tgoriginmti", [])
        + fields.get("msgid", [])
        + audit_values.get("msgid", [])
        + audit_values.get("mti", [])
        + HEADER_MTI_RE.findall(message_type)
    )
    rrn_values = unique_nonempty(
        fields.get("retrievrefnumber", [])
        + fields.get("retrievalreferencenumber", [])
        + fields.get("rrn", [])
        + audit_values.get("retrievrefnumber", [])
        + audit_values.get("retrievalreferencenumber", [])
        + audit_values.get("rrn", [])
        + plain.get("rrn", [])
    )
    processing_codes = unique_nonempty(
        fields.get("processingcode", [])
        + fields.get("transactiontype", [])
        + audit_values.get("processingcode", [])
        + audit_values.get("transactiontype", [])
    )
    response_codes = unique_nonempty(
        fields.get("responsecode", [])
        + audit_values.get("responsecode", [])
        + plain.get("responsecode", [])
    )
    tids = values_for_names(
        fields,
        audit_values,
        plain,
        ("tid", "terminal", "terminalid", "trmid", "trmuid"),
    )
    mids = values_for_names(
        fields,
        audit_values,
        plain,
        ("mid", "merchantid", "cardacceptorid", "merchant"),
    )
    amounts = values_for_names(
        fields,
        audit_values,
        plain,
        ("transactionamt", "transactionamount", "amt", "amount"),
    )
    currencies = values_for_names(
        fields,
        audit_values,
        plain,
        ("currency", "currencycode", "currcode"),
    )
    acquirer_ids = set(
        unique_nonempty(
            fields.get("acqid", [])
            + fields.get("acquirerid", [])
            + fields.get("acquiringinstid", [])
            + audit_values.get("acqid", [])
            + audit_values.get("acquirerid", [])
            + audit_values.get("acquiringinstid", [])
        )
    )

    identifiers: set[tuple[str, str]] = set()
    identifier_names = {
        "rrn": ("retrievrefnumber", "retrievalreferencenumber", "rrn"),
        "stan": ("stan", "auditnumber", "origauditnumber", "transseqno"),
        "sequence_number": ("sequence_number", "sequencenumber"),
        "authcode": ("authcode", "authid", "approvalcode", "authorizationcode"),
    }
    for canonical_name, names in identifier_names.items():
        for name in names:
            for value in fields.get(name, []) + audit_values.get(name, []) + plain.get(name, []):
                clean_value = value.strip()
                if clean_value:
                    identifiers.add((canonical_name, clean_value))
    for canonical_name, values in (
        ("tid", tids),
        ("mid", mids),
        ("amount", amounts),
        ("currency", currencies),
    ):
        for value in values:
            identifiers.add((canonical_name, value))

    flow_values = plain.get("flowdir", [])
    is_request = any("REQUEST" in value.upper() for value in flow_values)
    is_request = is_request or any(
        "REQUEST" in value.upper() for value in plain.get("flowtype", [])
    )
    is_request = is_request or "REQUEST" in message_type.upper()

    return BlockMeta(
        index=index,
        timestamp=timestamp,
        is_request=is_request,
        message_type=message_type,
        process_name=process_name,
        flow_dir=flow_dir,
        flow_type=flow_type,
        trans_uid=trans_uid,
        mti_values=mti_values,
        rrn_values=rrn_values,
        processing_codes=processing_codes,
        response_codes=response_codes,
        tids=tids,
        mids=mids,
        amounts=amounts,
        currencies=currencies,
        acquirer_ids=acquirer_ids,
        identifiers=identifiers,
    )


def select_iso_mti(transaction: Transaction) -> str:
    candidates = transaction.request_mtis + transaction.mtis
    # Prefer business TANGO MTIs over ISO and internal security/action MTIs.
    for value in candidates:
        if value in TANGO_TRANSACTION_MTI_NAMES:
            return value
    for value in candidates:
        if value in MTI_NAMES:
            return value
    return candidates[0] if candidates else "UNKNOWN_MTI"


def select_rrn(transaction: Transaction) -> str:
    return transaction.rrns[0] if transaction.rrns else "NO_RRN"


def select_identifier(transaction: Transaction, name: str) -> str:
    for identifier_name, value in sorted(transaction.identifiers):
        if identifier_name == name and value:
            return value
    return ""


def select_first(values: list[str]) -> str:
    return next(
        (
            value
            for value in values
            if value and value.strip().lower() not in {"not available", "na", "n/a"}
        ),
        "",
    )


def select_amount_display(transaction: Transaction) -> str:
    candidates = [
        value
        for value in transaction.amounts
        if value and value.strip().lower() not in {"not available", "na", "n/a"}
    ]
    # ISO DE4 is a 12-digit value. Prefer it to shorter protocol-specific
    # representations and to auxiliary token amounts collected in the same block.
    amount = next(
        (value for value in candidates if re.fullmatch(r"\d{12}", value)),
        candidates[0] if candidates else "",
    )
    if not amount:
        return ""
    if re.search(r"\([^()]+\)$", amount):
        return amount
    currency = select_first(transaction.currencies)
    return f"{amount}({currency})" if currency else amount


def select_response_code(values: list[str]) -> str:
    return next((value for value in values if value), "NA")


def response_code_component(code: str, names: dict[str, str]) -> str:
    if code == "NA":
        return "Not_available(NA)"
    return f"{names.get(code, 'Unknown_response_code')}({code})"


def safe_component(value: str) -> str:
    cleaned = SAFE_FILENAME_RE.sub("_", value.strip()).strip("._")
    return cleaned or "UNKNOWN"


def transaction_protocol_suffix(transaction: Transaction) -> str:
    has_ptms = any(name.upper().startswith("PTMS") for name in transaction.process_names)
    has_opn = any(name.upper().startswith("OPN") for name in transaction.process_names)
    if has_ptms and has_opn:
        return "SPDH_ISO"
    if has_ptms:
        return "SPDH"
    if has_opn:
        return "ISO"
    return "SUMMARY"


def build_filenames(transactions: dict[str, Transaction]) -> dict[str, str]:
    filenames: dict[str, str] = {}
    used: dict[str, str] = {}
    for uid, transaction in sorted(transactions.items(), key=lambda item: item[1].first_index):
        filename = f"{safe_component(uid)}.log"

        if filename.casefold() in used and used[filename.casefold()] != uid:
            filename = filename[:-4] + f"_{transaction.first_index}.log"
        used[filename.casefold()] = uid
        filenames[uid] = filename
    return filenames


def build_summary_filenames(
    transactions: dict[str, Transaction],
    protocol_choice: str | None = None,
) -> dict[str, str]:
    filenames: dict[str, str] = {}
    used: dict[str, str] = {}
    selected_suffix = PROTOCOL_SUFFIX_BY_CHOICE.get((protocol_choice or "").strip())
    for uid, transaction in sorted(transactions.items(), key=lambda item: item[1].first_index):
        suffix = selected_suffix or transaction_protocol_suffix(transaction)
        filename = f"{safe_component(uid)}_{suffix}.log"
        if filename.casefold() in used and used[filename.casefold()] != uid:
            filename = filename[:-4] + f"_{transaction.first_index}.log"
        used[filename.casefold()] = uid
        filenames[uid] = filename
    return filenames


def resolve_missing_uid(
    block: BlockMeta,
    identifier_index: dict[tuple[str, str], set[str]],
    transactions: dict[str, Transaction],
) -> str | None:
    candidates: set[str] = set()
    for identifier in block.identifiers:
        candidates.update(identifier_index.get(identifier, set()))
    if not candidates or block.timestamp is None:
        return None

    ranked: list[tuple[float, str]] = []
    for uid in candidates:
        reference_time = transactions[uid].request_timestamp or transactions[uid].first_timestamp
        if reference_time is not None:
            ranked.append((abs((block.timestamp - reference_time).total_seconds()), uid))
    ranked.sort()
    if not ranked or ranked[0][0] > CORRELATION_WINDOW_SECONDS:
        return None
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        return None
    return ranked[0][1]


def build_uid_pattern(transaction_uids: set[str] | None) -> re.Pattern[str] | None:
    if not transaction_uids:
        return None
    alternatives = "|".join(
        re.escape(uid) for uid in sorted(transaction_uids, key=len, reverse=True)
    )
    return re.compile(rf"(?<![A-Za-z0-9])(?:{alternatives})(?![A-Za-z0-9])")


def iter_blocks_from_text(text: str) -> Iterator[str]:
    for part in re.split(
        rf"(?=^{re.escape(SEPARATOR_PREFIX)})",
        text,
        flags=re.MULTILINE,
    ):
        if part:
            yield part


def iter_target_blocks_from_text(
    text: str,
    target_pattern: re.Pattern[str],
) -> Iterator[str]:
    seen_ranges: set[tuple[int, int]] = set()
    for match in target_pattern.finditer(text):
        start = text.rfind(SEPARATOR_PREFIX, 0, match.start())
        if start == -1:
            start = 0
        end = text.find(SEPARATOR_PREFIX, match.end())
        if end == -1:
            end = len(text)
        block_range = (start, end)
        if block_range in seen_ranges:
            continue
        seen_ranges.add(block_range)
        block_text = text[start:end]
        if block_text:
            yield block_text


def iter_marker_blocks_from_text(
    text: str,
    marker_pattern: re.Pattern[str],
) -> Iterator[str]:
    seen_ranges: set[tuple[int, int]] = set()
    for match in marker_pattern.finditer(text):
        start = text.rfind(SEPARATOR_PREFIX, 0, match.start())
        if start == -1:
            start = 0
        end = text.find(SEPARATOR_PREFIX, match.end())
        if end == -1:
            end = len(text)
        block_range = (start, end)
        if block_range in seen_ranges:
            continue
        seen_ranges.add(block_range)
        block_text = text[start:end]
        if block_text:
            yield block_text


def file_text_cache_key(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return (str(path.resolve()), stat.st_mtime_ns, stat.st_size)


def input_paths_cache_key(input_paths: list[Path]) -> tuple[tuple[str, int, int], ...]:
    return tuple(file_text_cache_key(path) for path in input_paths)


def read_text_cached(path: Path) -> str:
    key = file_text_cache_key(path)
    cached = FILE_TEXT_CACHE.get(key)
    if cached is not None:
        return cached

    path_key = key[0]
    stale_keys = [
        existing_key for existing_key in FILE_TEXT_CACHE if existing_key[0] == path_key
    ]
    for stale_key in stale_keys:
        del FILE_TEXT_CACHE[stale_key]

    text = path.read_text(encoding="utf-8", errors="replace")
    FILE_TEXT_CACHE[key] = text
    return text


def cached_target_blocks(
    input_paths: list[Path],
    target_uids: set[str] | None,
) -> list[tuple[int, str]] | None:
    if not target_uids:
        return None
    blocks_by_uid = AUDIT_BLOCK_TEXT_CACHE.get(input_paths_cache_key(input_paths))
    if blocks_by_uid is None:
        return None
    blocks: list[tuple[int, str]] = []
    for uid in target_uids:
        blocks.extend(blocks_by_uid.get(uid, []))
    blocks.sort(key=lambda item: item[0])
    return blocks


def iter_input_blocks(
    input_paths: list[Path],
    progress_callback: Callable[[int, int, str], None] | None = None,
    load_into_memory: bool = False,
    target_uids: set[str] | None = None,
) -> Iterator[tuple[int, str]]:
    index = 0
    total_bytes = sum(path.stat().st_size for path in input_paths)
    processed_bytes = 0
    last_reported_bytes = 0
    target_pattern = build_uid_pattern(target_uids)

    def report(path: Path, force: bool = False) -> None:
        nonlocal last_reported_bytes
        if not progress_callback:
            return
        if force or processed_bytes - last_reported_bytes >= 1024 * 1024:
            last_reported_bytes = processed_bytes
            progress_callback(
                processed_bytes,
                total_bytes,
                f"Load transactions: {path.name}",
            )

    for input_path in input_paths:
        if load_into_memory:
            text = read_text_cached(input_path)
            processed_bytes += input_path.stat().st_size
            report(input_path, force=True)
            if target_pattern is not None:
                block_iterable = iter_target_blocks_from_text(text, target_pattern)
            else:
                block_iterable = iter_blocks(io.StringIO(text))
            for block_text in block_iterable:
                yield index, block_text
                index += 1
            continue

        lines: list[str] = []
        pending_separator: str | None = None
        with input_path.open("rb") as handle:
            for raw_line in handle:
                processed_bytes += len(raw_line)
                line = raw_line.decode("utf-8", errors="replace")
                report(input_path)
                if line.startswith(SEPARATOR_PREFIX):
                    if pending_separator is not None:
                        lines.append(pending_separator)
                    pending_separator = line
                    continue

                if pending_separator is not None:
                    if re.match(r"^(?:RP|SP) date time(?: GMT)?\s*:", line):
                        if lines:
                            yield index, "".join(lines)
                            index += 1
                        lines = [pending_separator, line]
                    else:
                        lines.extend((pending_separator, line))
                    pending_separator = None
                else:
                    lines.append(line)
        if pending_separator is not None:
            lines.append(pending_separator)
        if lines:
            yield index, "".join(lines)
            index += 1
        report(input_path, force=True)
    if progress_callback and total_bytes == 0:
        progress_callback(1, 1, "Load transactions")


def scan_transactions(
    input_paths: list[Path],
    progress_callback: Callable[[int, int, str], None] | None = None,
    load_into_memory: bool = False,
    correlate_missing: bool = True,
    target_uids: set[str] | None = None,
) -> tuple[dict[str, Transaction], dict[int, str]]:
    transactions: dict[str, Transaction] = {}
    missing_blocks: list[BlockMeta] = []

    cached_blocks = cached_target_blocks(input_paths, target_uids)
    block_iterable = (
        cached_blocks
        if cached_blocks is not None
        else iter_input_blocks(
            input_paths,
            progress_callback,
            load_into_memory=load_into_memory,
            target_uids=target_uids,
        )
    )
    for index, text in block_iterable:
        if (
            not correlate_missing
            and "transUId" not in text
            and "transUid" not in text
        ):
            continue
        block = parse_block(text, index)
        if block.trans_uid:
            transaction = transactions.setdefault(
                block.trans_uid,
                Transaction(trans_uid=block.trans_uid, first_index=index),
            )
            transaction.add(block)
        elif correlate_missing:
            missing_blocks.append(block)

    if not correlate_missing:
        return transactions, {}

    identifier_index: dict[tuple[str, str], set[str]] = defaultdict(set)
    for uid, transaction in transactions.items():
        for identifier in transaction.identifiers:
            identifier_index[identifier].add(uid)

    correlated: dict[int, str] = {}
    for block in missing_blocks:
        uid = resolve_missing_uid(block, identifier_index, transactions)
        if uid:
            correlated[block.index] = uid
            transactions[uid].add(block)
    return transactions, correlated


def scan_transactions_for_list(
    input_paths: list[Path],
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict[str, Transaction]:
    transactions: dict[str, Transaction] = {}
    blocks_by_uid: dict[str, list[tuple[int, str]]] = defaultdict(list)
    index = 0
    total_bytes = sum(path.stat().st_size for path in input_paths)
    processed_bytes = 0
    for input_path in input_paths:
        text = read_text_cached(input_path)
        processed_bytes += input_path.stat().st_size
        if progress_callback:
            progress_callback(
                processed_bytes,
                total_bytes,
                f"Load transactions: {input_path.name}",
            )
        for block_text in iter_marker_blocks_from_text(text, TRANS_UID_MARKER_RE):
            block = parse_block_for_list(block_text, index)
            if not block.trans_uid:
                index += 1
                continue
            blocks_by_uid[block.trans_uid].append((index, block_text))
            transaction = transactions.setdefault(
                block.trans_uid,
                Transaction(trans_uid=block.trans_uid, first_index=index),
            )
            transaction.add(block)
            index += 1
    AUDIT_BLOCK_TEXT_CACHE[input_paths_cache_key(input_paths)] = blocks_by_uid
    return transactions


def collect_tango_lines(
    tango_log_path: Path | None,
    transaction_uids: set[str],
) -> dict[str, list[str]]:
    lines_by_uid: dict[str, list[str]] = defaultdict(list)
    if not tango_log_path or not tango_log_path.is_file() or not transaction_uids:
        return lines_by_uid

    uid_pattern = build_uid_pattern(transaction_uids)
    if uid_pattern is None:
        return lines_by_uid
    for line in read_text_cached(tango_log_path).splitlines(keepends=True):
        matched_uids = {match.group(0) for match in uid_pattern.finditer(line)}
        for uid in matched_uids:
            lines_by_uid[uid].append(line)
    return lines_by_uid


def tango_field(lines: list[str], name: str) -> str:
    pattern = re.compile(rf"(?:^|/){re.escape(name)}=([^/|]*)", re.IGNORECASE)
    for line in reversed(lines):
        match = pattern.search(line)
        if match and match.group(1).strip():
            return match.group(1).strip()
    return ""


def display_rc_description(code: str) -> str:
    description = ISO_RC_NAMES.get(code, "Unknown response code")
    return description.replace("_", " ").title()


def transaction_status(iso_rc: str, spdh_rc: str) -> str:
    known_codes = [code for code in (iso_rc, spdh_rc) if code != "NA"]
    if not known_codes:
        return "UNKNOWN"
    if iso_rc not in {"NA", "00"} or spdh_rc not in {"NA", "000"}:
        return "DECLINED"
    return "APPROVED"


def format_transaction_summary(
    transaction: Transaction,
    tango_lines: list[str],
) -> str:
    timestamp = transaction.request_timestamp or transaction.first_timestamp
    readable_timestamp = (
        timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        if timestamp
        else "Not available"
    )
    rrn = select_rrn(transaction)
    tid = (
        select_first(transaction.tids)
        or tango_field(tango_lines, "trmId")
        or "Not available"
    )
    mid = (
        select_first(transaction.mids)
        or tango_field(tango_lines, "merchantId")
        or tango_field(tango_lines, "merId")
        or "Not available"
    )
    amount = select_amount_display(transaction)
    if not amount:
        tango_amount = tango_field(tango_lines, "amount")
        tango_currency = tango_field(tango_lines, "currency")
        amount = (
            f"{tango_amount}({tango_currency})"
            if tango_amount and tango_currency
            else tango_amount
        )
    if not amount:
        amount = "Not available"
    acquirer = tango_field(tango_lines, "acqId")
    if not acquirer:
        acquirer = sorted(transaction.acquirer_ids)[0] if transaction.acquirer_ids else "Not available"
    mti = tango_field(tango_lines, "MTI") or select_iso_mti(transaction)
    result_code = tango_field(tango_lines, "resultCode") or "Not available"
    spdh_rc = (
        tango_field(tango_lines, "responseCode")
        or select_response_code(transaction.spdh_response_codes)
    )
    iso_rc = select_response_code(transaction.iso_response_codes)
    network_rc = (
        f"{iso_rc} ({display_rc_description(iso_rc)})"
        if iso_rc != "NA"
        else "Not available"
    )

    def field_line(label: str, value: str) -> str:
        return f"{label:<20} : {value}"

    lines = [
        SECTION_SEPARATOR,
        "TRANSACTION SUMMARY",
        SECTION_SEPARATOR,
        field_line("transUId", transaction.trans_uid),
    ]
    if rrn != "NO_RRN":
        lines.append(field_line("RRN", rrn))
    lines.extend(
        [
            field_line("Date/Time", readable_timestamp),
            "",
            field_line("TID", tid),
            field_line("MID", mid),
            field_line("AMT", amount),
            field_line("Acquirer", acquirer),
            field_line("MTI", mti),
            "",
            field_line("Internal result Code", result_code),
            field_line("RC_SPDH", spdh_rc),
            field_line("RC_ISO", network_rc),
            "",
            field_line("Status", transaction_status(iso_rc, spdh_rc)),
            SECTION_SEPARATOR,
        ]
    )
    return "\n".join(lines)


def format_flow_section(flow_diagram: str) -> str:
    if not flow_diagram:
        return ""
    return "\n".join(
        (
            SECTION_SEPARATOR,
            "TRANSACTION FLOW",
            SECTION_SEPARATOR,
            flow_diagram,
            SECTION_SEPARATOR,
        )
    )


def write_outputs(
    input_paths: list[Path],
    output_dir: Path,
    filenames: dict[str, str],
    summary_filenames: dict[str, str] | None,
    correlated: dict[int, str],
    excluded_uids: set[str] | None = None,
    include_unassigned: bool = True,
    cleanup_excluded: bool = True,
    tango_lines_by_uid: dict[str, list[str]] | None = None,
    transaction_headers_by_uid: dict[str, str] | None = None,
    protocol_choice: str | None = None,
    include_byte_data: bool = True,
    include_internal: bool = True,
    include_tango_to_network: bool = True,
    include_network_to_tango: bool = True,
    target_uids: set[str] | None = None,
) -> tuple[int, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_paths = {output_dir / filename for filename in filenames.values()}
    if include_unassigned:
        generated_paths.add(output_dir / "NO_TRANSUID.log")
    if cleanup_excluded:
        for uid in excluded_uids or set():
            uid_component = safe_component(uid)
            for old_path in output_dir.glob(f"{uid_component}*.log"):
                old_path.unlink(missing_ok=True)
    for uid, filename in filenames.items():
        current_path = output_dir / filename
        current_paths = {current_path}
        uid_component = safe_component(uid)
        for old_path in output_dir.glob(f"{uid_component}*.log"):
            if old_path not in current_paths:
                old_path.unlink(missing_ok=True)
        for old_path in output_dir.glob(f"*_{uid_component}_*.log"):
            if old_path not in current_paths:
                old_path.unlink(missing_ok=True)
    for path in generated_paths:
        path.unlink(missing_ok=True)

    transaction_blocks = 0
    no_transuid_blocks = 0
    blocks_by_path: dict[Path, list[tuple[datetime, int, str]]] = defaultdict(list)
    flow_diagram_nodes: dict[
        str,
        list[tuple[datetime, int, str]],
    ] = defaultdict(list)
    uid_by_path: dict[Path, str] = {}
    selected_protocol_suffix = PROTOCOL_SUFFIX_BY_CHOICE.get((protocol_choice or "").strip())
    cached_blocks = cached_target_blocks(input_paths, target_uids)
    block_iterable = (
        cached_blocks
        if cached_blocks is not None
        else iter_input_blocks(
            input_paths,
            load_into_memory=bool(target_uids),
            target_uids=target_uids,
        )
    )
    for index, text in block_iterable:
        block = parse_block(text, index)
        normalized_flow = block.flow_dir.upper().replace(" ", "")
        process_name = block.process_name.upper()
        if selected_protocol_suffix == "SPDH" and not process_name.startswith("PTMS"):
            continue
        if selected_protocol_suffix == "ISO" and not process_name.startswith("OPN"):
            continue
        is_network_direction = normalized_flow in {
            "TANGO-->NETWORK",
            "NETWORK-->TANGO",
        }
        if not is_network_direction and not include_internal:
            continue
        if normalized_flow == "TANGO-->NETWORK" and not include_tango_to_network:
            continue
        if normalized_flow == "NETWORK-->TANGO" and not include_network_to_tango:
            continue
        uid = block.trans_uid or correlated.get(index)
        if uid and excluded_uids and uid in excluded_uids:
            continue
        if uid and uid in filenames:
            target = output_dir / filenames[uid]
            uid_by_path[target] = uid
            transaction_blocks += 1
        else:
            if not include_unassigned:
                continue
            target = output_dir / "NO_TRANSUID.log"
            no_transuid_blocks += 1
        sort_time = block.timestamp or datetime.max
        block_text = text if include_byte_data else without_byte_data(text)
        blocks_by_path[target].append((sort_time, index, block_text))
        if uid and uid in filenames:
            if process_name.startswith("PTMS"):
                if normalized_flow == "NETWORK-->TANGO":
                    label = "[SPDH] NETWORK -> TANGO"
                    if "RESPONSE" in block.flow_type.upper():
                        rc = select_response_code(block.response_codes)
                        label += (
                            "  "
                            + response_code_component(rc, SPDH_RC_NAMES)
                        )
                    flow_diagram_nodes[uid].append(
                        (
                            sort_time,
                            index,
                            label,
                        )
                    )
                elif normalized_flow == "TANGO-->NETWORK":
                    label = "[SPDH] TANGO -> NETWORK"
                    if "RESPONSE" in block.flow_type.upper():
                        rc = select_response_code(block.response_codes)
                        label += (
                            "  "
                            + response_code_component(rc, SPDH_RC_NAMES)
                        )
                    flow_diagram_nodes[uid].append(
                        (
                            sort_time,
                            index,
                            label,
                        )
                    )
                elif normalized_flow == "REQUEST":
                    message_match = MESSAGE_MTI_RE.match(block.message_type)
                    if message_match:
                        description = message_match.group("description").strip()
                        mti = message_match.group("mti")
                        flow_diagram_nodes[uid].append(
                            (
                                sort_time,
                                index,
                                f"[INTERNAL] {mti}  {description}",
                            )
                        )
            elif process_name.startswith("OPN"):
                if is_network_direction:
                    direction_label = (
                        "TANGO -> NETWORK"
                        if normalized_flow == "TANGO-->NETWORK"
                        else "NETWORK -> TANGO"
                    )
                    label = f"[ISO]  {direction_label}"
                    if "RESPONSE" in block.flow_type.upper():
                        rc = select_response_code(block.response_codes)
                        label += (
                            "  "
                            + response_code_component(rc, ISO_RC_NAMES)
                        )
                    flow_diagram_nodes[uid].append(
                        (
                            sort_time,
                            index,
                            label,
                        )
                    )
                elif normalized_flow == "REQUEST":
                    message_match = MESSAGE_MTI_RE.match(block.message_type)
                    if message_match:
                        description = message_match.group("description").strip()
                        mti = message_match.group("mti")
                        flow_diagram_nodes[uid].append(
                            (
                                sort_time,
                                index,
                                f"[INTERNAL] {mti}  {description}",
                            )
                        )

    def write_file(
        target: Path,
        blocks: list[tuple[datetime, int, str]],
        summary_header: str = "",
        flow_diagram: str = "",
    ) -> None:
        blocks.sort(key=lambda item: (item[0], item[1]))
        with target.open("w", encoding="utf-8", newline="") as output:
            uid = uid_by_path.get(target)
            if summary_header:
                output.write(summary_header)
                output.write("\n\n")
            if flow_diagram:
                output.write(format_flow_section(flow_diagram))
                output.write("\n\n")
            tango_lines = (tango_lines_by_uid or {}).get(uid or "", [])
            for line in tango_lines:
                output.write(line)
                if not line.endswith(("\n", "\r")):
                    output.write("\n")
            if tango_lines:
                output.write("\n")
            for _, _, text in blocks:
                output.write(text)

    for target, blocks in blocks_by_path.items():
        uid = uid_by_path.get(target)
        write_file(
            target,
            blocks,
            (transaction_headers_by_uid or {}).get(uid or "", ""),
            format_flow_diagram(flow_diagram_nodes.get(uid or "", [])),
        )
    return transaction_blocks, no_transuid_blocks


def split_audit_files(
    input_paths: list[Path],
    output_dir: Path,
    bank: str | None = None,
    transaction_uid: str | None = None,
    transaction_uids: set[str] | None = None,
    stan: str | None = None,
    rrn: str | None = None,
    authcode: str | None = None,
    sequence_number: str | None = None,
    response_code_spdh: str | None = None,
    response_code_iso: str | None = None,
    tango_log_path: Path | None = None,
    protocol_choice: str | None = None,
    include_byte_data: bool = True,
    include_internal: bool = True,
    include_tango_to_network: bool = True,
    include_network_to_tango: bool = True,
) -> dict[str, int]:
    if not input_paths:
        raise ValueError("No audit files were supplied for analysis.")
    transaction_uid = (transaction_uid or "").strip()
    selected_transaction_uids = set(transaction_uids or set())
    if transaction_uid:
        selected_transaction_uids.add(transaction_uid)
    use_target_fast_path = bool(selected_transaction_uids)
    transactions, correlated = scan_transactions(
        input_paths,
        load_into_memory=use_target_fast_path,
        correlate_missing=not use_target_fast_path,
        target_uids=selected_transaction_uids if use_target_fast_path else None,
    )
    excluded_uids: set[str] = set()
    if bank and not use_target_fast_path:
        expected_ids = BANK_ACQUIRER_IDS.get(bank, set())
        matching = {
            uid: transaction
            for uid, transaction in transactions.items()
            if (
                transaction.acquirer_ids & expected_ids
                or any(
                    bank_audit_code_matches(bank, process_name)
                    for process_name in transaction.process_names
                )
            )
        }
        excluded_uids = set(transactions) - set(matching)
        transactions = matching
    if selected_transaction_uids:
        targeted = {
            uid: transaction
            for uid, transaction in transactions.items()
            if uid in selected_transaction_uids
        }
        excluded_uids.update(set(transactions) - set(targeted))
        transactions = targeted
    identifier_filters = {
        "stan": (stan or "").strip(),
        "rrn": (rrn or "").strip(),
        "authcode": (authcode or "").strip(),
        "sequence_number": (sequence_number or "").strip(),
    }
    identifier_filters = {
        name: value for name, value in identifier_filters.items() if value
    }
    if identifier_filters:
        targeted = {
            uid: transaction
            for uid, transaction in transactions.items()
            if all(
                (name, value) in transaction.identifiers
                for name, value in identifier_filters.items()
            )
        }
        excluded_uids.update(set(transactions) - set(targeted))
        transactions = targeted
    response_code_spdh = (response_code_spdh or "").strip()
    response_code_iso = (response_code_iso or "").strip()
    if response_code_spdh or response_code_iso:
        targeted = {
            uid: transaction
            for uid, transaction in transactions.items()
            if (
                (not response_code_spdh or response_code_spdh in transaction.spdh_response_codes)
                and (not response_code_iso or response_code_iso in transaction.iso_response_codes)
            )
        }
        excluded_uids.update(set(transactions) - set(targeted))
        transactions = targeted
    protocol_choice = (protocol_choice or "").strip()
    if protocol_choice:
        if protocol_choice not in PROTOCOL_SUFFIX_BY_CHOICE:
            raise ValueError(f"Unknown protocol selection: {protocol_choice}")
    filenames = build_filenames(transactions)
    tango_lines_by_uid = collect_tango_lines(tango_log_path, set(transactions))
    transaction_headers_by_uid: dict[str, str] = {}
    for uid, transaction in transactions.items():
        transaction_headers_by_uid[uid] = format_transaction_summary(
            transaction,
            tango_lines_by_uid.get(uid, []),
        )
    transaction_blocks, no_transuid_blocks = write_outputs(
        input_paths,
        output_dir,
        filenames,
        None,
        correlated,
        excluded_uids,
        include_unassigned=(
            not selected_transaction_uids
            and not identifier_filters
            and not response_code_spdh
            and not response_code_iso
            and not protocol_choice
        ),
        cleanup_excluded=not selected_transaction_uids and not identifier_filters and not response_code_spdh and not response_code_iso,
        tango_lines_by_uid=tango_lines_by_uid,
        transaction_headers_by_uid=transaction_headers_by_uid,
        protocol_choice=protocol_choice,
        include_byte_data=include_byte_data,
        include_internal=include_internal,
        include_tango_to_network=include_tango_to_network,
        include_network_to_tango=include_network_to_tango,
        target_uids=set(transactions) if use_target_fast_path else None,
    )
    return {
        "transactions": len(transactions),
        "transaction_blocks": transaction_blocks,
        "correlated_blocks": len(correlated),
        "no_transuid_blocks": no_transuid_blocks,
        "tango_lines": sum(len(lines) for lines in tango_lines_by_uid.values()),
    }


def install_interrupt_handler() -> None:
    def handler(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, handler)


def run_remote_command(command: str, sudo: bool = False) -> str:
    if shutil.which("ssh") is None:
        raise RuntimeError("The 'ssh' executable was not found on PATH.")
    remote_command = f"sudo -S -p '' {command}" if sudo else command
    args = [
        "ssh",
        "-o",
        f"ConnectTimeout={SSH_TIMEOUT}",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-p",
        str(SSH_PORT),
        f"{RUNTIME_SETTINGS.user}@{DEFAULT_HOST}",
        remote_command,
    ]
    completed = subprocess.run(
        args,
        input=RUNTIME_SETTINGS.sudo_password + "\n" if sudo else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=SSH_TIMEOUT,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout


def download_remote_file(remote_path: str, local_dir: Path) -> Path:
    local_dir.mkdir(parents=True, exist_ok=True)
    local_path = local_dir / Path(remote_path).name
    if local_path.is_file():
        return local_path
    if shutil.which("scp") is None:
        raise RuntimeError("The 'scp' executable was not found on PATH.")
    args = [
        "scp",
        "-o",
        f"ConnectTimeout={SSH_TIMEOUT}",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-P",
        str(SSH_PORT),
        f"{RUNTIME_SETTINGS.user}@{DEFAULT_HOST}:{remote_path}",
        str(local_path),
    ]
    completed = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(SSH_TIMEOUT, 120),
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"Failed to download {remote_path}")
    return local_path


COMPRESSED_FILE_SUFFIXES = {".gz", ".gzip"}


def is_gzip_file(path: Path) -> bool:
    return path.suffix.lower() in COMPRESSED_FILE_SUFFIXES


def decompress_file(path: Path) -> Path:
    if not is_gzip_file(path):
        return path
    output_path = path.with_suffix("")
    if output_path.is_file():
        return output_path
    try:
        with gzip.open(path, "rb") as source, output_path.open("wb") as destination:
            for line in source:
                destination.write(line)
    except (EOFError, gzip.BadGzipFile) as exc:
        if output_path.is_file() and output_path.stat().st_size > 0:
            return output_path
        output_path.unlink(missing_ok=True)
        raise ValueError(
            f"Compressed file is incomplete or corrupted: {path.name}. "
            "Download/copy the gzip file again and retry."
        ) from exc
    return output_path


def extract_gzip_files_in_folder(
    folder: Path,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> list[Path]:
    if not folder.is_dir():
        raise ValueError(f"Local source folder was not found: {folder}")
    gzip_paths = sorted(
        path
        for path in folder.iterdir()
        if path.is_file() and is_gzip_file(path)
    )
    extracted: list[Path] = []
    total = len(gzip_paths)
    for index, path in enumerate(gzip_paths, start=1):
        if progress_callback:
            progress_callback(index - 1, total, f"Extracting: {path.name}")
        extracted.append(decompress_file(path))
        if progress_callback:
            progress_callback(index, total, f"Extracted: {path.name}")
    return extracted


def cache_local_file(source_path: Path, local_dir: Path) -> Path:
    local_dir.mkdir(parents=True, exist_ok=True)
    local_path = local_dir / source_path.name
    if local_path.resolve() == source_path.resolve():
        return local_path
    if local_path.is_file():
        return local_path
    shutil.copy2(source_path, local_path)
    return local_path


def any_path_name(path: str | Path) -> str:
    return str(path).replace("\\", "/").rsplit("/", 1)[-1]


def source_file_key(path: Path) -> str:
    return path.with_suffix("").name if is_gzip_file(path) else path.name


def unique_source_files(paths: list[Path]) -> list[Path]:
    selected: dict[str, Path] = {}
    for path in sorted(paths, key=lambda item: item.name):
        key = source_file_key(path)
        current = selected.get(key)
        if current is None or is_gzip_file(current):
            selected[key] = path
    return sorted(selected.values(), key=lambda item: item.name)


def audit_code_family_pattern(audit_code: str) -> re.Pattern[str]:
    match = re.match(r"^(?P<prefix>.*?)(?P<number>\d{2})$", audit_code)
    if not match:
        return re.compile(rf"^{re.escape(audit_code)}$")
    return re.compile(rf"^{re.escape(match.group('prefix'))}\d{{2}}$")


def bank_audit_codes(bank: str) -> set[str]:
    return {BANK_AUDIT_CODES[bank]}


def bank_audit_code_matches(bank: str, audit_code: str) -> bool:
    return bool(audit_code_family_pattern(BANK_AUDIT_CODES[bank]).match(audit_code))


def parse_log_date(name: str) -> str | None:
    if name == "tango.log":
        return datetime.now().strftime("%Y-%m-%d")
    match = re.match(
        r"^tango\.log\.(?P<date>\d{4}-\d{2}-\d{2})(?:$|[ ._-])",
        name,
    )
    if match:
        date_part = match.group("date")
        try:
            datetime.strptime(date_part, "%Y-%m-%d")
            return date_part
        except ValueError:
            pass
    return None


def list_local_logs(folder: Path) -> list[str]:
    if not folder.is_dir():
        raise ValueError(f"Local source folder was not found: {folder}")
    paths = [
        path
        for path in folder.iterdir()
        if path.is_file() and parse_log_date(path.name)
    ]
    return [str(path) for path in unique_source_files(paths)]


def available_banks_for_folder(folder: Path) -> list[str]:
    if not folder.is_dir():
        return []
    banks: list[str] = []
    for path in folder.iterdir():
        if not path.is_file():
            continue
        name = source_file_key(path)
        if not name.startswith("audit."):
            continue
        parts = name.split(".")
        if len(parts) < 3:
            continue
        audit_code = parts[1]
        if not audit_code.startswith("OPN"):
            continue
        banks.extend(
            bank
            for bank in BANK_AUDIT_CODES
            if bank_audit_code_matches(bank, audit_code)
        )
    return [bank for bank in BANK_AUDIT_CODES if bank in set(banks)]


def validate_local_log_folder(folder: Path) -> None:
    if not folder.is_dir():
        raise ValueError(f"Local source folder was not found: {folder}")
    files = [source_file_key(path) for path in folder.iterdir() if path.is_file()]
    log_dates = sorted({date for name in files if (date := parse_log_date(name))})
    selected_date = log_dates[0] if len(log_dates) == 1 else None
    has_tango = bool(log_dates)
    if selected_date:
        compact_date = selected_date.replace("-", "")
        has_ptms = any(
            name.startswith("audit.PTMS")
            and (selected_date in name or compact_date in name)
            for name in files
        )
        has_opn = any(
            name.startswith("audit.OPN")
            and (selected_date in name or compact_date in name)
            for name in files
        )
    else:
        has_ptms = any(name.startswith("audit.PTMS") for name in files)
        has_opn = any(name.startswith("audit.OPN") for name in files)
    if has_tango and has_ptms and has_opn:
        return

    date_pattern = selected_date or "<YYYY-MM-DD>"
    missing: list[str] = []
    if not has_tango:
        missing.append("Daily Tango log: tango.log.<YYYY-MM-DD>")
    if not has_ptms:
        missing.append(f"PTMS audit: audit.PTMS*.*{date_pattern}*")
    if not has_opn:
        missing.append(f"OPN audit: audit.OPN*.*{date_pattern}* (at least one)")
    date_context = f" for {selected_date}" if selected_date else ""
    raise ValueError(
        f"Missing required source file(s){date_context}:\n"
        + "\n".join(f"- {item}" for item in missing)
        + "\nAccepted formats: uncompressed, .gz, or .gzip."
    )


def path_matches_audit(path: Path, selected_date: str, audit_code: str) -> bool:
    name = path.name
    compact_date = selected_date.replace("-", "")
    return (
        name.startswith(f"audit.{audit_code}.")
        and (selected_date in name or compact_date in name)
    )


def path_matches_ptms_audit(path: Path, selected_date: str) -> bool:
    name = source_file_key(path)
    compact_date = selected_date.replace("-", "")
    return name.startswith("audit.PTMS") and (
        selected_date in name or compact_date in name
    )


def list_local_audits(folder: Path, selected_date: str, bank: str) -> list[Path]:
    compact_date = selected_date.replace("-", "")
    paths = [
        path
        for path in folder.iterdir()
        if path.is_file()
        and (
            path_matches_ptms_audit(path, selected_date)
            or (
                (selected_date in path.name or compact_date in path.name)
                and path.name.startswith("audit.")
                and len(source_file_key(path).split(".")) >= 3
                and bank_audit_code_matches(bank, source_file_key(path).split(".")[1])
            )
        )
    ]
    return unique_source_files(paths)



