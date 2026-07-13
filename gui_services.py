from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
from pathlib import Path

from log_core import *


def list_remote_logs() -> list[str]:
    output = run_remote_command(
        f"find {REMOTE_LOG_DIR} -maxdepth 1 -name 'tango.log*' -print | sort",
        sudo=True,
    )
    return [line.strip() for line in output.splitlines() if line.strip()]


def list_remote_logs_for_date(selected_date: str) -> list[str]:
    compact_date = selected_date.replace("-", "")
    command = (
        f"find {REMOTE_LOG_DIR} -maxdepth 1 -type f \\( "
        f"-name 'tango.log*{selected_date}*' -o "
        f"-name 'tango.log*{compact_date}*' \\) -print | sort"
    )
    output = run_remote_command(command, sudo=True)
    return [line.strip() for line in output.splitlines() if line.strip()]


def list_remote_uat_sources(selected_date: str) -> list[str]:
    compact_date = selected_date.replace("-", "")
    log_paths = list_remote_logs_for_date(selected_date)
    command = (
        f"find {REMOTE_AUDIT_DIR} -maxdepth 1 -type f \\( "
        f"-name 'audit.PTMS*.*{selected_date}*' -o "
        f"-name 'audit.PTMS*.*{compact_date}*' -o "
        f"-name 'audit.OPN*.*{selected_date}*' -o "
        f"-name 'audit.OPN*.*{compact_date}*' \\) -print | sort"
    )
    output = run_remote_command(command, sudo=True)
    audit_paths = [line.strip() for line in output.splitlines() if line.strip()]
    return list(dict.fromkeys(log_paths + audit_paths))


def download_uat_sources(
    selected_date: str,
    output_root: Path,
    progress_callback=None,
) -> Path:
    target_dir = output_root / f"{selected_date}_UAT"
    target_dir.mkdir(parents=True, exist_ok=True)
    remote_paths = list_remote_uat_sources(selected_date)
    if not remote_paths:
        raise ValueError(f"No UAT source files were found for {selected_date}.")

    total_steps = len(remote_paths) * 2
    current_step = 0

    def report(message: str) -> None:
        if progress_callback:
            progress_callback(current_step, total_steps, message)

    downloaded: list[Path] = []
    for remote_path in remote_paths:
        report(f"Downloading: {Path(remote_path).name}")
        downloaded.append(download_remote_file(remote_path, target_dir))
        current_step += 1
        report(f"Downloading complete: {Path(remote_path).name}")

    extracted: list[Path] = []
    for path in downloaded:
        report(f"Extracting: {path.name}")
        extracted.append(decompress_file(path))
        current_step += 1
        report(f"Extracting complete: {path.name}")
    has_tango = any(path.name.startswith("tango.log") for path in extracted)
    has_ptms = any(path.name.startswith("audit.PTMS") for path in extracted)
    has_opn = any(path.name.startswith("audit.OPN") for path in extracted)
    missing = []
    if not has_tango:
        missing.append("tango.log*")
    if not has_ptms:
        missing.append("audit.PTMS*")
    if not has_opn:
        missing.append("audit.OPN*")
    if missing:
        raise ValueError(
            f"Missing UAT source file(s) for {selected_date}: {', '.join(missing)}"
        )
    return target_dir


def list_remote_audits(selected_date: str, bank: str) -> list[str]:
    audit_code = BANK_AUDIT_CODES[bank]
    audit_family = audit_code[:-2] + "??" if audit_code[-2:].isdigit() else audit_code
    compact_date = selected_date.replace("-", "")
    audit_patterns = [
        f"-name 'audit.{audit_family}.*{selected_date}*'",
        f"-name 'audit.{audit_family}.*{compact_date}*'",
    ]
    command = (
        f"find {REMOTE_AUDIT_DIR} -maxdepth 1 -type f \\( "
        f"-name 'audit.PTMS*.*{selected_date}*' -o "
        f"-name 'audit.PTMS*.*{compact_date}*' -o "
        f"{' -o '.join(audit_patterns)} \\) -print | sort"
    )
    output = run_remote_command(command, sudo=True)
    paths = [line.strip() for line in output.splitlines() if line.strip()]
    return list(dict.fromkeys(paths))


def bank_directory_name(bank: str) -> str:
    return safe_component(bank.replace("/", "_"))


def find_first_executable(candidates: list[str]) -> str | None:
    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return found
        path = Path(candidate)
        if path.is_file():
            return str(path)
    return None


def find_notepad_plus_plus() -> str | None:
    return find_first_executable(
        [
            "notepad++",
            "notepad++.exe",
            r"C:\Program Files\Notepad++\notepad++.exe",
            r"C:\Program Files (x86)\Notepad++\notepad++.exe",
        ]
    )


def find_winmerge() -> str | None:
    return find_first_executable(
        [
            "WinMergeU",
            "WinMergeU.exe",
            r"C:\Program Files\WinMerge\WinMergeU.exe",
            r"C:\Program Files (x86)\WinMerge\WinMergeU.exe",
        ]
    )


def focus_process_window(process_id: int) -> None:
    if os.name != "nt":
        return
    try:
        user32 = ctypes.windll.user32
        target_hwnds: list[int] = []

        enum_proc_type = ctypes.WINFUNCTYPE(
            ctypes.c_bool,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )

        def enum_proc(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            window_process_id = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_process_id))
            if window_process_id.value == process_id:
                target_hwnds.append(hwnd)
                return False
            return True

        user32.EnumWindows(enum_proc_type(enum_proc), 0)
        if not target_hwnds:
            return
        hwnd = target_hwnds[0]
        user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)
    except Exception:
        return


def execute_gui_export(
    selected: tuple[
        str,
        Path | None,
        str,
        str,
        str,
        str,
        str,
        str,
        str,
        str,
        str,
        str,
        str,
        list[str],
        bool,
        bool,
        bool,
        bool,
    ],
    base_output: Path,
) -> GuiExportResult:
    (
        environment,
        production_folder,
        selected_date,
        bank,
        source_log,
        transaction_uid,
        stan,
        rrn,
        authcode,
        sequence_number,
        response_code_spdh,
        response_code_iso,
        protocol_choice,
        selected_trans_uids,
        include_byte_data,
        include_internal,
        include_tango_to_network,
        include_network_to_tango,
    ) = selected

    local_audits: list[Path] = []
    bank_dir = base_output / bank_directory_name(bank)
    date_dir = bank_dir / selected_date
    if environment in {SOURCE_SSH_UAT, SOURCE_LOG_FOLDER}:
        source_folder = (
            Path(source_log).parent if environment == SOURCE_LOG_FOLDER else Path(source_log)
        )
        local_logs = list_local_logs(source_folder)
        if not local_logs:
            raise ValueError(f"No tango.log files found in {source_folder}.")
        local_tango_log = Path(local_logs[0])
        source_audits = list_local_audits(source_folder, selected_date, bank)
        has_ptms = any(path.name.startswith("audit.PTMS") for path in source_audits)
        has_opn = any(
            path.name.startswith("audit.")
            and len(path.name.split(".")) >= 3
            and bank_audit_code_matches(bank, path.name.split(".")[1])
            for path in source_audits
        )
        if not has_ptms or not has_opn:
            missing = []
            if not has_ptms:
                missing.append("audit.PTMS*")
            if not has_opn:
                missing.append(f"audit.{BANK_AUDIT_CODES[bank][:-2]}##")
            raise ValueError(
                f"Missing audit file(s) for {bank} on "
                f"{selected_date}: {', '.join(missing)}"
            )
        local_audits = source_audits
    else:
        assert production_folder is not None
        source_dir = date_dir / "source"
        source_dir.mkdir(parents=True, exist_ok=True)
        local_tango_log = decompress_file(
            cache_local_file(Path(source_log), source_dir)
        )
        source_audits = list_local_audits(production_folder, selected_date, bank)
        has_ptms = any(path.name.startswith("audit.PTMS") for path in source_audits)
        has_opn = any(
            path.name.startswith("audit.")
            and len(path.name.split(".")) >= 3
            and bank_audit_code_matches(bank, path.name.split(".")[1])
            for path in source_audits
        )
        if not has_ptms or not has_opn:
            missing = []
            if not has_ptms:
                missing.append("audit.PTMS*")
            if not has_opn:
                missing.append(f"audit.{BANK_AUDIT_CODES[bank][:-2]}##")
            raise ValueError(
                f"Missing production audit file(s) for {bank} on "
                f"{selected_date}: {', '.join(missing)}"
            )
        for source_audit in source_audits:
            local_audits.append(decompress_file(cache_local_file(source_audit, source_dir)))

    stats = split_audit_files(
        local_audits,
        date_dir,
        bank=bank,
        transaction_uid=transaction_uid,
        transaction_uids=set(selected_trans_uids),
        stan=stan,
        rrn=rrn,
        authcode=authcode,
        sequence_number=sequence_number,
        response_code_spdh=response_code_spdh,
        response_code_iso=response_code_iso,
        tango_log_path=local_tango_log,
        protocol_choice=protocol_choice,
        include_byte_data=include_byte_data,
        include_internal=include_internal,
        include_tango_to_network=include_tango_to_network,
        include_network_to_tango=include_network_to_tango,
    )
    has_target_filters = any(
        (
            transaction_uid,
            stan,
            rrn,
            authcode,
            sequence_number,
            response_code_spdh,
            response_code_iso,
            *selected_trans_uids,
        )
    )
    if has_target_filters and stats["transactions"] == 0:
        raise ValueError(
            f"No transaction matched the selected filters for "
            f"{bank} on {selected_date} with protocol {protocol_choice}."
        )
    summary = (
        f"Environment: {environment}\n"
        f"Bank: {bank}\n"
        f"Date: {selected_date}\n"
        f"TransUID: {transaction_uid or 'ALL'}\n"
        f"STAN: {stan or 'ALL'}\n"
        f"RRN: {rrn or 'ALL'}\n"
        f"AuthCode: {authcode or 'ALL'}\n"
        f"Sequence_Number: {sequence_number or 'ALL'}\n"
        f"RC_SPDH: {response_code_spdh or 'ALL'}\n"
        f"RC_ISO: {response_code_iso or 'ALL'}\n"
        f"Protocol: {protocol_choice}\n"
        f"Byte/Data: {'INCLUDED' if include_byte_data else 'EXCLUDED'}\n"
        f"Tango Internal: {'INCLUDED' if include_internal else 'EXCLUDED'}\n"
        f"Tango->Network: {'INCLUDED' if include_tango_to_network else 'EXCLUDED'}\n"
        f"Network->Tango: {'INCLUDED' if include_network_to_tango else 'EXCLUDED'}\n"
        f"Audit files: {len(local_audits)}\n"
        f"Transactions: {stats['transactions']}\n"
        f"Tango lines: {stats['tango_lines']}\n"
        f"Output: {date_dir}"
    )
    return GuiExportResult(summary, date_dir, list(selected_trans_uids))
