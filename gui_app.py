from __future__ import annotations

import queue
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from tkcalendar import Calendar

from gui_services import (
    download_uat_sources,
    execute_gui_export,
    find_notepad_plus_plus,
    find_winmerge,
    focus_process_window,
    list_remote_logs,
)
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
    style = ttk.Style(root)
    heading_font = tkfont.nametofont("TkHeadingFont").copy()
    heading_font.configure(weight="bold")
    style.configure("Treeview.Heading", font=heading_font)
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
    timezone_var = tk.StringVar(root, value="UTC")
    trans_uid_var = tk.StringVar(root)
    stan_var = tk.StringVar(root)
    rrn_var = tk.StringVar(root)
    authcode_var = tk.StringVar(root)
    sequence_number_var = tk.StringVar(root)
    transaction_type_var = tk.StringVar(root)
    tid_var = tk.StringVar(root)
    mid_var = tk.StringVar(root)
    amount_var = tk.StringVar(root)
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
    current_base_output = {"path": Path(base_output)}
    RUNTIME_SETTINGS.output = Path(base_output)
    RUNTIME_SETTINGS.user = DEFAULT_USER
    RUNTIME_SETTINGS.sudo_password = DEFAULT_SUDO_PASSWORD

    menubar = tk.Menu(root)
    file_menu = tk.Menu(menubar, tearoff=0)
    edit_menu = tk.Menu(menubar, tearoff=0)
    view_menu = tk.Menu(menubar, tearoff=0)
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
        has_selected_bank = bool(bank_var.get().strip()) and bank_var.get() in available_banks
        entry_state = "normal" if has_selected_bank else "disabled"
        trans_uid_entry.configure(state=entry_state)
        stan_entry.configure(state=entry_state)
        rrn_entry.configure(state=entry_state)
        authcode_entry.configure(state=entry_state)
        sequence_number_entry.configure(state=entry_state)
        transaction_type_entry.configure(state=entry_state)
        tid_entry.configure(state=entry_state)
        mid_entry.configure(state=entry_state)
        amount_entry.configure(state=entry_state)
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
    tk.Label(folder_frame, text="Bank/Acquirer:").pack(side=tk.LEFT, padx=(14, 8))
    bank_combo = ttk.Combobox(
        folder_frame,
        textvariable=bank_var,
        values=list(BANK_AUDIT_CODES),
        state="disabled",
        width=25,
    )
    bank_combo.pack(side=tk.LEFT)
    tk.Label(folder_frame, text="Timezone:").pack(side=tk.LEFT, padx=(14, 8))
    timezone_combo = ttk.Combobox(
        folder_frame,
        textvariable=timezone_var,
        values=("UTC", "UTC+1", "UTC+2", "UTC+3", "UTC-1", "UTC-2", "UTC-3"),
        state="readonly",
        width=7,
    )
    timezone_combo.pack(side=tk.LEFT)

    def clear_filters() -> None:
        trans_uid_var.set("")
        stan_var.set("")
        rrn_var.set("")
        authcode_var.set("")
        sequence_number_var.set("")
        transaction_type_var.set("")
        tid_var.set("")
        mid_var.set("")
        amount_var.set("")
        response_code_spdh_var.set("")
        response_code_iso_var.set("")

    def clear_bank_and_transactions() -> None:
        bank_var.set("")
        transaction_rows.clear()
        clear_transaction_list()
        update_compare_state()

    def import_log_folder() -> None:
        folder = filedialog.askdirectory(title="Select log folder")
        if folder:
            folder_path = Path(folder)

            def update_extract_progress(current: int, total: int, message: str) -> None:
                percent = (current / total) * 100 if total else 100
                show_inline_progress(f"{message} ({percent:.0f}%)", percent)

            try:
                root.config(cursor="watch")
                status_var.set("Extracting imported files...")
                show_inline_progress("Extracting imported files", 0)
                root.update_idletasks()
                extract_gzip_files_in_folder(
                    folder_path,
                    progress_callback=update_extract_progress,
                )
                validate_local_log_folder(folder_path)
            except (OSError, ValueError) as exc:
                hide_inline_progress()
                root.config(cursor="")
                status_var.set(f"Import failed: {exc}")
                messagebox.showerror("Import failed", str(exc), parent=root)
                return
            finally:
                hide_inline_progress()
                root.config(cursor="")

            if environment_var.get() != SOURCE_LOG_FOLDER:
                environment_var.set(SOURCE_LOG_FOLDER)
            clear_filters()
            clear_bank_and_transactions()
            folder_var.set(folder)
            clear_selected_remote_date()
            update_source_state()
            update_bank_state()
            status_var.set(f"Imported log folder: {folder}")

    def show_settings_dialog() -> None:
        dialog = tk.Toplevel(root)
        dialog.title("Settings")
        dialog.geometry("620x210")
        dialog.minsize(560, 190)
        dialog.transient(root)
        dialog.grab_set()

        output_var = tk.StringVar(dialog, value=str(current_base_output["path"]))
        user_var = tk.StringVar(dialog, value=RUNTIME_SETTINGS.user)
        sudo_password_var = tk.StringVar(dialog, value=RUNTIME_SETTINGS.sudo_password)

        content = tk.Frame(dialog)
        content.pack(fill=tk.BOTH, expand=True, padx=14, pady=14)
        content.columnconfigure(1, weight=1)

        tk.Label(content, text="Output folder:").grid(
            row=0,
            column=0,
            sticky="w",
            padx=(0, 8),
            pady=(0, 8),
        )
        output_entry = tk.Entry(content, textvariable=output_var)
        output_entry.grid(row=0, column=1, sticky="ew", pady=(0, 8))

        def browse_output_folder() -> None:
            folder = filedialog.askdirectory(
                title="Select output folder",
                initialdir=output_var.get().strip() or str(DEFAULT_OUTPUT),
                parent=dialog,
            )
            if folder:
                output_var.set(folder)

        tk.Button(content, text="Browse", command=browse_output_folder).grid(
            row=0,
            column=2,
            sticky="ew",
            padx=(8, 0),
            pady=(0, 8),
        )
        tk.Label(content, text="SSH user:").grid(
            row=1,
            column=0,
            sticky="w",
            padx=(0, 8),
            pady=(0, 8),
        )
        tk.Entry(content, textvariable=user_var).grid(
            row=1,
            column=1,
            columnspan=2,
            sticky="ew",
            pady=(0, 8),
        )
        tk.Label(content, text="Sudo password:").grid(
            row=2,
            column=0,
            sticky="w",
            padx=(0, 8),
            pady=(0, 8),
        )
        tk.Entry(content, textvariable=sudo_password_var, show="*").grid(
            row=2,
            column=1,
            columnspan=2,
            sticky="ew",
            pady=(0, 8),
        )

        button_frame = tk.Frame(content)
        button_frame.grid(row=3, column=0, columnspan=3, sticky="e", pady=(8, 0))

        def save_settings() -> None:
            output_text = output_var.get().strip()
            user_text = user_var.get().strip()
            if not output_text:
                messagebox.showerror("Settings", "Output folder is required.", parent=dialog)
                return
            if not user_text:
                messagebox.showerror("Settings", "SSH user is required.", parent=dialog)
                return
            output_path = Path(output_text)
            current_base_output["path"] = output_path
            RUNTIME_SETTINGS.output = output_path
            RUNTIME_SETTINGS.user = user_text
            RUNTIME_SETTINGS.sudo_password = sudo_password_var.get()
            status_var.set(f"Settings updated. Output folder: {output_path}")
            dialog.destroy()

        tk.Button(button_frame, text="Save", command=save_settings, width=10).pack(
            side=tk.LEFT,
            padx=(0, 8),
        )
        tk.Button(button_frame, text="Cancel", command=dialog.destroy, width=10).pack(
            side=tk.LEFT,
        )
        output_entry.focus_set()
        root.wait_window(dialog)

    file_menu.add_command(label=SOURCE_SSH_UAT, command=select_ssh_source)
    file_menu.add_cascade(label="Export options", menu=generated_menu)
    file_menu.add_separator()
    file_menu.add_command(label="Exit", command=root.destroy)
    menubar.add_cascade(label="File", menu=file_menu)
    menubar.add_cascade(label="Edit", menu=edit_menu)
    menubar.add_cascade(label="View", menu=view_menu)
    menubar.add_cascade(label="Tools", menu=tools_menu)

    def show_about() -> None:
        messagebox.showinfo(
            "About LogComparator",
            (
                "LogComparator\n"
                f"Version: {APP_VERSION}\n"
                f"Author: {APP_AUTHOR}"
            ),
            parent=root,
        )

    help_menu.add_command(
        label="About",
        command=show_about,
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
            clear_filters()
            clear_bank_and_transactions()
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

    def max_length_validator(max_length: int):
        return root.register(lambda value: len(value) <= max_length)

    stan_validate = max_length_validator(6)
    rrn_validate = max_length_validator(12)
    authcode_validate = max_length_validator(6)
    sequence_number_validate = max_length_validator(32)
    transaction_type_validate = max_length_validator(20)
    response_code_validate = max_length_validator(6)
    amount_validate = max_length_validator(8)

    fields = tk.Frame(root)
    fields.pack(fill=tk.X, padx=12, pady=(4, 4))

    def filter_group(label: str) -> tk.Frame:
        frame = tk.Frame(fields)
        frame.pack(side=tk.LEFT, padx=(0, 10), fill=tk.Y)
        tk.Label(frame, text=label, anchor="center").pack(fill=tk.X)
        return frame

    trans_uid_group = filter_group("TransUID")
    trans_uid_entry = tk.Entry(
        trans_uid_group,
        textvariable=trans_uid_var,
        width=18,
        state="disabled",
    )
    trans_uid_entry.pack(fill=tk.X)
    stan_group = filter_group("STAN")
    stan_entry = tk.Entry(
        stan_group,
        textvariable=stan_var,
        width=8,
        state="disabled",
        validate="key",
        validatecommand=(stan_validate, "%P"),
    )
    stan_entry.pack(fill=tk.X)
    rrn_group = filter_group("RRN")
    rrn_entry = tk.Entry(
        rrn_group,
        textvariable=rrn_var,
        width=14,
        state="disabled",
        validate="key",
        validatecommand=(rrn_validate, "%P"),
    )
    rrn_entry.pack(fill=tk.X)
    authcode_group = filter_group("AuthCode")
    authcode_entry = tk.Entry(
        authcode_group,
        textvariable=authcode_var,
        width=8,
        state="disabled",
        validate="key",
        validatecommand=(authcode_validate, "%P"),
    )
    authcode_entry.pack(fill=tk.X)
    sequence_number_group = filter_group("Sequence_Number")
    sequence_number_entry = tk.Entry(
        sequence_number_group,
        textvariable=sequence_number_var,
        width=16,
        state="disabled",
        validate="key",
        validatecommand=(sequence_number_validate, "%P"),
    )
    sequence_number_entry.pack(fill=tk.X)
    transaction_type_group = filter_group("TransactionType")
    transaction_type_entry = tk.Entry(
        transaction_type_group,
        textvariable=transaction_type_var,
        width=22,
        state="disabled",
        validate="key",
        validatecommand=(transaction_type_validate, "%P"),
    )
    transaction_type_entry.pack(fill=tk.X)
    tid_group = filter_group("TID")
    tid_entry = tk.Entry(
        tid_group,
        textvariable=tid_var,
        width=12,
        state="disabled",
    )
    tid_entry.pack(fill=tk.X)
    mid_group = filter_group("MID")
    mid_entry = tk.Entry(
        mid_group,
        textvariable=mid_var,
        width=12,
        state="disabled",
    )
    mid_entry.pack(fill=tk.X)
    amount_group = filter_group("AMT")
    amount_entry = tk.Entry(
        amount_group,
        textvariable=amount_var,
        width=10,
        state="disabled",
        validate="key",
        validatecommand=(amount_validate, "%P"),
    )
    amount_entry.pack(fill=tk.X)
    response_code_spdh_group = filter_group("RC_SPDH")
    response_code_spdh_entry = tk.Entry(
        response_code_spdh_group,
        textvariable=response_code_spdh_var,
        width=8,
        state="disabled",
        validate="key",
        validatecommand=(response_code_validate, "%P"),
    )
    response_code_spdh_entry.pack(fill=tk.X)
    response_code_iso_group = filter_group("RC_ISO")
    response_code_iso_entry = tk.Entry(
        response_code_iso_group,
        textvariable=response_code_iso_var,
        width=8,
        state="disabled",
        validate="key",
        validatecommand=(response_code_validate, "%P"),
    )
    response_code_iso_entry.pack(fill=tk.X)

    configurable_columns = (
        "transuid",
        "rrn",
        "stan",
        "authcode",
        "sequencenumber",
        "transactiontype",
        "tid",
        "mid",
        "amt",
        "responsecodespdh",
        "responsecodeiso",
    )
    filter_groups = {
        "transuid": trans_uid_group,
        "rrn": rrn_group,
        "stan": stan_group,
        "authcode": authcode_group,
        "sequencenumber": sequence_number_group,
        "transactiontype": transaction_type_group,
        "tid": tid_group,
        "mid": mid_group,
        "amt": amount_group,
        "responsecodespdh": response_code_spdh_group,
        "responsecodeiso": response_code_iso_group,
    }
    filter_variables = {
        "transuid": trans_uid_var,
        "rrn": rrn_var,
        "stan": stan_var,
        "authcode": authcode_var,
        "sequencenumber": sequence_number_var,
        "transactiontype": transaction_type_var,
        "tid": tid_var,
        "mid": mid_var,
        "amt": amount_var,
        "responsecodespdh": response_code_spdh_var,
        "responsecodeiso": response_code_iso_var,
    }
    column_visible_vars = {
        column: tk.BooleanVar(root, value=True) for column in configurable_columns
    }

    transaction_columns = (
        "datetime",
        "transuid",
        "rrn",
        "stan",
        "authcode",
        "sequencenumber",
        "transactiontype",
        "tid",
        "mid",
        "amt",
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
        "sequencenumber": "Sequence_Number",
        "transactiontype": "TransactionType",
        "tid": "TID",
        "mid": "MID",
        "amt": "AMT",
        "responsecodespdh": "RC_SPDH",
        "responsecodeiso": "RC_ISO",
    }
    column_widths = {
        "datetime": 170,
        "transuid": 230,
        "rrn": 130,
        "stan": 90,
        "authcode": 100,
        "sequencenumber": 140,
        "transactiontype": 170,
        "tid": 110,
        "mid": 110,
        "amt": 110,
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

    def visible_transaction_columns() -> tuple[str, ...]:
        return tuple(
            column
            for column in transaction_columns
            if column == "datetime" or column_visible_vars[column].get()
        )

    def apply_column_filter_visibility() -> None:
        for column in configurable_columns:
            group = filter_groups[column]
            if not column_visible_vars[column].get():
                filter_variables[column].set("")
            if column_visible_vars[column].get():
                group.pack_forget()
            elif group.winfo_ismapped():
                group.pack_forget()
        for column in configurable_columns:
            if column_visible_vars[column].get():
                filter_groups[column].pack(side=tk.LEFT, padx=(0, 10), fill=tk.Y)
        transaction_tree.configure(displaycolumns=visible_transaction_columns())
        autosize_transaction_columns()
        apply_transaction_filters()

    def autosize_transaction_columns() -> None:
        row_font = tkfont.nametofont("TkDefaultFont")
        padding = 28
        visible_items = transaction_tree.get_children("")
        displayed_columns = visible_transaction_columns()
        for column in displayed_columns:
            column_index = transaction_columns.index(column)
            width = heading_font.measure(column_labels[column]) + padding
            for item_id in visible_items:
                values = transaction_tree.item(item_id, "values")
                if column_index < len(values):
                    width = max(width, row_font.measure(str(values[column_index])) + padding)
            transaction_tree.column(
                column,
                width=max(width, 80),
                minwidth=80,
                stretch=False,
            )

    autosize_transaction_columns()
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
    x_scroll.grid(row=1, column=0, columnspan=2, sticky="ew")
    transaction_frame.rowconfigure(0, weight=1)
    transaction_frame.rowconfigure(1, weight=0)
    transaction_frame.columnconfigure(0, weight=1)

    def clear_transaction_list() -> None:
        transaction_tree.delete(*transaction_tree.get_children())
        autosize_transaction_columns()

    def selected_timezone_offset_hours() -> int:
        value = timezone_var.get().strip()
        if value == "UTC":
            return 0
        try:
            return int(value.replace("UTC", "", 1))
        except ValueError:
            return 0

    def display_values_for_timezone(values: tuple[str, ...]) -> tuple[str, ...]:
        if not values or not values[0]:
            return values
        try:
            utc_datetime = datetime.strptime(values[0], "%Y-%m-%d %H:%M:%S.%f")
        except ValueError:
            return values
        shifted_datetime = utc_datetime + timedelta(
            hours=selected_timezone_offset_hours()
        )
        displayed = list(values)
        displayed[0] = shifted_datetime.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        return tuple(displayed)

    def row_matches_filters(values: tuple[str, ...]) -> bool:
        filters = {
            "transuid": trans_uid_var.get().strip(),
            "rrn": rrn_var.get().strip(),
            "stan": stan_var.get().strip(),
            "authcode": authcode_var.get().strip(),
            "sequencenumber": sequence_number_var.get().strip(),
            "transactiontype": transaction_type_var.get().strip(),
            "tid": tid_var.get().strip(),
            "mid": mid_var.get().strip(),
            "amt": amount_var.get().strip(),
            "responsecodespdh": response_code_spdh_var.get().strip(),
            "responsecodeiso": response_code_iso_var.get().strip(),
        }
        value_by_column = dict(zip(transaction_columns, values))
        for column, filter_value in filters.items():
            if filter_value and filter_value.casefold() not in value_by_column[column].casefold():
                return False
        return True

    def apply_transaction_filters(*_args) -> int:
        clear_transaction_list()
        visible_count = 0
        for uid, values in transaction_rows:
            if row_matches_filters(values):
                transaction_tree.insert(
                    "",
                    tk.END,
                    iid=uid,
                    values=display_values_for_timezone(values),
                )
                visible_count += 1
        autosize_transaction_columns()
        if transaction_rows and visible_count == 0:
            status_var.set(
                f"Loaded transactions: {len(transaction_rows)}; visible after filters: 0"
            )
        elif transaction_rows:
            status_var.set(
                f"Loaded transactions: {len(transaction_rows)}; visible: {visible_count}"
            )
        return visible_count

    def show_column_filter_options() -> None:
        dialog = tk.Toplevel(root)
        dialog.title("Columns / Filters")
        dialog.transient(root)
        dialog.resizable(False, False)
        dialog.grab_set()

        container = tk.Frame(dialog, padx=14, pady=12)
        container.pack(fill=tk.BOTH, expand=True)
        for row_index, column in enumerate(configurable_columns):
            ttk.Checkbutton(
                container,
                text=column_labels[column],
                variable=column_visible_vars[column],
                command=apply_column_filter_visibility,
            ).grid(row=row_index, column=0, sticky="w", pady=2)

        button_bar = tk.Frame(container)
        button_bar.grid(row=len(configurable_columns), column=0, sticky="e", pady=(10, 0))
        tk.Button(button_bar, text="Close", command=dialog.destroy, width=10).pack()

        dialog.update_idletasks()
        x = root.winfo_rootx() + (root.winfo_width() - dialog.winfo_width()) // 2
        y = root.winfo_rooty() + (root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{max(x, 0)}+{max(y, 0)}")

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
            transactions = scan_transactions_for_list(
                audits,
                report_scan_progress,
            )
            transaction_scan_cache[scan_key] = transactions
        elif progress_callback:
            progress_callback(85.0, "Using cached transactions")
        if progress_callback:
            progress_callback(88.0, "Build transaction list")
        expected_ids = BANK_ACQUIRER_IDS.get(bank, set())
        matching = [
            transaction
            for transaction in transactions.values()
            if (
                transaction.acquirer_ids & expected_ids
                or any(
                    bank_audit_code_matches(bank, process_name)
                    for process_name in transaction.process_names
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
                select_identifier(transaction, "sequence_number"),
                transaction_type,
                select_first(transaction.tids),
                select_first(transaction.mids),
                select_amount_display(transaction),
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
        visible_count = apply_transaction_filters()
        selected_date_var.set(selected_date)
        if not rows:
            status_var.set("No matching transactions found for this bank/acquirer.")
        elif visible_count == 0:
            status_var.set(
                f"Loaded transactions: {len(rows)}; visible after filters: 0"
            )

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
            except Exception as exc:
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

    def on_bank_selected(event=None) -> None:
        update_bank_state()
        load_transaction_list(event)

    bank_combo.bind("<<ComboboxSelected>>", on_bank_selected)
    timezone_combo.bind("<<ComboboxSelected>>", apply_transaction_filters)
    for filter_var in (
        trans_uid_var,
        rrn_var,
        stan_var,
        authcode_var,
        sequence_number_var,
        transaction_type_var,
        tid_var,
        mid_var,
        amount_var,
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
            selection["sequence_number"],
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
        selection["sequence_number"] = sequence_number_var.get().strip()
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

    def select_all_transactions() -> None:
        transaction_tree.selection_set(transaction_tree.get_children(""))
        update_compare_state()

    def clear_transaction_selection() -> None:
        transaction_tree.selection_remove(transaction_tree.selection())
        update_compare_state()

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
    edit_menu.add_command(label="Clear filters", command=clear_filters)
    edit_menu.add_separator()
    edit_menu.add_command(label="Select all transactions", command=select_all_transactions)
    edit_menu.add_command(label="Clear selection", command=clear_transaction_selection)
    view_menu.add_command(label="Columns / Filters...", command=show_column_filter_options)
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



