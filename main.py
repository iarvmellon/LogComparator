from __future__ import annotations

import argparse
import gzip
import os
import re
import shutil
import signal
import subprocess
import sys
import tkinter as tk
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Iterator, TextIO

from tkcalendar import Calendar


DEFAULT_INPUT = Path(
    r"C:\Users\j.arvanitis\Desktop\Tango\Logs\audit.OPNBISOBKT01.2026-03-06"
)
DEFAULT_OUTPUT = Path(r"C:\Users\j.arvanitis\Desktop\Tango\Logs\LogComparator")
DEFAULT_HOST = "10.1.110.84"
DEFAULT_USER = "j.arvanitis"
DEFAULT_SUDO_PASSWORD = "12345ja!@#$%"
REMOTE_LOG_DIR = "/opt/tango/MLNPSP01/log"
REMOTE_AUDIT_DIR = "/opt/tango/MLNPSP01/audit"
SSH_PORT = 22
SSH_TIMEOUT = 10
SEPARATOR_PREFIX = "=" * 40
CORRELATION_WINDOW_SECONDS = 5 * 60

BANK_AUDIT_CODES = {
    "CASYS/STOPANSKA": "OPNBISOCAS01",
    "CASYS/FIBANK": "OPNBISOCAS01",
    "CASYS/RUBICON": "OPNBISOCAS01",
    "AKTIF/BKT": "OPNBISOBKT01",
    "EURONET/OTP": "OPNRENOTP01",
    "NEXI/ALPHA": "OPNBISOA01",
    "BORICA/PROCREDIT": "OPNWAY4B01",
    "NBG": "OPNWAY4N01",
    "EUROBANK": "OPNBISOE01",
    "COSMOTE/NEXI": "OPNBISOC01",
}
BANK_ACQUIRER_IDS = {
    "CASYS/STOPANSKA": {"021", "031"},
    "CASYS/FIBANK": {"054"},
    "CASYS/RUBICON": {"056"},
    "AKTIF/BKT": {"050", "065", "978", "003723"},
    "EURONET/OTP": {"063", "99999008036"},
    "NEXI/ALPHA": {"075"},
    "BORICA/PROCREDIT": {"077", "078", "2081", "301000", "808018"},
    "NBG": {"011"},
    "EUROBANK": {"006"},
    "COSMOTE/NEXI": {"061"},
}

MTI_NAMES = {
    "0100": "Authorization_Request",
    "0110": "Authorization_Response",
    "0120": "Authorization_Advice",
    "0121": "Authorization_Advice_Repeat",
    "0130": "Authorization_Advice_Response",
    "0140": "Authorization_Notification",
    "0141": "Authorization_Notification_Ackn",
    "0200": "Financial_Request",
    "0210": "Financial_Response",
    "0220": "Financial_Advice",
    "0221": "Financial_Advice_Repeat",
    "0230": "Financial_Advice_Response",
    "0240": "Financial_Notification",
    "0241": "Financial_Notification_Ackn",
    "0400": "Reversal_Request",
    "0410": "Reversal_Response",
    "0420": "Reversal_Advice",
    "0421": "Reversal_Advice_Repeat",
    "0430": "Reversal_Advice_Response",
    "0440": "Reversal_Notification",
    "0441": "Reversal_Notification_Ackn",
    "0500": "Batch_Upload_File_Action_Request",
    "0510": "Batch_Upload_File_Action_Response",
    "0520": "Batch_Advice",
    "0521": "Batch_Advice_Repeat",
    "0530": "Batch_Advice_Response",
    "0540": "File_Update_Notification",
    "0541": "File_Update_Notification_Ack",
    "0560": "Settlement_Request",
    "0570": "Settlement_Response",
    "0800": "Network_Management_Request_(Echo_Sign-on_Sign-off_Key_Exchange)",
    "0810": "Network_Management_Response",
    "0820": "Network_Management_Advice",
    "0830": "Network_Management_Advice_Response",
    "0840": "Cutover_Notification",
    "0850": "Key_Exchange_Request",
    "0851": "Key_Exchange_Response",
    "0860": "Echo_Test_Request",
    "0861": "Echo_Test_Response",
    "0870": "Sign-on_Request",
    "0871": "Sign-on_Response",
    "0880": "Sign-off_Request",
    "0881": "Sign-off_Response",
    "0900": "Administrative_Request_(Parameter_Download_Key_Management)",
    "0910": "Administrative_Response",
    "0920": "Administrative_Advice",
    "0930": "Administrative_Advice_Response",
    "0940": "Key_Change_Notification",
    "0950": "Security_Module_Synchronization",
    "0960": "Network_Time_Sync_Parameter_Distribution",
    "1000": "File_Action_Request",
    "1010": "File_Action_Response",
    "1020": "File_Upload_Request",
    "1030": "File_Upload_Response",
    "1100": "Parameter_Download_Request",
    "1110": "Parameter_Download_Response",
    "6000": "Terminal_Initialization_Proprietary_Setup",
    "6100": "Host_Diagnostic_Proprietary_Status",
    "6200": "Software_Update_Custom_Operation",
    "9999": "Undefined_Reserved_Proprietary_MTI",
    "7080": "Echo_Test_Request",
    "9081": "Echo_Test_Response",
    "6001": "Generate_Key",
    "4842": "Call_Data_Logger",
    "6034": "Verify_MAC_Msg_From_PoS",
    "4530": "Financial_Processing",
    "6022": "Generate_MAC_To_POS",
}

TANGO_TRANSACTION_MTI_NAMES = {
    "4013": "Pre-auth_Request",
    "8707": "Pre-auth_Request_Reversal",
    "4530": "Purchase",
    "4546": "Purchase_Reversal",
    "4531": "Cash_Advance",
    "4547": "Cash_Advance_Reversal",
    "4533": "Purchase_with_Cashback",
    "4549": "Purchase_with_Cashback_Reversal",
    "4534": "Refund",
    "5251": "Refund_Reversal",
    "4538": "Financial_Purchase_Advice",
    "4558": "Financial_Purchase_Advice_Reversal",
    "4554": "Purchase_Void",
    "4581": "Purchase_Void_Reversal",
    "4555": "Refund_Void",
    "4582": "Refund_Void_Reversal",
    "4557": "Purchase_with_Cashback_Void",
    "4583": "Purchase_with_Cashback_Void_Reversal",
    "4559": "Cash_Advance_Void",
    "4584": "Cash_Advance_Void_Reversal",
    "5109": "Debit_Adjustment",
    "5259": "Debit_Adjustment_Reversal",
    "5110": "Credit_Adjustment",
    "5260": "Credit_Adjustment_Reversal",
    "8706": "Pre-auth_Completion",
    "8705": "Pre-auth_Completion_Reversal",
    "8760": "Pre-auth_Void",
    "8763": "Pre-auth_Void_Reversal",
}

ISO_RC_NAMES = {
    "00": "Approved",
    "01": "Refer_to_card_issuer",
    "03": "Invalid_merchant",
    "04": "Pick_up_card",
    "05": "Do_not_honor",
    "12": "Invalid_transaction",
    "13": "Invalid_amount",
    "14": "Invalid_card_number",
    "30": "Format_error",
    "41": "Lost_card",
    "43": "Stolen_card",
    "51": "Insufficient_funds",
    "54": "Expired_card",
    "55": "Incorrect_PIN",
    "56": "No_card_record",
    "57": "Transaction_not_permitted_to_cardholder",
    "58": "Transaction_not_permitted_to_terminal",
    "61": "Exceeds_withdrawal_limit",
    "62": "Restricted_card",
    "65": "Exceeds_withdrawal_frequency",
    "68": "Response_received_too_late",
    "75": "PIN_tries_exceeded",
    "78": "No_account",
    "86": "PIN_validation_not_possible",
    "91": "Issuer_or_switch_unavailable",
    "94": "Duplicate_transmission",
    "96": "System_malfunction",
}

SPDH_RC_NAMES = {
    "000": "Approved",
    "050": "General",
    "051": "Expired card",
    "052": "Number of PIN tries exceeded",
    "053": "No sharing allowed",
    "054": "No security module",
    "055": "Invalid transaction",
    "056": "Transaction not supported by institution",
    "057": "Lost or stolen card",
    "059": "Invalid card status",
    "060": "Account not found in cardholder database",
    "061": "Positive balance account record not found",
    "062": "Positive balance account update error",
    "063": "Invalid authorization type in institution database",
    "064": "Bad track information",
    "065": "Adjustment not allowed in institution database",
    "066": "Invalid credit/cash advance increment",
    "067": "Invalid transaction date",
    "068": "Transaction log file error",
    "069": "Bad message edit",
    "070": "No institution database record",
    "071": "Invalid routing to host application",
    "072": "Card or national negative file",
    "073": "Invalid host authorization service",
    "074": "Unable to authorize",
    "075": "Invalid PAN length",
    "076": "Insufficient funds in positive balance account",
    "077": "Pre-authorization full",
    "078": "Duplicate transaction received",
    "079": "Maximum online refund reached",
    "080": "Maximum offline refund reached",
    "081": "Maximum credit per refund reached",
    "082": "Maximum number of times used",
    "083": "Maximum credit reached",
    "084": "Customer selected negative card file reason",
    "085": "History not allowed - no balances",
    "086": "Over floor limit",
    "087": "Maximum number refund credits reached",
    "088": "Place call",
    "089": "Card status equals 0 (inactive) or 9 (closed)",
    "090": "Referral file full",
    "091": "Problem accessing negative card file",
    "092": "Absence less than minimum",
    "093": "Delinquent",
    "094": "Over limit table or exceeds annual amount",
    "095": "Amount over maximum",
    "096": "Strong customer authentication (SCA) required",
    "097": "Mod 10 check",
    "098": "Force post",
    "099": "Could not access positive balance account in database",
    "100": "Unable to process transaction",
    "101": "Unable to authorize - issue call",
    "102": "Call",
    "103": "Problem accessing negative card file",
    "104": "Problem accessing cardholder account",
    "105": "Card not supported",
    "106": "Amount over maximum",
    "107": "Over daily limit",
    "108": "Card authorization parameters not found",
    "109": "Audience less than minimum",
    "110": "Number times used",
    "111": "Delinquent",
    "112": "Over limit table",
    "113": "Timeout",
    "114": "Transaction log file full",
    "120": "Problem accessing cardholder usage accumulation data",
    "121": "Problem accessing administrative card data",
    "122": "Unable to validate PIN/security module is bad",
    "130": "Cryptogram verification failure referral",
    "131": "Card verification results (CVR) referral",
    "132": "Terminal verification results (TVR) referral",
    "133": "Reason online code referral",
    "134": "Fallback referral",
    "200": "Invalid account",
    "201": "Incorrect PIN",
    "202": "Cash advance less than minimum",
    "203": "Administrative card needed",
    "204": "Enter lesser amount",
    "205": "Invalid advance amount",
    "206": "Invalid expiration date",
    "251": "Cash-back limit exceeded",
    "400": "Cryptogram verification failure decline",
    "401": "Hardware security module parameter error",
    "402": "Hardware security module failure",
    "403": "Impacted circuit card key information not found",
    "404": "Issuer application counter (IATC) check failure",
    "405": "Card verification results (CVR) decline",
    "406": "Terminal verification results (TVR) decline",
    "407": "Reason online code decline",
    "408": "Fallback decline",
    "500": "Administrative card not allowed",
    "501": "Administrative transactions not supported",
    "800": "Host not responding / Timeout",
    "811": "Duplicate transaction",
    "878": "Incorrect PIN length error",
    "888": "MAC communications key (KM/AC) synchronization error",
    "889": "Invalid MAC",
    "899": "Sequence error resync",
    "900": "Number of PIN tries exceeded",
    "901": "Expired card",
    "902": "Negative card file capture code",
    "903": "Card status is 3 (stolen)",
    "904": "Hardware security module unavailable",
    "905": "Number times used exceeded",
    "906": "Delinquent",
    "907": "Over limit table",
    "908": "Amount over maximum",
    "909": "Capture",
    "910": "Cryptogram verification failure capture",
    "911": "Card verification results (CVR) capture",
    "912": "Terminal verification results (TVR) capture",
    "950": "Administrative card not allowed",
    "951": "Administrative transactions not supported",
    "952": "Administrative request out of window",
    "953": "Approved admin request anytime",
    "954": "Advance less than minimum",
    "955": "Chargeback - customer file updated",
    "956": "Chargeback - customer file not updated, acquirer not found",
    "957": "Chargeback - incorrect print receipt",
    "958": "Chargeback - incorrect response code or card prefix configuration",
    "960": "Chargeback - approved customer file not updated",
    "961": "Chargeback - approved customer file not updated, acquirer not found",
    "962": "Chargeback - accepted incorrect presentation",
}

FIELD_RE = re.compile(
    r"<field\b[^>]*\bname=['\"](?P<name>[^'\"]+)['\"][^>]*>(?P<value>.*?)</field>",
    re.IGNORECASE,
)
AUDIT_VALUE_RE = re.compile(
    r"^\s*(?:\d+\.\s+)?(?P<name>[A-Za-z_][\w-]*)\s*:\s*"
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
SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._()\\-]+")
SECTION_SEPARATOR = "#" * 79


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


def select_response_code(values: list[str]) -> str:
    return next((value for value in values if value), "NA")


def response_code_component(code: str, names: dict[str, str]) -> str:
    if code == "NA":
        return "Not_available(NA)"
    return f"{names.get(code, 'Unknown_response_code')}({code})"


def safe_component(value: str) -> str:
    cleaned = SAFE_FILENAME_RE.sub("_", value.strip()).strip("._")
    return cleaned or "UNKNOWN"


def build_filenames(transactions: dict[str, Transaction]) -> dict[str, str]:
    filenames: dict[str, str] = {}
    used: dict[str, str] = {}
    for uid, transaction in sorted(transactions.items(), key=lambda item: item[1].first_index):
        request_time = transaction.request_timestamp or transaction.first_timestamp
        date_part = (
            request_time.strftime("%Y%m%d_%H%M%S")
            if request_time
            else "UNKNOWN_DATETIME"
        )
        mti = select_iso_mti(transaction)
        rrn = select_rrn(transaction)
        mti_name = TANGO_TRANSACTION_MTI_NAMES.get(
            mti,
            MTI_NAMES.get(mti, "Unknown_MTI"),
        )
        iso_rc = select_response_code(transaction.iso_response_codes)
        spdh_rc = select_response_code(transaction.spdh_response_codes)
        parts = (
            date_part,
            uid,
            rrn,
            mti_name,
            response_code_component(iso_rc, ISO_RC_NAMES),
            response_code_component(spdh_rc, SPDH_RC_NAMES),
        )
        filename = "_".join(safe_component(part) for part in parts) + ".log"

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


def iter_input_blocks(input_paths: list[Path]) -> Iterator[tuple[int, str]]:
    index = 0
    for input_path in input_paths:
        with input_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            for text in iter_blocks(handle):
                yield index, text
                index += 1


def scan_transactions(input_paths: list[Path]) -> tuple[dict[str, Transaction], dict[int, str]]:
    transactions: dict[str, Transaction] = {}
    missing_blocks: list[BlockMeta] = []

    for index, text in iter_input_blocks(input_paths):
        block = parse_block(text, index)
        if block.trans_uid:
            transaction = transactions.setdefault(
                block.trans_uid,
                Transaction(trans_uid=block.trans_uid, first_index=index),
            )
            transaction.add(block)
        else:
            missing_blocks.append(block)

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


def collect_tango_lines(
    tango_log_path: Path | None,
    transaction_uids: set[str],
) -> dict[str, list[str]]:
    lines_by_uid: dict[str, list[str]] = defaultdict(list)
    if not tango_log_path or not tango_log_path.is_file() or not transaction_uids:
        return lines_by_uid

    alternatives = "|".join(
        re.escape(uid) for uid in sorted(transaction_uids, key=len, reverse=True)
    )
    uid_pattern = re.compile(
        rf"(?<![A-Za-z0-9])(?:{alternatives})(?![A-Za-z0-9])"
    )
    with tango_log_path.open(
        "r",
        encoding="utf-8",
        errors="replace",
        newline="",
    ) as tango_log:
        for line in tango_log:
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
    terminal = tango_field(tango_lines, "trmId") or "Not available"
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
        return f"{label:<15} : {value}"

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
            field_line("Terminal", terminal),
            field_line("Acquirer", acquirer),
            field_line("MTI", mti),
            "",
            field_line("Result Code", result_code),
            field_line("Response Code", spdh_rc),
            field_line("Network RC", network_rc),
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
    correlated: dict[int, str],
    excluded_uids: set[str] | None = None,
    include_unassigned: bool = True,
    cleanup_excluded: bool = True,
    tango_lines_by_uid: dict[str, list[str]] | None = None,
    transaction_headers_by_uid: dict[str, str] | None = None,
) -> tuple[int, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_paths = {output_dir / filename for filename in filenames.values()}
    summary_paths_by_uid = {
        uid: output_dir / f"{Path(filename).stem}_summary.log"
        for uid, filename in filenames.items()
    }
    generated_paths.update(summary_paths_by_uid.values())
    if include_unassigned:
        generated_paths.add(output_dir / "NO_TRANSUID.log")
    if cleanup_excluded:
        for uid in excluded_uids or set():
            for old_path in output_dir.glob(f"*_{safe_component(uid)}_*.log"):
                old_path.unlink(missing_ok=True)
    for uid, filename in filenames.items():
        current_path = output_dir / filename
        current_paths = {current_path, summary_paths_by_uid[uid]}
        for old_path in output_dir.glob(f"*_{safe_component(uid)}_*.log"):
            if old_path not in current_paths:
                old_path.unlink(missing_ok=True)
    for path in generated_paths:
        path.unlink(missing_ok=True)

    transaction_blocks = 0
    no_transuid_blocks = 0
    blocks_by_path: dict[Path, list[tuple[datetime, int, str]]] = defaultdict(list)
    summary_blocks_by_path: dict[Path, list[tuple[datetime, int, str]]] = {
        path: [] for path in summary_paths_by_uid.values()
    }
    flow_diagram_nodes: dict[
        str,
        list[tuple[datetime, int, str]],
    ] = defaultdict(list)
    uid_by_path: dict[Path, str] = {}
    for uid, summary_path in summary_paths_by_uid.items():
        uid_by_path[summary_path] = uid
    for index, text in iter_input_blocks(input_paths):
        block = parse_block(text, index)
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
        blocks_by_path[target].append((sort_time, index, text))
        if uid and uid in summary_paths_by_uid:
            normalized_flow = block.flow_dir.upper().replace(" ", "")
            process_name = block.process_name.upper()
            is_network_direction = normalized_flow in {
                "TANGO-->NETWORK",
                "NETWORK-->TANGO",
            }
            is_network_process = process_name.startswith(("PTMS", "OPN"))
            if is_network_direction and is_network_process:
                summary_blocks_by_path[summary_paths_by_uid[uid]].append(
                    (sort_time, index, without_bus_data(text))
                )
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
    for target, blocks in summary_blocks_by_path.items():
        uid = uid_by_path[target]
        write_file(
            target,
            blocks,
            (transaction_headers_by_uid or {}).get(uid, ""),
            format_flow_diagram(flow_diagram_nodes.get(uid, [])),
        )
    return transaction_blocks, no_transuid_blocks


def split_audit_files(
    input_paths: list[Path],
    output_dir: Path,
    bank: str | None = None,
    transaction_uid: str | None = None,
    tango_log_path: Path | None = None,
) -> dict[str, int]:
    if not input_paths:
        raise ValueError("No audit files were supplied for analysis.")
    transactions, correlated = scan_transactions(input_paths)
    excluded_uids: set[str] = set()
    if bank:
        expected_ids = BANK_ACQUIRER_IDS.get(bank, set())
        expected_process = BANK_AUDIT_CODES.get(bank)
        matching = {
            uid: transaction
            for uid, transaction in transactions.items()
            if (
                transaction.acquirer_ids & expected_ids
                or (
                    expected_process is not None
                    and expected_process in transaction.process_names
                )
            )
        }
        excluded_uids = set(transactions) - set(matching)
        transactions = matching
    transaction_uid = (transaction_uid or "").strip()
    if transaction_uid:
        targeted = {
            uid: transaction
            for uid, transaction in transactions.items()
            if uid == transaction_uid
        }
        excluded_uids.update(set(transactions) - set(targeted))
        transactions = targeted
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
        correlated,
        excluded_uids,
        include_unassigned=not transaction_uid,
        cleanup_excluded=not transaction_uid,
        tango_lines_by_uid=tango_lines_by_uid,
        transaction_headers_by_uid=transaction_headers_by_uid,
    )
    return {
        "transactions": len(transactions),
        "transaction_blocks": transaction_blocks,
        "correlated_blocks": len(correlated),
        "no_transuid_blocks": no_transuid_blocks,
        "tango_lines": sum(len(lines) for lines in tango_lines_by_uid.values()),
        "summary_files": len(filenames),
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
        f"{DEFAULT_USER}@{DEFAULT_HOST}",
        remote_command,
    ]
    completed = subprocess.run(
        args,
        input=DEFAULT_SUDO_PASSWORD + "\n" if sudo else None,
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
        print(f"Using existing file: {local_path}")
        return local_path
    if shutil.which("scp") is None:
        raise RuntimeError("The 'scp' executable was not found on PATH.")
    print(f"Downloading: {remote_path}")
    args = [
        "scp",
        "-o",
        f"ConnectTimeout={SSH_TIMEOUT}",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-P",
        str(SSH_PORT),
        f"{DEFAULT_USER}@{DEFAULT_HOST}:{remote_path}",
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


def decompress_file(path: Path) -> Path:
    if path.suffix.lower() != ".gz":
        return path
    output_path = path.with_suffix("")
    if output_path.is_file():
        print(f"Using existing decompressed file: {output_path}")
        return output_path
    with gzip.open(path, "rb") as source, output_path.open("wb") as destination:
        shutil.copyfileobj(source, destination)
    return output_path


def parse_log_date(name: str) -> str | None:
    if name == "tango.log":
        return datetime.now().strftime("%Y-%m-%d")
    if name.startswith("tango.log."):
        date_part = name[len("tango.log.") :].split(".")[0]
        try:
            datetime.strptime(date_part, "%Y-%m-%d")
            return date_part
        except ValueError:
            return None
    return None


def choose_date_and_bank(paths: list[str]) -> tuple[str, str, str, str] | None:
    valid_dates: dict[str, str] = {}
    for path in paths:
        date_part = parse_log_date(path.rsplit("/", 1)[-1])
        if date_part:
            valid_dates[date_part] = path
    if not valid_dates:
        return None

    root = tk.Tk()
    root.title("Select date and bank")
    root.geometry("760x410")
    root.minsize(700, 390)

    default_date = sorted(valid_dates)[0]
    initial = datetime.strptime(default_date, "%Y-%m-%d")
    tk.Label(root, text="Select a date:").pack(pady=(10, 5))
    calendar = Calendar(
        root,
        selectmode="day",
        year=initial.year,
        month=initial.month,
        day=initial.day,
    )
    valid_date_objects: dict[object, str] = {}
    for date_value, path in valid_dates.items():
        event_date = datetime.strptime(date_value, "%Y-%m-%d").date()
        valid_date_objects[event_date] = path
        calendar.calevent_create(event_date, "", tags=["valid"])
    calendar.tag_config("valid", background="#c8f7c5", foreground="black")
    calendar.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)

    selection: dict[str, str] = {}

    def close_window() -> None:
        root.quit()
        root.destroy()

    def report_callback_exception(exc_type, exc_value, traceback) -> None:
        if exc_type is KeyboardInterrupt:
            selection["interrupted"] = "1"
            close_window()
            return
        sys.__excepthook__(exc_type, exc_value, traceback)

    def poll_signals() -> None:
        root.after(100, poll_signals)

    root.report_callback_exception = report_callback_exception
    root.protocol("WM_DELETE_WINDOW", close_window)
    root.after(100, poll_signals)

    def selected_date():
        try:
            return datetime.strptime(calendar.get_date(), "%m/%d/%y").date()
        except (TypeError, ValueError):
            return None

    def validate_date(event=None):
        chosen = selected_date()
        if chosen not in valid_date_objects:
            calendar.selection_clear()
            messagebox.showwarning("Invalid date", "Please select a highlighted date.")

    calendar.bind("<<CalendarSelected>>", validate_date)

    bank_frame = tk.Frame(root)
    bank_frame.pack(padx=12, pady=(8, 4), fill=tk.X)
    tk.Label(bank_frame, text="Bank/Acquirer:").pack(side=tk.LEFT, padx=(0, 8))
    bank_var = tk.StringVar(root)
    bank_combo = ttk.Combobox(
        bank_frame,
        textvariable=bank_var,
        values=list(BANK_AUDIT_CODES),
        state="readonly",
        width=25,
    )
    bank_combo.pack(side=tk.LEFT)
    tk.Label(bank_frame, text="TransUID:").pack(side=tk.LEFT, padx=(14, 8))
    trans_uid_var = tk.StringVar(root)
    trans_uid_entry = tk.Entry(
        bank_frame,
        textvariable=trans_uid_var,
        width=28,
    )
    trans_uid_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def submit():
        chosen = selected_date()
        if chosen not in valid_date_objects:
            messagebox.showwarning("Invalid date", "Please select a highlighted date.")
            return
        bank = bank_var.get().strip()
        if not bank:
            messagebox.showwarning("Bank required", "Please select a bank/acquirer.")
            return
        selection["date"] = chosen.strftime("%Y-%m-%d")
        selection["bank"] = bank
        selection["path"] = valid_date_objects[chosen]
        selection["trans_uid"] = trans_uid_var.get().strip()
        close_window()

    tk.Button(root, text="Select", command=submit).pack(pady=(10, 12))
    root.mainloop()
    if selection.get("interrupted"):
        raise KeyboardInterrupt
    if not selection:
        return None
    return (
        selection["date"],
        selection["bank"],
        selection["path"],
        selection["trans_uid"],
    )


def list_remote_logs() -> list[str]:
    output = run_remote_command(
        f"find {REMOTE_LOG_DIR} -maxdepth 1 -name 'tango.log*' -print | sort",
        sudo=True,
    )
    return [line.strip() for line in output.splitlines() if line.strip()]


def list_remote_audits(selected_date: str, bank: str) -> list[str]:
    audit_code = BANK_AUDIT_CODES[bank]
    compact_date = selected_date.replace("-", "")
    command = (
        f"find {REMOTE_AUDIT_DIR} -maxdepth 1 -type f \\( "
        f"-name 'audit.PTMSPMLN01.*{selected_date}*' -o "
        f"-name 'audit.PTMSPMLN01.*{compact_date}*' -o "
        f"-name 'audit.{audit_code}.*{selected_date}*' -o "
        f"-name 'audit.{audit_code}.*{compact_date}*' \\) -print | sort"
    )
    output = run_remote_command(command, sudo=True)
    paths = [line.strip() for line in output.splitlines() if line.strip()]
    return list(dict.fromkeys(paths))


def bank_directory_name(bank: str) -> str:
    return safe_component(bank.replace("/", "_"))


def run_gui_workflow(base_output: Path = DEFAULT_OUTPUT) -> int:
    install_interrupt_handler()
    try:
        run_remote_command("whoami")
        run_remote_command("su -c 'whoami'", sudo=True)
        remote_logs = list_remote_logs()
        if not remote_logs:
            print("No matching Tango log files were found.")
            return 0

        selected = choose_date_and_bank(remote_logs)
        if selected is None:
            return 0
        selected_date, bank, remote_log, transaction_uid = selected

        bank_dir = base_output / bank_directory_name(bank)
        date_dir = bank_dir / selected_date
        source_dir = date_dir / "source"
        source_dir.mkdir(parents=True, exist_ok=True)

        local_tango_log = decompress_file(
            download_remote_file(remote_log, source_dir)
        )

        remote_audits = list_remote_audits(selected_date, bank)
        if not remote_audits:
            print(f"No audit files found for {bank} on {selected_date}.")
            return 0

        local_audits: list[Path] = []
        for remote_audit in remote_audits:
            local_audits.append(decompress_file(download_remote_file(remote_audit, source_dir)))

        stats = split_audit_files(
            local_audits,
            date_dir,
            bank=bank,
            transaction_uid=transaction_uid,
            tango_log_path=local_tango_log,
        )
        if transaction_uid and stats["transactions"] == 0:
            print(
                f"TransUID {transaction_uid} was not found for "
                f"{bank} on {selected_date}."
            )
            return 0
        summary = (
            f"Bank: {bank}\n"
            f"Date: {selected_date}\n"
            f"TransUID: {transaction_uid or 'ALL'}\n"
            f"Audit files: {len(local_audits)}\n"
            f"Transactions: {stats['transactions']}\n"
            f"Summary files: {stats['summary_files']}\n"
            f"Tango lines: {stats['tango_lines']}\n"
            f"Output: {date_dir}"
        )
        print(summary.replace("\n", " | "))
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        return 130
    except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError) as exc:
        print(f"LogComparator failed: {exc}")
        return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download and split TANGO audit logs into complete transaction flows."
    )
    parser.add_argument(
        "input",
        nargs="*",
        type=Path,
        help="Optional local audit files. Without inputs, the GUI downloader opens.",
    )
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--tango-log",
        type=Path,
        help="Optional local tango.log whose matching TransUID lines are prepended.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.output.expanduser().resolve()
    if not args.input:
        return run_gui_workflow(output_dir)

    input_paths = [path.expanduser().resolve() for path in args.input]
    missing = [path for path in input_paths if not path.is_file()]
    if missing:
        raise SystemExit(f"Input file not found: {missing[0]}")

    tango_log_path = (
        args.tango_log.expanduser().resolve()
        if args.tango_log
        else None
    )
    if tango_log_path is not None and not tango_log_path.is_file():
        raise SystemExit(f"Tango log file not found: {tango_log_path}")
    stats = split_audit_files(
        input_paths,
        output_dir,
        tango_log_path=tango_log_path,
    )
    print(f"Inputs: {len(input_paths)}")
    print(f"Output: {output_dir}")
    print(f"Transactions: {stats['transactions']}")
    print(f"Transaction blocks: {stats['transaction_blocks']}")
    print(f"Correlated blocks without transUId: {stats['correlated_blocks']}")
    print(f"NO_TRANSUID blocks: {stats['no_transuid_blocks']}")
    print(f"Tango lines prepended: {stats['tango_lines']}")
    print(f"Summary files: {stats['summary_files']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
