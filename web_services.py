"""Web adapters over the existing parser/exporter; no Tkinter or NiceGUI needed."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock
import queue
import threading

import log_core as core
from diagnostic_common import problem_display_text, problem_row_tag
from tango_checks import scan_tango_diagnostics
from transaction_checks import build_problem_columns, is_successful_protocol_only, successful_local_reversal_uids

# The original parser has process-wide caches. Serialize access across browser tabs.
CORE_LOCK = RLock()
BACKGROUND_LOCKS = {}


class BackgroundAudits:
    """Download other banks with atomic publication, without holding parser locks."""
    def __init__(self, selected_date: str, folder: Path):
        self.cancel_event = threading.Event()
        self.done = threading.Event()
        self.messages = queue.Queue()
        self.error = None
        self.folder = folder.resolve()
        self.selected_date = selected_date
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        from gui_services import download_remaining_uat_audits
        lock = BACKGROUND_LOCKS.setdefault(self.folder, threading.Lock())
        acquired = False
        try:
            while not self.cancel_event.is_set():
                acquired = lock.acquire(timeout=0.2)
                if acquired:
                    break
            if not acquired or self.cancel_event.is_set():
                return
            ready = {path.name for path in self.folder.iterdir() if path.is_file()}
            download_remaining_uat_audits(self.selected_date, self.folder, ready,
                                        progress_callback=self.messages.put, cancel_event=self.cancel_event)
            if not self.cancel_event.is_set():
                self.messages.put('Background audits ready for all banks')
        except Exception as error:
            self.error = str(error)
            self.messages.put(f'Background download failed: {error}')
        finally:
            if acquired:
                lock.release()
            self.done.set()

COLUMNS = [
    ('datetime', 'Date/Time'), ('transuid', 'TransUID'), ('stan', 'STAN'),
    ('rrn', 'RRN'), ('authcode', 'AuthCode'), ('sequencenumber', 'Sequence_Number'),
    ('transactiontype', 'TransactionType'), ('tid', 'TID'), ('mid', 'MID'),
    ('amt', 'AMT'), ('responsecodespdh', 'RC_SPDH'), ('responsecodeiso', 'RC_ISO'),
    ('possibleproblem', 'Possible problem'),
]


@dataclass
class LoadedLogs:
    folder: Path
    bank: str
    selected_date: str
    audits: list[Path]
    tango_logs: list[Path]
    rows: list[dict]


def load_logs(folder: Path, bank: str, selected_date: str = '', progress=None) -> LoadedLogs:
    folder = folder.expanduser().resolve()
    if not folder.is_dir():
        raise ValueError('Select an existing log folder on this computer.')
    if bank not in core.BANK_AUDIT_CODES:
        raise ValueError('Select a bank/acquirer.')
    with CORE_LOCK:
        if progress:
            progress(0, 1, 'Extracting source files')
        core.extract_gzip_files_in_folder(folder)
        logs = [Path(path) for path in core.list_local_logs(folder)]
        dates = sorted({date for path in logs if (date := core.parse_log_date(path.name))})
        if not selected_date:
            if len(dates) != 1:
                raise ValueError('Choose a date: the folder must contain one log date or an explicit date must be supplied.')
            selected_date = dates[0]
        datetime.strptime(selected_date, '%Y-%m-%d')
        logs = [path for path in logs if core.parse_log_date(path.name) == selected_date]
        audits = core.list_local_audits(folder, selected_date, bank)
        if not audits:
            raise ValueError(f'No audit files found for {bank} on {selected_date}.')
        transactions = core.scan_transactions_for_list(audits, progress)
        problems = build_problem_columns(transactions.values(), scan_tango_diagnostics(logs, set(transactions)))
        local_reversals = successful_local_reversal_uids(transactions.values())
        rows = []
        for transaction in sorted(transactions.values(), key=lambda t: t.first_index):
            if not core.transaction_matches_bank(transaction, bank):
                continue
            uid = transaction.trans_uid
            timestamp = transaction.request_timestamp or transaction.first_timestamp
            raw_problem = '; '.join(dict.fromkeys(part for column in problems[uid] for part in column.split('; ') if part))
            spdh = core.response_code_component(core.select_response_code(transaction.spdh_response_codes), core.SPDH_RC_NAMES)
            iso = core.response_code_component(core.select_response_code(transaction.iso_response_codes), core.ISO_RC_NAMES)
            rrn = core.select_rrn(transaction)
            rows.append(dict(
                datetime=timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3] if timestamp else '',
                transuid=uid, stan=core.select_identifier(transaction, 'stan'),
                rrn='' if rrn == 'NO_RRN' else rrn,
                authcode=core.select_identifier(transaction, 'authcode'),
                sequencenumber=core.select_identifier(transaction, 'sequence_number'),
                transactiontype=core.select_transaction_type(transaction),
                tid=core.select_first(transaction.tids), mid=core.select_first(transaction.mids),
                amt=core.select_amount_display(transaction), responsecodespdh=spdh, responsecodeiso=iso,
                possibleproblem=problem_display_text(raw_problem),
                severity=problem_row_tag(raw_problem, spdh, iso, protocol_only_success=(
                    is_successful_protocol_only(transaction) or uid in local_reversals)),
            ))
        return LoadedLogs(folder, bank, selected_date, audits, logs, rows)


def filter_rows(rows: list[dict], filters: dict[str, str], minimum: str = '', maximum: str = '', offset: int = 0) -> list[dict]:
    result = []
    for row in rows:
        if any(str(value).strip().casefold() not in str(row.get(key, '')).casefold()
               for key, value in filters.items() if value):
            continue
        displayed = dict(row)
        if row['datetime']:
            timestamp = datetime.strptime(row['datetime'], '%Y-%m-%d %H:%M:%S.%f') + timedelta(hours=offset)
            displayed['datetime'] = timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            # Compare at second resolution, so the entire final second is included.
            value = displayed['datetime'][:19]
            if minimum and value < minimum or maximum and value > maximum:
                continue
        result.append(displayed)
    return result


def export_logs(loaded: LoadedLogs, uids: list[str], output: Path, **options) -> list[Path]:
    if not uids:
        raise ValueError('No transactions selected or visible.')
    allowed = {row['transuid'] for row in loaded.rows}
    if not set(uids) <= allowed:
        raise ValueError('The selection does not belong to the loaded source.')
    output.mkdir(parents=True, exist_ok=True)
    with CORE_LOCK:
        core.split_audit_files(loaded.audits, output, bank=loaded.bank,
                              transaction_uids=set(uids),
                              tango_log_path=loaded.tango_logs[0] if loaded.tango_logs else None,
                              **options)
    paths = [output / f'{core.safe_component(uid)}.log' for uid in dict.fromkeys(uids)]
    if any(not path.is_file() for path in paths):
        raise ValueError('Some selected transactions could not be exported with these options.')
    return paths
