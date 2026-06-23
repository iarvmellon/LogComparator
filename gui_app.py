from __future__ import annotations

import ctypes
import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from tkcalendar import Calendar

from log_core import *


def choose_run_options(base_output: Path = DEFAULT_OUTPUT) -> tuple[
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
    list[str],
    bool,
    bool,
    bool,
    bool,
] | None:
    root = tk.Tk()
    root.title("LogComparator")
    root.geometry("860x560")
    root.minsize(780, 520)
    try:
        root.state("zoomed")
    except tk.TclError:
        root.geometry(
            f"{root.winfo_screenwidth()}x{root.winfo_screenheight()}+0+0"
        )

    selection: dict[str, str] = {}
    selected_remote_log: dict[str, str] = {}

    environment_var = tk.StringVar(root, value=SOURCE_ENVIRONMENTS[0])
    protocol_var = tk.StringVar(root, value=PROTOCOL_CHOICES[0])
    include_byte_data_var = tk.BooleanVar(root, value=True)
    folder_var = tk.StringVar(root)
    bank_var = tk.StringVar(root)
    trans_uid_var = tk.StringVar(root)
    stan_var = tk.StringVar(root)
    rrn_var = tk.StringVar(root)
    authcode_var = tk.StringVar(root)
    response_code_spdh_var = tk.StringVar(root)
    response_code_iso_var = tk.StringVar(root)
    include_internal_var = tk.BooleanVar(root, value=True)
    include_tango_to_network_var = tk.BooleanVar(root, value=True)
    include_network_to_tango_var = tk.BooleanVar(root, value=True)
    selected_date_var = tk.StringVar(root, value="Not selected")
    status_var = tk.StringVar(root, value="")
    inline_progress_var = tk.DoubleVar(root, value=0.0)
    inline_progress_text_var = tk.StringVar(root, value="")
    transaction_rows: list[tuple[str, tuple[str, ...]]] = []
    transaction_sort_state: dict[str, bool] = {}
    transaction_load_cache: dict[
        tuple[str, str, tuple[tuple[str, int, int], ...]],
        list[tuple[str, tuple[str, ...]]],
    ] = {}
    transaction_scan_cache: dict[
        tuple[tuple[str, int, int], ...],
        dict[str, Transaction],
    ] = {}
    transaction_load_token = {"value": 0}

    menubar = tk.Menu(root)
    file_menu = tk.Menu(menubar, tearoff=0)
    tools_menu = tk.Menu(menubar, tearoff=0)
    help_menu = tk.Menu(menubar, tearoff=0)
    generated_menu = tk.Menu(file_menu, tearoff=0)

    def clear_selected_remote_date() -> None:
        selected_remote_log.clear()
        selected_date_var.set("Not selected")

    def update_bank_state() -> None:
        folder_text = folder_var.get().strip()
        available_banks = available_banks_for_folder(Path(folder_text)) if folder_text else []
        bank_combo.configure(values=available_banks)
        if bank_var.get() not in available_banks:
            bank_var.set("")
            clear_transaction_list()
        has_banks = bool(available_banks)
        bank_combo.configure(state="readonly" if has_banks else "disabled")
        entry_state = "normal" if folder_text or selected_remote_log else "disabled"
        trans_uid_entry.configure(state=entry_state)
        stan_entry.configure(state=entry_state)
        rrn_entry.configure(state=entry_state)
        authcode_entry.configure(state=entry_state)
        response_code_spdh_entry.configure(state=entry_state)
        response_code_iso_entry.configure(state=entry_state)

    def update_source_state() -> None:
        is_log_folder = environment_var.get() == SOURCE_LOG_FOLDER
        if is_log_folder:
            if not folder_frame.winfo_ismapped():
                folder_frame.pack(
                    fill=tk.X,
                    padx=12,
                    pady=(4, 4),
                    before=action_frame,
                )
            folder_entry.configure(state="readonly")
            select_date_button.pack_forget()
        else:
            if not folder_frame.winfo_ismapped():
                folder_frame.pack(
                    fill=tk.X,
                    padx=12,
                    pady=(4, 4),
                    before=action_frame,
                )
            folder_entry.configure(state="readonly")
            if not ssh_date_frame.winfo_ismapped():
                ssh_date_frame.pack(side=tk.LEFT, padx=(0, 12))
            root.after(50, select_ssh_date)
        if is_log_folder:
            ssh_date_frame.pack_forget()
        clear_selected_remote_date()
        update_bank_state()
        if is_log_folder:
            status_var.set("")
        else:
            status_var.set("Select a date from SSH/SCP (UAT).")

    def select_ssh_source() -> None:
        if environment_var.get() != SOURCE_SSH_UAT:
            environment_var.set(SOURCE_SSH_UAT)
        update_source_state()

    for protocol in PROTOCOL_CHOICES:
        generated_menu.add_radiobutton(
            label=protocol,
            variable=protocol_var,
            value=protocol,
        )
    generated_menu.add_separator()
    generated_menu.add_checkbutton(
        label="Include byte/data",
        variable=include_byte_data_var,
    )
    generated_menu.add_separator()
    generated_menu.add_command(label="Audit blocks", state=tk.DISABLED)
    generated_menu.add_checkbutton(
        label="Tango Internal",
        variable=include_internal_var,
    )
    generated_menu.add_checkbutton(
        label="Tango->Network",
        variable=include_tango_to_network_var,
    )
    generated_menu.add_checkbutton(
        label="Network->Tango",
        variable=include_network_to_tango_var,
    )

    options_bar = tk.Frame(root, bd=1, relief=tk.GROOVE)
    options_bar.pack(fill=tk.X, padx=8, pady=(8, 4))

    generated_options = tk.LabelFrame(options_bar, text="Generated files")
    generated_options.pack(side=tk.LEFT, padx=(6, 10), pady=6)
    for protocol in PROTOCOL_CHOICES:
        tk.Radiobutton(
            generated_options,
            text=protocol,
            variable=protocol_var,
            value=protocol,
        ).pack(side=tk.LEFT, padx=4)

    data_options = tk.LabelFrame(options_bar, text="Byte/Data")
    data_options.pack(side=tk.LEFT, padx=(0, 6), pady=6)
    tk.Checkbutton(
        data_options,
        text="Include",
        variable=include_byte_data_var,
    ).pack(side=tk.LEFT, padx=6)
    flow_options = tk.LabelFrame(options_bar, text="Audit blocks")
    flow_options.pack(side=tk.LEFT, padx=(0, 6), pady=6)
    tk.Checkbutton(
        flow_options,
        text="Tango Internal",
        variable=include_internal_var,
    ).pack(side=tk.LEFT, padx=4)
    tk.Checkbutton(
        flow_options,
        text="Tango->Network",
        variable=include_tango_to_network_var,
    ).pack(side=tk.LEFT, padx=4)
    tk.Checkbutton(
        flow_options,
        text="Network->Tango",
        variable=include_network_to_tango_var,
    ).pack(side=tk.LEFT, padx=4)

    command_options = tk.Frame(options_bar)
    command_options.pack(side=tk.RIGHT, padx=(10, 6), pady=6)
    tk.Label(command_options, text="Selected date:").pack(side=tk.LEFT, padx=(0, 6))
    tk.Label(command_options, textvariable=selected_date_var, width=14, anchor="w").pack(
        side=tk.LEFT,
        padx=(0, 12),
    )
    folder_frame = tk.Frame(root)
    folder_frame.pack(fill=tk.X, padx=12, pady=(4, 4))
    tk.Label(folder_frame, text="Log folder:").pack(side=tk.LEFT, padx=(0, 8))
    folder_entry = tk.Entry(folder_frame, textvariable=folder_var, state="readonly")
    folder_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def import_log_folder() -> None:
        folder = filedialog.askdirectory(title="Select log folder")
        if folder:
            if environment_var.get() != SOURCE_LOG_FOLDER:
                environment_var.set(SOURCE_LOG_FOLDER)
            folder_var.set(folder)
            clear_selected_remote_date()
            update_source_state()
            update_bank_state()
            status_var.set("")

    file_menu.add_command(label=SOURCE_SSH_UAT, command=select_ssh_source)
    file_menu.add_cascade(label="Export options", menu=generated_menu)
    file_menu.add_separator()
    file_menu.add_command(label="Exit", command=root.destroy)
    menubar.add_cascade(label="File", menu=file_menu)
    menubar.add_cascade(label="Tools", menu=tools_menu)
    help_menu.add_command(
        label="About",
        command=lambda: messagebox.showinfo(
            "About LogComparator",
            f"LogComparator\nVersion: {APP_VERSION}\nAuthor: {APP_AUTHOR}",
            parent=root,
        ),
    )
    menubar.add_cascade(label="Help", menu=help_menu)
    root.config(menu=menubar)

    action_frame = tk.Frame(root)
    action_frame.pack(fill=tk.X, padx=12, pady=(4, 6))

    def choose_remote_date_window(paths: list[str]) -> tuple[str, str] | None:
        valid_dates: dict[str, str] = {}
        for path in paths:
            date_part = parse_log_date(any_path_name(path))
            if date_part:
                valid_dates[date_part] = path
        if not valid_dates:
            raise ValueError("No matching Tango log files were found.")

        dialog = tk.Toplevel(root)
        dialog.title("Select SSH/SCP date")
        dialog.geometry("420x360")
        dialog.minsize(380, 330)
        dialog.transient(root)
        dialog.grab_set()

        result: dict[str, str] = {}
        default_date = sorted(valid_dates)[0]
        initial = datetime.strptime(default_date, "%Y-%m-%d")
        tk.Label(dialog, text="Select a highlighted date:").pack(pady=(10, 5))
        remote_calendar = Calendar(
            dialog,
            selectmode="day",
            year=initial.year,
            month=initial.month,
            day=initial.day,
        )
        valid_date_objects: dict[object, str] = {}
        for date_value, path in valid_dates.items():
            event_date = datetime.strptime(date_value, "%Y-%m-%d").date()
            valid_date_objects[event_date] = path
            remote_calendar.calevent_create(event_date, "", tags=["valid"])
        remote_calendar.tag_config("valid", background="#c8f7c5", foreground="black")
        remote_calendar.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)

        def selected_date():
            try:
                return datetime.strptime(remote_calendar.get_date(), "%m/%d/%y").date()
            except (TypeError, ValueError):
                return None

        def submit_date() -> None:
            chosen = selected_date()
            if chosen not in valid_date_objects:
                messagebox.showwarning(
                    "Invalid date",
                    "Please select a highlighted date.",
                    parent=dialog,
                )
                return
            result["date"] = chosen.strftime("%Y-%m-%d")
            result["path"] = valid_date_objects[chosen]
            dialog.destroy()

        def cancel_date() -> None:
            dialog.destroy()

        button_frame = tk.Frame(dialog)
        button_frame.pack(pady=(8, 12))
        tk.Button(button_frame, text="Select", command=submit_date).pack(
            side=tk.LEFT,
            padx=4,
        )
        tk.Button(button_frame, text="Cancel", command=cancel_date).pack(
            side=tk.LEFT,
            padx=4,
        )
        dialog.protocol("WM_DELETE_WINDOW", cancel_date)
        root.wait_window(dialog)
        if not result:
            return None
        return result["date"], result["path"]

    def select_ssh_date() -> None:
        def update_progress(current: int, total: int, message: str) -> None:
            percent = (current / total) * 100 if total else 0
            if total:
                inline_progress_var.set(percent)
            inline_progress_text_var.set(f"{message} ({percent:.0f}%)")
            root.update_idletasks()

        try:
            root.config(cursor="watch")
            root.update_idletasks()
            run_remote_command("whoami")
            run_remote_command("su -c 'whoami'", sudo=True)
            selected = choose_remote_date_window(list_remote_logs())
            if selected is None:
                return
            selected_date, selected_path = selected
            status_var.set(f"Downloading UAT sources for {selected_date}...")
            show_inline_progress("Preparing download...", 0)
            root.update_idletasks()
            uat_folder = download_uat_sources(
                selected_date,
                base_output,
                progress_callback=update_progress,
            )
            show_inline_progress("UAT sources ready", 100)
            selected_remote_log["date"] = selected_date
            selected_remote_log["path"] = selected_path
            selected_remote_log["folder"] = str(uat_folder)
            if not folder_frame.winfo_ismapped():
                folder_frame.pack(
                    fill=tk.X,
                    padx=12,
                    pady=(4, 4),
                    before=action_frame,
                )
            folder_entry.configure(state="readonly")
            folder_var.set(str(uat_folder))
            selected_date_var.set(selected_date)
            update_bank_state()
            status_var.set(f"UAT sources ready: {uat_folder}")
        except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError) as exc:
            messagebox.showerror("Select date failed", str(exc))
            status_var.set(f"Select date failed: {exc}")
        finally:
            hide_inline_progress()
            root.config(cursor="")

    ssh_date_frame = tk.Frame(action_frame)
    select_date_button = tk.Button(
        ssh_date_frame,
        text="Change SSH/SCP date",
        command=select_ssh_date,
    )
    select_date_button.pack(side=tk.LEFT, padx=(0, 10))
    fields = tk.Frame(root)
    fields.pack(fill=tk.X, padx=12, pady=(4, 4))
    tk.Label(fields, text="Bank/Acquirer:").pack(side=tk.LEFT, padx=(0, 8))
    bank_combo = ttk.Combobox(
        fields,
        textvariable=bank_var,
        values=list(BANK_AUDIT_CODES),
        state="disabled",
        width=25,
    )
    bank_combo.pack(side=tk.LEFT)
    tk.Label(fields, text="TransUID:").pack(side=tk.LEFT, padx=(14, 8))
    trans_uid_entry = tk.Entry(
        fields,
        textvariable=trans_uid_var,
        width=30,
        state="disabled",
    )
    trans_uid_entry.pack(side=tk.LEFT)
    tk.Label(fields, text="STAN:").pack(side=tk.LEFT, padx=(14, 8))
    stan_entry = tk.Entry(
        fields,
        textvariable=stan_var,
        width=18,
        state="disabled",
    )
    stan_entry.pack(side=tk.LEFT)
    tk.Label(fields, text="RRN:").pack(side=tk.LEFT, padx=(14, 8))
    rrn_entry = tk.Entry(
        fields,
        textvariable=rrn_var,
        width=22,
        state="disabled",
    )
    rrn_entry.pack(side=tk.LEFT)
    tk.Label(fields, text="AuthCode:").pack(side=tk.LEFT, padx=(14, 8))
    authcode_entry = tk.Entry(
        fields,
        textvariable=authcode_var,
        width=12,
        state="disabled",
    )
    authcode_entry.pack(side=tk.LEFT)
    tk.Label(fields, text="responseCodeSPDH:").pack(side=tk.LEFT, padx=(14, 8))
    response_code_spdh_entry = tk.Entry(
        fields,
        textvariable=response_code_spdh_var,
        width=8,
        state="disabled",
    )
    response_code_spdh_entry.pack(side=tk.LEFT)
    tk.Label(fields, text="responseCodeISO:").pack(side=tk.LEFT, padx=(14, 8))
    response_code_iso_entry = tk.Entry(
        fields,
        textvariable=response_code_iso_var,
        width=8,
        state="disabled",
    )
    response_code_iso_entry.pack(side=tk.LEFT)

    transaction_columns = (
        "datetime",
        "transuid",
        "rrn",
        "stan",
        "authcode",
        "transactiontype",
        "responsecodespdh",
        "responsecodeiso",
    )
    transaction_frame = tk.Frame(root)
    transaction_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(6, 8))
    transaction_tree = ttk.Treeview(
        transaction_frame,
        columns=transaction_columns,
        show="headings",
        height=18,
        selectmode="extended",
    )
    column_labels = {
        "datetime": "Date/Time",
        "transuid": "transUid",
        "rrn": "RRN",
        "stan": "STAN",
        "authcode": "AuthCode",
        "transactiontype": "TransactionType",
        "responsecodespdh": "responseCodeSPDH",
        "responsecodeiso": "responseCodeISO",
    }
    column_widths = {
        "datetime": 170,
        "transuid": 230,
        "rrn": 130,
        "stan": 90,
        "authcode": 100,
        "transactiontype": 170,
        "responsecodespdh": 170,
        "responsecodeiso": 170,
    }
    def sort_transaction_tree(column: str) -> None:
        reverse = transaction_sort_state.get(column, False)
        children = list(transaction_tree.get_children(""))
        column_index = transaction_columns.index(column)

        def sort_key(item_id: str):
            value = transaction_tree.item(item_id, "values")[column_index]
            if column == "datetime":
                try:
                    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S.%f")
                except ValueError:
                    return datetime.min
            return str(value).casefold()

        for position, item_id in enumerate(
            sorted(children, key=sort_key, reverse=reverse)
        ):
            transaction_tree.move(item_id, "", position)
        transaction_sort_state[column] = not reverse

    for column in transaction_columns:
        transaction_tree.heading(
            column,
            text=column_labels[column],
            command=lambda col=column: sort_transaction_tree(col),
        )
        transaction_tree.column(
            column,
            width=column_widths[column],
            minwidth=80,
            stretch=False,
        )
    y_scroll = ttk.Scrollbar(
        transaction_frame,
        orient=tk.VERTICAL,
        command=transaction_tree.yview,
    )
    x_scroll = ttk.Scrollbar(
        transaction_frame,
        orient=tk.HORIZONTAL,
        command=transaction_tree.xview,
    )
    transaction_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
    transaction_tree.grid(row=0, column=0, sticky="nsew")
    y_scroll.grid(row=0, column=1, sticky="ns")
    x_scroll.grid(row=1, column=0, sticky="ew")
    transaction_frame.rowconfigure(0, weight=1)
    transaction_frame.columnconfigure(0, weight=1)

    def clear_transaction_list() -> None:
        transaction_tree.delete(*transaction_tree.get_children())

    def row_matches_filters(values: tuple[str, ...]) -> bool:
        filters = {
            "transuid": trans_uid_var.get().strip(),
            "rrn": rrn_var.get().strip(),
            "stan": stan_var.get().strip(),
            "authcode": authcode_var.get().strip(),
            "responsecodespdh": response_code_spdh_var.get().strip(),
            "responsecodeiso": response_code_iso_var.get().strip(),
        }
        value_by_column = dict(zip(transaction_columns, values))
        for column, filter_value in filters.items():
            if filter_value and filter_value.casefold() not in value_by_column[column].casefold():
                return False
        return True

    def apply_transaction_filters(*_args) -> None:
        clear_transaction_list()
        for uid, values in transaction_rows:
            if row_matches_filters(values):
                transaction_tree.insert("", tk.END, iid=uid, values=values)

    def transaction_audit_cache_key(
        bank: str,
        selected_date: str,
        audits: list[Path],
    ) -> tuple[str, str, tuple[tuple[str, int, int], ...]]:
        return bank, selected_date, transaction_scan_cache_key(audits)

    def transaction_scan_cache_key(
        audits: list[Path],
    ) -> tuple[tuple[str, int, int], ...]:
        return tuple(
            (str(path), path.stat().st_mtime_ns, path.stat().st_size)
            for path in audits
        )

    def build_transaction_rows(
        bank: str,
        audits: list[Path],
        progress_callback: Callable[[float, str], None] | None = None,
    ) -> list[tuple[str, tuple[str, ...]]]:
        def report_scan_progress(current: int, total: int, message: str) -> None:
            if progress_callback:
                percent = 85.0 if total <= 0 else min((current / total) * 85.0, 85.0)
                progress_callback(percent, message)

        scan_key = transaction_scan_cache_key(audits)
        transactions = transaction_scan_cache.get(scan_key)
        if transactions is None:
            transactions, _ = scan_transactions(
                audits,
                report_scan_progress,
                load_into_memory=True,
                correlate_missing=False,
            )
            transaction_scan_cache[scan_key] = transactions
        elif progress_callback:
            progress_callback(85.0, "Using cached transactions")
        if progress_callback:
            progress_callback(88.0, "Build transaction list")
        expected_ids = BANK_ACQUIRER_IDS.get(bank, set())
        expected_process = BANK_AUDIT_CODES.get(bank)
        matching = [
            transaction
            for transaction in transactions.values()
            if (
                transaction.acquirer_ids & expected_ids
                or (
                    expected_process is not None
                    and expected_process in transaction.process_names
                )
            )
        ]
        matching.sort(key=lambda transaction: transaction.first_index)
        rows: list[tuple[str, tuple[str, ...]]] = []
        total_matching = max(len(matching), 1)
        for row_index, transaction in enumerate(matching, start=1):
            timestamp = transaction.request_timestamp or transaction.first_timestamp
            readable_time = (
                timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                if timestamp
                else ""
            )
            mti = select_iso_mti(transaction)
            transaction_type = TANGO_TRANSACTION_MTI_NAMES.get(
                mti,
                MTI_NAMES.get(mti, mti),
            )
            rrn_value = select_rrn(transaction)
            values = (
                readable_time,
                transaction.trans_uid,
                "" if rrn_value == "NO_RRN" else rrn_value,
                select_identifier(transaction, "stan"),
                select_identifier(transaction, "authcode"),
                transaction_type,
                response_code_component(
                    select_response_code(transaction.spdh_response_codes),
                    SPDH_RC_NAMES,
                ),
                response_code_component(
                    select_response_code(transaction.iso_response_codes),
                    ISO_RC_NAMES,
                ),
            )
            rows.append((transaction.trans_uid, values))
            if progress_callback and (row_index == len(matching) or row_index % 250 == 0):
                progress_callback(
                    88.0 + min((row_index / total_matching) * 12.0, 12.0),
                    "Build transaction list",
                )
        if progress_callback:
            progress_callback(100.0, "Load transactions complete")
        return rows

    def populate_transaction_rows(
        rows: list[tuple[str, tuple[str, ...]]],
        selected_date: str,
    ) -> None:
        transaction_rows[:] = rows
        apply_transaction_filters()
        selected_date_var.set(selected_date)
        status_var.set(f"Loaded transactions: {len(rows)}")

    def load_transaction_list(event=None) -> None:
        transaction_load_token["value"] += 1
        token = transaction_load_token["value"]
        transaction_rows.clear()
        clear_transaction_list()
        bank = bank_var.get().strip()
        folder_text = folder_var.get().strip()
        if not bank or not folder_text:
            return
        try:
            selected_date, _ = select_log_folder_source(Path(folder_text))
            audits = list_local_audits(Path(folder_text), selected_date, bank)
            if not audits:
                return
            cache_key = transaction_audit_cache_key(bank, selected_date, audits)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Transaction list failed", str(exc), parent=root)
            return

        cached_rows = transaction_load_cache.get(cache_key)
        if cached_rows is not None:
            populate_transaction_rows(cached_rows, selected_date)
            return

        status_var.set("Load transactions...")
        show_inline_progress("Load transactions", 0)
        result_queue: queue.Queue[
            tuple[
                str,
                list[tuple[str, tuple[str, ...]]]
                | BaseException
                | tuple[float, str],
            ]
        ] = queue.Queue()

        def finish_success(
            finished_token: int,
            rows: list[tuple[str, tuple[str, ...]]],
        ) -> None:
            if finished_token != transaction_load_token["value"]:
                return
            hide_inline_progress()
            transaction_load_cache[cache_key] = rows
            populate_transaction_rows(rows, selected_date)

        def finish_error(finished_token: int, exc: BaseException) -> None:
            if finished_token != transaction_load_token["value"]:
                return
            hide_inline_progress()
            status_var.set(f"Transaction list failed: {exc}")
            messagebox.showerror("Transaction list failed", str(exc), parent=root)

        def worker() -> None:
            def report_progress(percent: float, message: str) -> None:
                result_queue.put(("progress", (percent, message)))

            try:
                rows = build_transaction_rows(bank, audits, report_progress)
            except (OSError, ValueError) as exc:
                result_queue.put(("error", exc))
            else:
                result_queue.put(("success", rows))

        threading.Thread(target=worker, daemon=True).start()

        def poll_load_result() -> None:
            try:
                status, payload = result_queue.get_nowait()
            except queue.Empty:
                root.after(100, poll_load_result)
                return
            if status == "progress":
                percent, message = payload
                bounded_percent = max(0.0, min(float(percent), 100.0))
                show_inline_progress(f"{message} ({bounded_percent:.0f}%)", bounded_percent)
                root.after(50, poll_load_result)
            elif status == "error":
                finish_error(token, payload)
            else:
                finish_success(token, payload)

        root.after(100, poll_load_result)

    bank_combo.bind("<<ComboboxSelected>>", load_transaction_list)
    for filter_var in (
        trans_uid_var,
        rrn_var,
        stan_var,
        authcode_var,
        response_code_spdh_var,
        response_code_iso_var,
    ):
        filter_var.trace_add("write", apply_transaction_filters)

    bottom_bar = tk.Frame(root)
    bottom_bar.pack(fill=tk.X, padx=12, pady=(0, 8))
    tk.Label(bottom_bar, textvariable=status_var, anchor="w").pack(
        side=tk.LEFT,
        fill=tk.X,
        expand=True,
    )
    inline_progress_frame = tk.Frame(bottom_bar)
    inline_progress_label = tk.Label(
        inline_progress_frame,
        textvariable=inline_progress_text_var,
        anchor="e",
        width=42,
    )
    inline_progress_label.pack(side=tk.LEFT, padx=(8, 6))
    ttk.Progressbar(
        inline_progress_frame,
        mode="determinate",
        maximum=100,
        variable=inline_progress_var,
        length=240,
    ).pack(side=tk.LEFT)

    def show_inline_progress(message: str, percent: float) -> None:
        inline_progress_var.set(max(0.0, min(float(percent), 100.0)))
        inline_progress_text_var.set(message)
        if not inline_progress_frame.winfo_ismapped():
            inline_progress_frame.pack(side=tk.RIGHT)
        root.update_idletasks()

    def hide_inline_progress() -> None:
        inline_progress_var.set(0.0)
        inline_progress_text_var.set("")
        if inline_progress_frame.winfo_ismapped():
            inline_progress_frame.pack_forget()
        root.update_idletasks()

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

    def select_log_folder_source(folder: Path) -> tuple[str, str]:
        logs = list_local_logs(folder)
        dates_by_path: list[tuple[str, str]] = []
        for path in logs:
            date_part = parse_log_date(any_path_name(path))
            if date_part:
                dates_by_path.append((date_part, path))
        unique_dates = sorted({date for date, _ in dates_by_path})
        if not unique_dates:
            raise ValueError("No tango.log file was found in the selected log folder.")
        if len(unique_dates) > 1:
            raise ValueError(
                "The selected log folder contains multiple log dates. "
                "Use a folder with one daily tango.log/audit set."
            )
        selected_date = unique_dates[0]
        selected_path = next(path for date, path in dates_by_path if date == selected_date)
        return selected_date, selected_path

    def current_selection() -> tuple[
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
        list[str],
        bool,
        bool,
        bool,
        bool,
    ]:
        folder = Path(selection["folder"]) if selection["folder"] else None
        return (
            selection["environment"],
            folder,
            selection["date"],
            selection["bank"],
            selection["path"],
            selection["trans_uid"],
            selection["stan"],
            selection["rrn"],
            selection["authcode"],
            selection["response_code_spdh"],
            selection["response_code_iso"],
            selection["protocol"],
            [uid for uid in selection["selected_trans_uids"].splitlines() if uid],
            selection["include_byte_data"] == "1",
            selection["include_internal"] == "1",
            selection["include_tango_to_network"] == "1",
            selection["include_network_to_tango"] == "1",
        )

    def capture_selection() -> bool:
        bank = bank_var.get().strip()
        if not bank:
            messagebox.showwarning("Bank required", "Please select a bank/acquirer.")
            return False
        environment = environment_var.get()
        folder = folder_var.get().strip()
        if environment == SOURCE_LOG_FOLDER and not folder:
            messagebox.showwarning("Folder required", "Please enter or select a log folder.")
            return False
        try:
            if environment == SOURCE_LOG_FOLDER:
                selected_date, selected_path = select_log_folder_source(Path(folder))
            else:
                selected_date = selected_remote_log.get("date", "")
                selected_path = selected_remote_log.get("folder", "")
                if not selected_date or not selected_path:
                    messagebox.showwarning(
                        "Date required",
                        "Please select an SSH/SCP date first.",
                    )
                    return False
        except (OSError, ValueError) as exc:
            messagebox.showerror("Source selection failed", str(exc))
            status_var.set(f"Source selection failed: {exc}")
            return False
        selection["environment"] = environment
        selection["folder"] = folder
        selection["date"] = selected_date
        selection["bank"] = bank
        selection["path"] = selected_path
        selection["trans_uid"] = trans_uid_var.get().strip()
        selection["stan"] = stan_var.get().strip()
        selection["rrn"] = rrn_var.get().strip()
        selection["authcode"] = authcode_var.get().strip()
        selection["response_code_spdh"] = response_code_spdh_var.get().strip()
        selection["response_code_iso"] = response_code_iso_var.get().strip()
        selection["protocol"] = protocol_var.get().strip()
        selection["selected_trans_uids"] = "\n".join(transaction_tree.selection())
        selection["include_byte_data"] = "1" if include_byte_data_var.get() else "0"
        selection["include_internal"] = "1" if include_internal_var.get() else "0"
        selection["include_tango_to_network"] = "1" if include_tango_to_network_var.get() else "0"
        selection["include_network_to_tango"] = "1" if include_network_to_tango_var.get() else "0"
        return True

    def export_current_selection(show_completion: bool = True) -> GuiExportResult | None:
        if not capture_selection():
            return None
        try:
            open_button.configure(state=tk.DISABLED)
            export_button.configure(state=tk.DISABLED)
            compare_button.configure(state=tk.DISABLED)
            root.config(cursor="watch")
            status_var.set("Exporting...")
            root.update_idletasks()
            result = execute_gui_export(current_selection(), base_output)
            status_var.set("Export complete.")
            if show_completion:
                messagebox.showinfo("Export complete", result.summary, parent=root)
            return result
        except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError) as exc:
            status_var.set(f"Export failed: {exc}")
            messagebox.showerror("Export failed", str(exc), parent=root)
            return None
        finally:
            root.config(cursor="")
            open_button.configure(state=tk.NORMAL)
            export_button.configure(state=tk.NORMAL)
            update_compare_state()

    def submit() -> None:
        export_current_selection(show_completion=True)

    def selected_log_paths(output_dir: Path, trans_uids: list[str]) -> list[Path]:
        return [output_dir / f"{safe_component(uid)}.log" for uid in trans_uids]

    def open_selected_logs() -> None:
        selected_uids = list(transaction_tree.selection())
        if not selected_uids:
            messagebox.showwarning(
                "Selection required",
                "Please select one or more transactions.",
                parent=root,
            )
            return
        result = export_current_selection(show_completion=False)
        if result is None:
            return
        paths = selected_log_paths(result.output_dir, selected_uids)
        missing = [path for path in paths if not path.is_file()]
        if missing:
            messagebox.showerror(
                "Open failed",
                f"Exported log was not found:\n{missing[0]}",
                parent=root,
            )
            return
        notepad = find_notepad_plus_plus()
        if not notepad:
            messagebox.showerror(
                "Notepad++ not found",
                "Notepad++ was not found in PATH or the standard install folders.",
                parent=root,
            )
            return
        subprocess.Popen([notepad, *[str(path) for path in paths]])
        status_var.set(f"Opened logs in Notepad++: {len(paths)}")

    def compare_selected_logs() -> None:
        selected_uids = list(transaction_tree.selection())
        if len(selected_uids) != 2:
            messagebox.showwarning(
                "Two transactions required",
                "Please select exactly two transactions.",
                parent=root,
            )
            return
        result = export_current_selection(show_completion=False)
        if result is None:
            return
        paths = selected_log_paths(result.output_dir, selected_uids)
        missing = [path for path in paths if not path.is_file()]
        if missing:
            messagebox.showerror(
                "Compare failed",
                f"Exported log was not found:\n{missing[0]}",
                parent=root,
            )
            return
        winmerge = find_winmerge()
        if not winmerge:
            messagebox.showerror(
                "WinMerge not found",
                "WinMerge was not found in PATH or the standard install folders.",
                parent=root,
            )
            return
        process = subprocess.Popen([winmerge, "/maximize", str(paths[0]), str(paths[1])])
        root.after(900, lambda pid=process.pid: focus_process_window(pid))
        status_var.set("Opened selected logs in WinMerge.")

    def update_compare_state(event=None) -> None:
        state = tk.NORMAL if len(transaction_tree.selection()) == 2 else tk.DISABLED
        compare_button.configure(state=state)
        tools_menu.entryconfig("Compare", state=state)

    open_button = tk.Button(
        command_options,
        text="Open",
        command=open_selected_logs,
        width=12,
    )
    open_button.pack(
        side=tk.LEFT,
        padx=(0, 6),
    )
    export_button = tk.Button(command_options, text="Export", command=submit, width=12)
    export_button.pack(
        side=tk.LEFT,
        padx=(0, 6),
    )
    compare_button = tk.Button(
        command_options,
        text="Compare",
        command=compare_selected_logs,
        state=tk.DISABLED,
        width=12,
    )
    compare_button.pack(
        side=tk.LEFT,
    )
    tools_menu.add_command(label="Import", command=import_log_folder)
    tools_menu.add_command(label="Open", command=open_selected_logs)
    tools_menu.add_command(label="Export", command=submit)
    tools_menu.add_command(
        label="Compare",
        command=compare_selected_logs,
        state=tk.DISABLED,
    )
    transaction_tree.bind("<<TreeviewSelect>>", update_compare_state)
    update_source_state()
    folder_var.trace_add("write", lambda *_args: update_bank_state())
    update_bank_state()
    root.mainloop()
    if selection.get("interrupted"):
        raise KeyboardInterrupt
    return None


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
        f"-name 'audit.PTMSPMLN01.*{selected_date}*' -o "
        f"-name 'audit.PTMSPMLN01.*{compact_date}*' -o "
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
    has_ptms = any(path.name.startswith("audit.PTMSPMLN01.") for path in extracted)
    has_opn = any(path.name.startswith("audit.OPN") for path in extracted)
    missing = []
    if not has_tango:
        missing.append("tango.log*")
    if not has_ptms:
        missing.append("audit.PTMSPMLN01")
    if not has_opn:
        missing.append("audit.OPN*")
    if missing:
        raise ValueError(
            f"Missing UAT source file(s) for {selected_date}: {', '.join(missing)}"
        )
    return target_dir


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
    if environment == SOURCE_SSH_UAT:
        source_folder = Path(source_log)
        local_logs = list_local_logs(source_folder)
        if not local_logs:
            raise ValueError(f"No tango.log files found in {source_folder}.")
        local_tango_log = Path(local_logs[0])
        source_audits = list_local_audits(source_folder, selected_date, bank)
        audit_code = BANK_AUDIT_CODES[bank]
        has_ptms = any(path.name.startswith("audit.PTMSPMLN01.") for path in source_audits)
        has_opn = any(path.name.startswith(f"audit.{audit_code}.") for path in source_audits)
        if not has_ptms or not has_opn:
            missing = []
            if not has_ptms:
                missing.append("audit.PTMSPMLN01")
            if not has_opn:
                missing.append(f"audit.{audit_code}")
            raise ValueError(
                f"Missing UAT audit file(s) for {bank} on "
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
        audit_code = BANK_AUDIT_CODES[bank]
        has_ptms = any(path.name.startswith("audit.PTMSPMLN01.") for path in source_audits)
        has_opn = any(path.name.startswith(f"audit.{audit_code}.") for path in source_audits)
        if not has_ptms or not has_opn:
            missing = []
            if not has_ptms:
                missing.append("audit.PTMSPMLN01")
            if not has_opn:
                missing.append(f"audit.{audit_code}")
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
        response_code_spdh=response_code_spdh,
        response_code_iso=response_code_iso,
        tango_log_path=local_tango_log,
        protocol_choice=protocol_choice,
        include_byte_data=include_byte_data,
        include_internal=include_internal,
        include_tango_to_network=include_tango_to_network,
        include_network_to_tango=include_network_to_tango,
    )
    has_target_filters = any((
        transaction_uid,
        stan,
        rrn,
        authcode,
        response_code_spdh,
        response_code_iso,
        *selected_trans_uids,
    ))
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
        f"responseCodeSPDH: {response_code_spdh or 'ALL'}\n"
        f"responseCodeISO: {response_code_iso or 'ALL'}\n"
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


def run_gui_workflow(base_output: Path = DEFAULT_OUTPUT) -> int:
    install_interrupt_handler()
    try:
        choose_run_options(base_output)
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        return 130
    except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError) as exc:
        print(f"LogComparator failed: {exc}")
        return 1


