from __future__ import annotations

import subprocess
import tempfile
from datetime import date
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


def list_remote_uat_sources(selected_date: str, bank: str) -> list[str]:
    log_paths = list_remote_logs_for_date(selected_date)
    if bank == "All":
        compact_date = selected_date.replace("-", "")
        command = (
            f"find {REMOTE_AUDIT_DIR} -maxdepth 1 -type f \\( "
            f"-name 'audit.PTMS*.*{selected_date}*' -o "
            f"-name 'audit.PTMS*.*{compact_date}*' -o "
            f"-name 'audit.OPN*.*{selected_date}*' -o "
            f"-name 'audit.OPN*.*{compact_date}*' \\) -print | sort"
        )
        output = run_remote_command(command, sudo=True)
        audit_paths = [line.strip() for line in output.splitlines() if line.strip()]
    else:
        audit_paths = list_remote_audits(selected_date, bank)
    return list(dict.fromkeys(log_paths + audit_paths))


def download_uat_sources(
    selected_date: str,
    bank: str,
    output_root: Path,
    progress_callback=None,
    ready_names: set[str] | None = None,
) -> Path:
    target_dir = output_root / f"{selected_date}_UAT" / bank_directory_name(bank)
    target_dir.mkdir(parents=True, exist_ok=True)
    remote_paths = list_remote_uat_sources(selected_date, bank)
    if not remote_paths:
        raise ValueError(f"No UAT source files were found for {bank} on {selected_date}.")

    force_refresh = selected_date == date.today().isoformat()
    total_steps = len(remote_paths) * 2
    current_step = 0

    def report(message: str) -> None:
        if progress_callback:
            progress_callback(current_step, total_steps, message)

    downloaded: list[Path] = []
    for remote_path in remote_paths:
        local_path = target_dir / Path(remote_path).name
        file_already_exists = local_path.is_file() and not force_refresh
        if file_already_exists:
            report(f"Existing file, skipping download: {local_path.name}")
            downloaded.append(local_path)
        else:
            report(f"Downloading: {Path(remote_path).name}")
            downloaded.append(
                download_remote_file(
                    remote_path,
                    target_dir,
                    overwrite=force_refresh,
                )
            )
        current_step += 1
        if file_already_exists:
            report(f"Existing file ready: {local_path.name}")
        else:
            report(f"Downloading complete: {Path(remote_path).name}")

    for path in downloaded:
        extracted_path = path.with_suffix("") if is_gzip_file(path) else path
        extracted_file_already_exists = extracted_path.is_file() and not force_refresh
        if extracted_file_already_exists:
            report(f"Existing extracted file: {extracted_path.name}")
        else:
            report(f"Extracting: {path.name}")
        decompress_file(path, overwrite=force_refresh)
        if ready_names is not None:
            ready_names.add(path.name)
        current_step += 1
        if extracted_file_already_exists:
            report(f"Existing extracted file ready: {extracted_path.name}")
        else:
            report(f"Extracting complete: {path.name}")
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


def download_remaining_uat_audits(
    selected_date: str,
    target_dir: Path,
    ready_names: set[str],
    progress_callback=None,
    cancel_event=None,
) -> None:
    """Publish complete audit files without modifying the foreground sources."""
    def cancelled():
        return cancel_event is not None and cancel_event.is_set()

    if cancelled():
        return
    remote_paths = [
        path for path in list_remote_uat_sources(selected_date, "All")
        if Path(path).name.startswith(("audit.PTMS", "audit.OPN"))
    ]
    force_refresh = selected_date == date.today().isoformat()
    errors = []
    for index, remote_path in enumerate(remote_paths, start=1):
        if cancelled():
            return
        name = Path(remote_path).name
        local_path = target_dir / name
        extracted_path = local_path.with_suffix("") if is_gzip_file(local_path) else local_path
        if name in ready_names and extracted_path.is_file():
            continue
        if progress_callback:
            progress_callback(f"Background audits {index}/{len(remote_paths)}: {name}")
        try:
            # Staging also keeps incomplete files out of bank scans and exports.
            with tempfile.TemporaryDirectory(prefix=".uat-", dir=target_dir) as staging:
                staging_dir = Path(staging)
                if local_path.is_file() and not force_refresh:
                    if extracted_path.is_file():
                        continue
                    staged = cache_local_file(local_path, staging_dir)
                else:
                    staged = download_remote_file(remote_path, staging_dir)
                extracted = decompress_file(staged)
                if cancelled():
                    return
                if extracted != staged:
                    extracted.replace(extracted_path)
                staged.replace(local_path)
        except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError) as exc:
            errors.append(f"{name}: {exc}")
    if errors:
        raise RuntimeError("Some background audit downloads failed: " + "; ".join(errors))


def bank_directory_name(bank: str) -> str:
    return safe_component(bank.replace("/", "_"))
