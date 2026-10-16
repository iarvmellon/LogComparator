"""Primary LogComparator interface: NiceGUI, Quasar and local diff2html."""
from __future__ import annotations

import argparse
import asyncio
import copy
import inspect
import socket
import webbrowser
import urllib.request
import json
import io
import queue
import tempfile
import zipfile
import uuid
import time
from collections import OrderedDict
from urllib.parse import urlencode
from datetime import date, datetime, timedelta
from pathlib import Path

from nicegui import app, run, ui
from logcomparator_ui.diff_view import DiffView, register_assets

import log_core as core
from gui_services import download_uat_sources, list_remote_logs
from web_services import (BackgroundAudits, COLUMNS, CORE_LOCK, comparison_diff, export_logs,
                          filter_rows, load_logs, publish_exports, with_settings)
from web_services import inspect_local_sources, source_signature, SourceWatcher

WORKSPACE = tempfile.TemporaryDirectory(prefix='LogComparator-web-')
PREVIEW_SOURCES = OrderedDict()
WEB_OUTPUT = core.DEFAULT_OUTPUT
register_assets()


@app.get('/health')
def health():
    return {'app': 'LogComparator', 'ui': 'web', 'version': core.APP_BUILD_DESCRIBE}


@ui.page('/transaction/{source_id}', title=f'LogComparator {core.APP_BUILD_DESCRIBE}')
async def transaction_page(source_id: str, uid: str):
    entry = PREVIEW_SOURCES.get(source_id)
    if entry is None:
        ui.label('This transaction link has expired. Reload the source in LogComparator.')
        return
    loaded, settings, destination = entry
    ui.label(f'LogComparator - {uid}').classes('text-lg')
    try:
        output = Path(tempfile.mkdtemp(prefix='preview-', dir=WORKSPACE.name))
        paths = await run.io_bound(export_logs, loaded, [uid], output, **dict(settings))
        await run.io_bound(publish_exports, paths, loaded, destination)
        text = await run.io_bound(paths[0].read_text, encoding='utf-8', errors='replace')
        ui.button('Download log', on_click=lambda: ui.download.file(paths[0]))
        ui.label(text).style('white-space:pre; font-family:Consolas,monospace; font-size:13px')
    except Exception as error:
        ui.label(f'Could not open transaction: {error}')

CSS = '''
body { background:#f0f0f0; color:#151515; font-family:Arial,sans-serif; }
.q-page { padding:0; }
.nicegui-content { padding:8px 12px; gap:12px; }
.menubar { background:#fafafa; border-bottom:1px solid #c4c4c4; gap:0; width:100%; }
.menubar .q-btn { min-height:26px; padding:0 10px; font-weight:400; }
.panel { border:1px solid #aaa; border-radius:0; padding:8px 10px; min-width:0; }
.panel legend { padding:0 6px; font-size:13px; }
.toolbar { gap:14px; align-items:center; width:100%; flex-wrap:wrap; }
.q-field--outlined .q-field__control { border-radius:0; background:white; }
.q-field--dense .q-field__control, .q-field--dense .q-field__marginal { height:32px; }
.q-btn { border-radius:0; text-transform:none; }
.q-table__container { border:1px solid #aaa; border-radius:0; width:100%; }
.q-table th { font-weight:bold; background:white; }
.q-table th, .q-table td { font-size:var(--log-font,13px); padding:3px 8px!important; height:auto!important; line-height:1.4; white-space:nowrap; }
.q-table tbody tr.problem { background:#ff9999; }
.q-table tbody tr.warning { background:#fff2b3; }
.q-table tbody tr.approved { background:#c8f7c5; }
.q-table tbody tr.selected { background:#0078d7!important; color:white; }
.log-table .q-table__middle { max-height:calc(100vh - 380px); min-height:240px; }
.filter-input { width:120px; flex:1 0 95px; }
.problem-filter { min-width:260px; flex:2 0 260px; }
.q-table tr.selected a { color:white; }
.diff2html-view { max-height:72vh; overflow:auto; width:100%; }
.diff2html-view .d2h-file-side-diff { overflow-x:auto; }
.diff2html-view .d2h-code-line, .diff2html-view .d2h-code-side-line { font-family:Consolas,monospace; }
.status { font-size:13px; }
.log-text { white-space:pre; overflow:auto; font-family:Consolas,monospace; font-size:13px; max-height:70vh; margin:0; }
@media(max-width:900px) { .log-table .q-table__middle { max-height:65vh; } }
'''


def download_uat(selected_date: str, bank: str, progress) -> Path:
    # Share the same parser/cache lock with local loading and exports.
    with CORE_LOCK:
        return download_uat_sources(selected_date, bank, core.ACTIVE_RUNTIME_SETTINGS.get().output.parent, progress)


@ui.page('/', title=f'LogComparator {core.APP_BUILD_DESCRIBE}')
def index():
    ui.add_css(CSS)
    loaded = None
    source_day = ''
    audit_source_folder = core.LOCAL_AUDIT_DIR
    busy = False
    ssh_picker = None
    background_job = None
    pending_bank = None
    preview_id = None
    font_size = 13
    previous_offset = 0
    last_source_signature = None
    source_watcher = None
    last_live_check = 0
    events = queue.Queue()
    filters = {}
    session_settings = core.RuntimeSettings(output=WEB_OUTPUT)
    operation_lock = asyncio.Lock()

    def progress(current, total, text):
        events.put((current / total if total else 0, text))

    def poll_progress():
        latest = None
        while not events.empty():
            latest = events.get_nowait()
        if latest:
            progress_bar.set_value(latest[0])
            status.set_text(latest[1])
        if background_job is not None:
            while not background_job.messages.empty():
                background_status.set_text(background_job.messages.get_nowait())
            if pending_bank and background_job.done.is_set() and not busy:
                asyncio.create_task(change_bank())

    def offset():
        return int(timezone.value.replace('UTC', '') or 0)

    def change_timezone():
        nonlocal previous_offset
        difference = offset() - previous_offset
        previous_offset = offset()
        for control in (from_datetime, to_datetime):
            if control.value:
                try:
                    value = datetime.strptime(control.value, '%Y-%m-%d %H:%M:%S') + timedelta(hours=difference)
                    control.set_value(value.strftime('%Y-%m-%d %H:%M:%S'))
                except ValueError:
                    pass
        refresh()

    def refresh():
        if loaded is None:
            return
        try:
            try:
                minimum = datetime.strptime(from_datetime.value, '%Y-%m-%d %H:%M:%S').isoformat(sep=' ', timespec='seconds') if from_datetime.value else ''
                maximum = datetime.strptime(to_datetime.value, '%Y-%m-%d %H:%M:%S').isoformat(sep=' ', timespec='seconds') if to_datetime.value else ''
            except ValueError:
                raise ValueError('Use YYYY-MM-DD HH:MM:SS in From and To (24-hour time).') from None
            if minimum and maximum and minimum > maximum:
                raise ValueError('From must be before To.')
            table.rows = filter_rows(loaded.rows, {key: control.value or '' for key, control in filters.items()}, minimum, maximum, offset())
            if preview_id:
                for row in table.rows:
                    row['preview_url'] = f'/transaction/{preview_id}?' + urlencode({'uid': row['transuid']})
            selected_uids = {row['transuid'] for row in table.selected}
            table.selected = [row for row in table.rows if row['transuid'] in selected_uids]
            table.update()
            update_actions()
            status.set_text(f'Loaded transactions: {len(loaded.rows)}; visible: {len(table.rows)}; selected: {len(table.selected)}')
        except ValueError as error:
            ui.notify(str(error), type='warning')

    async def perform(callback, quiet=False):
        nonlocal busy
        if busy:
            ui.notify('Wait for the current operation to finish.', type='info')
            return
        async with operation_lock:
            busy = True
            bank.disable()
            update_actions()
            progress_bar.set_visibility(True)
            try:
                await callback()
            except Exception as error:
                if quiet:
                    live_status.set_text(f'Live update delayed: {error}. Retrying on the next check.')
                else:
                    status.set_text(str(error))
                    ui.notify(str(error), type='negative', close_button=True, timeout=10000)
            finally:
                poll_progress()
                busy = False
                bank.enable()
                update_actions()
                progress_bar.set_visibility(False)

    async def change_bank():
        nonlocal pending_bank
        if loaded is not None and bank.value == loaded.bank:
            pending_bank = None
            return
        if busy or loaded is None:
            return
        if bank.value not in core.available_banks_for_folder(loaded.audit_folder or loaded.folder):
            if background_job and not background_job.done.is_set():
                pending_bank = bank.value
                background_status.set_text(f'Waiting for {bank.value} audits to finish downloading...')
                return
            pending_bank = None
            status.set_text(f'No audit files available for {bank.value} on {source_day}.')
            bank.set_value(loaded.bank)
            return
        pending_bank = None
        await load_source()

    def stop_watching():
        nonlocal source_watcher
        if source_watcher:
            source_watcher.close()
            source_watcher = None

    def configure_live():
        nonlocal source_watcher
        stop_watching()
        if live_enabled.value and loaded:
            source_watcher = SourceWatcher(loaded.folder, loaded.audit_folder or loaded.folder)
            live_status.set_text('Live — watching source files')
        else:
            live_status.set_text('Live paused' if loaded else 'Load files to start live updates')

    async def live_tick():
        nonlocal last_live_check
        if busy or loaded is None or not live_enabled.value or source_watcher is None:
            return
        # Events drive immediate updates; metadata polling also covers missed
        # notifications on network shares and changes during a failed read.
        if not source_watcher.changed.is_set() and time.monotonic() - last_live_check < 5:
            return
        source_watcher.changed.clear()
        last_live_check = time.monotonic()
        await load_source(live=True)
        if source_watcher and source_watcher.error:
            live_status.set_text(f'Filesystem watcher unavailable; checking every 5 s: {source_watcher.error}')

    async def load_source(remote=False, download_bank=None, live=False):
        if live and (busy or loaded is None or not live_enabled.value):
            return
        async def action():
            nonlocal loaded, source_day, background_job, pending_bank, preview_id, audit_source_folder, last_source_signature
            bank_value = bank.value
            date_value = source_day
            folder_value = folder.value or ''
            if not bank_value:
                raise ValueError('Select a bank/acquirer.')
            if remote:
                if not core.ENABLE_SSH:
                    raise ValueError('SSH/SCP is disabled; use the local filesystem import.')
                if background_job:
                    background_job.cancel_event.set()
                    background_job = None
                pending_bank = None
                try:
                    datetime.strptime(date_value, '%Y-%m-%d')
                except ValueError:
                    raise ValueError('Select a valid SSH date before downloading.') from None
                source = await run.io_bound(with_settings, copy.copy(session_settings), download_uat, date_value, download_bank or bank_value, progress)
                if download_bank == 'All':
                    available = core.available_banks_for_folder(source)
                    if available and bank_value not in available:
                        bank_value = available[0]
                        bank.set_value(bank_value)
                folder.set_value(str(source))
            else:
                if not folder_value.strip():
                    raise ValueError('Enter a log folder or use File > Import.')
                source = Path(folder_value)
                if background_job and source.resolve() != background_job.folder:
                    background_job.cancel_event.set()
                    background_job = None
                    pending_bank = None
                    background_status.set_text('')
            signature = await run.io_bound(source_signature, source, None if remote else audit_source_folder, date_value, bank_value)
            if live and signature == last_source_signature:
                live_status.set_text(f'Checked {datetime.now():%H:%M:%S} — no changes')
                return
            status.set_text('Loading source files…')
            result = await run.io_bound(load_logs, source, bank_value, date_value, progress,
                                       audit_folder=None if remote else audit_source_folder)
            loaded = result
            audit_source_folder = result.audit_folder
            audit_path.set_value(str(result.audit_folder))
            if not live:
                preview_id = uuid.uuid4().hex
            PREVIEW_SOURCES[preview_id] = (result, options(), session_settings.output)
            while len(PREVIEW_SOURCES) > 32:
                PREVIEW_SOURCES.popitem(last=False)
            source_day = result.selected_date
            selected_date.set_text(f'Selected date:  {result.selected_date}  |  {result.bank}')
            if not live:
                for control, clock in ((from_datetime, '00:00:00'), (to_datetime, '23:59:59')):
                    value = datetime.fromisoformat(f'{result.selected_date} {clock}') + timedelta(hours=offset())
                    control.set_value(value.strftime('%Y-%m-%d %H:%M:%S'))
                table.selected = []
            # Capture BEFORE parsing so appends during the scan trigger another pass.
            last_source_signature = signature if date_value else None
            poll_progress()
            refresh()
            live_status.set_text(f'Updated {datetime.now():%H:%M:%S}')
            if not live:
                configure_live()
            if remote and download_bank != 'All':
                background_status.set_text('Downloading audits for all banks in background...')
                background_job = BackgroundAudits(result.selected_date, result.folder, copy.copy(session_settings))
            elif download_bank == 'All':
                background_status.set_text('All available banks downloaded.')
        await perform(action, quiet=live)

    def options():
        return dict(protocol_choice=protocol.value, include_byte_data=byte_data.value,
                    include_internal=internal.value, include_tango_to_network=outbound.value,
                    include_network_to_tango=inbound.value)

    def update_actions():
        open_button.set_enabled(bool(table.selected) and not busy)
        compare_button.set_enabled(len(table.selected) == 2 and not busy)
        export_button.set_enabled(bool(table.rows) and not busy)
        if len(table.selected) == 1:
            open_button.props['href'] = table.selected[0]['preview_url']
            open_button.props['target'] = '_blank'
        else:
            open_button.props.pop('href', None)

    async def toolbar_open():
        # One selected log is a real browser link, preserving the click gesture.
        update_preview_options()
        if len(table.selected) > 1:
            await export_action('open')

    def selection_changed():
        update_actions()
        status.set_text(f'Loaded transactions: {len(loaded.rows) if loaded else 0}; visible: {len(table.rows)}; selected: {len(table.selected)}')

    def update_preview_options():
        if preview_id in PREVIEW_SOURCES:
            PREVIEW_SOURCES[preview_id] = (loaded, options(), session_settings.output)

    async def export_action(mode='download'):
        async def action():
            if loaded is None:
                raise ValueError('Load a source folder first.')
            selection = list(table.selected)
            if mode == 'compare' and len(selection) != 2:
                raise ValueError('Select exactly two transactions to compare.')
            if mode == 'open' and not selection:
                raise ValueError('Select one or more transactions to open.')
            rows = selection or list(table.rows)
            if mode == 'open':
                update_preview_options()
                for row in rows:
                    ui.navigate.to(row['preview_url'], new_tab=True)
                with ui.dialog() as links, ui.card():
                    ui.label('Open selected logs').classes('text-lg')
                    for row in rows:
                        ui.link(row['transuid'], row['preview_url'], new_tab=True)
                    ui.button('Close', on_click=links.close)
                links.open()
                return
            output = Path(tempfile.mkdtemp(prefix='export-', dir=WORKSPACE.name))
            status.set_text(f'Exporting {len(rows)} transaction(s)…')
            paths = await run.io_bound(export_logs, loaded, [row['transuid'] for row in rows], output, **options())
            saved_to = await run.io_bound(publish_exports, paths, loaded, session_settings.output)
            if mode == 'download':
                if len(paths) == 1:
                    ui.download.file(paths[0])
                else:
                    def archive():
                        buffer = io.BytesIO()
                        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as bundle:
                            for path in paths:
                                bundle.write(path, path.name)
                        return buffer.getvalue()
                    ui.download.content(await run.io_bound(archive), f'LogComparator-{loaded.selected_date}.zip')
            else:
                texts = await run.io_bound(lambda: [path.read_text(encoding='utf-8', errors='replace') for path in paths])
                with ui.dialog() as dialog, ui.card().classes('w-full max-w-[95vw]'):
                    with ui.row().classes('w-full items-center justify-between'):
                        ui.label('Compare transactions - diff2html').classes('text-lg')
                        ui.button('Close', on_click=dialog.close).props('flat')
                    ui.label(f'{paths[0].name}  |  {paths[1].name}').classes('text-sm')
                    diff = comparison_diff(texts[0], texts[1], paths[0].name, paths[1].name)
                    if diff:
                        with ui.row():
                            ui.button('Previous difference', on_click=lambda: viewer.previous_difference()).props('outline dense')
                            ui.button('Next difference', on_click=lambda: viewer.next_difference()).props('outline dense')
                            ui.button('Download diff', on_click=lambda: ui.download.content(diff, 'comparison.diff')).props('outline dense')
                        viewer = DiffView(diff).mark('diff2html-comparison')
                    else:
                        ui.label('The exported logs are identical.')
                dialog.open()
            status.set_text(f'Exported {len(paths)} transaction(s). Saved to {saved_to}')
        await perform(action)

    def clear_filters():
        for control in filters.values():
            control.set_value('')
        refresh()

    def zoom(delta):
        nonlocal font_size
        font_size = min(32, max(9, font_size + delta))
        table.style(f'--log-font:{font_size}px')

    def show_columns():
        with ui.dialog() as dialog, ui.card():
            ui.label('Columns / Filters').classes('text-lg')
            for field, label in COLUMNS:
                if field == 'possibleproblem':
                    continue
                ui.checkbox(label, value=field in table.props['visible-columns'],
                            on_change=lambda event, key=field: toggle_column(key, event.value))
            ui.button('Close', on_click=dialog.close)
        dialog.open()

    def toggle_column(field, visible):
        columns = set(table.props['visible-columns'])
        columns.add(field) if visible else columns.discard(field)
        table.props['visible-columns'] = [key for key, _ in COLUMNS if key in columns]
        table.update()
        if field in filters:
            filters[field].set_visibility(visible)
            if not visible:
                filters[field].set_value('')

    async def browse_folder(initial, on_choose):
        with ui.dialog() as browser, ui.card().classes('w-[700px] max-w-[95vw]'):
            ui.label('Choose a folder on the server').classes('text-lg')
            location = ui.input('Folder', value=str(initial)).props('outlined dense').classes('w-full')
            message = ui.label().classes('text-sm')
            listing = ui.column().classes('w-full max-h-80 overflow-auto gap-0')

            async def show(path=None):
                try:
                    target = Path(path or location.value).expanduser().resolve()
                    directories = await run.io_bound(lambda: sorted((p for p in target.iterdir() if p.is_dir()), key=lambda p: p.name.casefold()))
                    location.set_value(str(target))
                    listing.clear()
                    with listing:
                        if target.parent != target:
                            ui.button('.. (parent folder)', on_click=lambda p=target.parent: show(p)).props('flat dense')
                        for directory in directories:
                            ui.button(directory.name, on_click=lambda p=directory: show(p)).props('flat dense no-caps')
                    message.set_text(f'{len(directories)} folders')
                except (OSError, ValueError) as error:
                    message.set_text(str(error))

            async def select():
                chosen = Path(location.value).expanduser().resolve()
                if not chosen.is_dir():
                    message.set_text('Choose an existing folder.')
                    return
                result = on_choose(str(chosen))
                if inspect.isawaitable(result):
                    await result
                browser.close()

            with ui.row():
                ui.button('Go', on_click=lambda: show())
                ui.button('Choose this folder', on_click=select)
                ui.button('Cancel', on_click=browser.close).props('flat')
        browser.open()
        await show()

    async def import_dialog():
        with ui.dialog() as dialog, ui.card().classes('w-[700px] max-w-[95vw]'):
            ui.label('Import local log folder').classes('text-lg')
            ui.label('Choose a folder on the computer running LogComparator.').classes('text-sm')
            path_input = ui.input('Folder path', value=folder.value or str(core.DEFAULT_IMPORT)).props('outlined dense').classes('w-full')
            ui.button('Browse folders', on_click=lambda: browse_folder(path_input.value or core.DEFAULT_IMPORT, path_input.set_value)).props('outline dense')
            audit_default = audit_source_folder if core.LOCAL_AUDIT_DIR or (audit_source_folder and str(audit_source_folder) != folder.value) else None
            audit_input = ui.input('Audit folder (empty = same folder)', value=str(audit_default or '')).props('outlined dense').classes('w-full')
            ui.button('Browse audit folder', on_click=lambda: browse_folder(audit_input.value or path_input.value, audit_input.set_value)).props('outline dense')
            local_date = ui.select([], label='Log date (auto for one date)', clearable=True).props('outlined dense').classes('w-full')
            import_bank = ui.select(list(core.BANK_AUDIT_CODES), label='Import Bank/Acquirer', value=bank.value).props('outlined dense').classes('w-full')

            async def inspect_folders():
                try:
                    dates, banks = await run.io_bound(inspect_local_sources, Path(path_input.value), Path(audit_input.value) if audit_input.value else None)
                    local_date.set_options(dates)
                    if dates:
                        local_date.set_value(source_day if source_day in dates else dates[-1])
                    if banks:
                        import_bank.set_options(banks)
                        if import_bank.value not in banks:
                            import_bank.set_value(banks[0])
                    ui.notify(f'{len(dates)} log dates; {len(banks)} banks available.', type='info')
                except (OSError, ValueError) as error:
                    ui.notify(str(error), type='negative')
            ui.button('Inspect dates and banks', on_click=inspect_folders)
            async def choose_path():
                nonlocal source_day, audit_source_folder
                folder.set_value(path_input.value)
                source_day = local_date.value or ''
                audit_source_folder = Path(audit_input.value) if audit_input.value else None
                bank.set_value(import_bank.value)
                clear_filters()
                dialog.close()
                await load_source()
            ui.button('Load folder', on_click=choose_path)
            ui.button('Cancel', on_click=dialog.close).props('flat')
        dialog.open()
        if Path(path_input.value).is_dir():
            await inspect_folders()

    def settings_dialog():
        with ui.dialog() as dialog, ui.card().classes('w-[620px] max-w-[95vw]'):
            ui.label('Settings').classes('text-lg')
            output_input = ui.input('Output folder', value=str(session_settings.output)).props('outlined dense').classes('w-full')
            ui.button('Browse output folder', on_click=lambda: browse_folder(output_input.value, output_input.set_value)).props('outline dense')
            user_input = password_input = None
            if core.ENABLE_SSH:
                user_input = ui.input('SSH user', value=session_settings.user).props('outlined dense').classes('w-full')
                password_input = ui.input('Sudo password (leave empty to keep current)', password=True).props('outlined dense').classes('w-full')
            def save():
                if not (output_input.value or '').strip() or (user_input is not None and not (user_input.value or '').strip()):
                    ui.notify('Fill in the required settings.', type='warning')
                    return
                session_settings.output = Path(output_input.value).expanduser().resolve()
                if user_input is not None:
                    session_settings.user = user_input.value.strip()
                if password_input is not None and password_input.value:
                    session_settings.sudo_password = password_input.value
                update_preview_options()
                status.set_text(f'Settings updated. Output folder: {session_settings.output}')
                dialog.close()
            ui.button('Save settings', on_click=save)
            ui.button('Cancel', on_click=dialog.close).props('flat')
        dialog.open()

    def export_options_dialog():
        with ui.dialog() as dialog, ui.card():
            ui.label('Export options').classes('text-lg')
            ui.radio(list(core.PROTOCOL_CHOICES)).props('inline').bind_value(protocol)
            ui.checkbox('Include Byte/Data').bind_value(byte_data)
            ui.checkbox('Tango Internal').bind_value(internal)
            ui.checkbox('Tango to Network').bind_value(outbound)
            ui.checkbox('Network to Tango').bind_value(inbound)
            ui.button('Close', on_click=dialog.close)
        dialog.open()

    def close_workspace():
        nonlocal loaded, background_job, pending_bank, preview_id, source_day, audit_source_folder
        if background_job:
            background_job.cancel_event.set()
        loaded = background_job = pending_bank = preview_id = None
        source_day = ''
        table.rows = []
        stop_watching()
        live_status.set_text('')
        table.selected = []
        table.update()
        update_actions()
        folder.set_value('')
        audit_source_folder = core.LOCAL_AUDIT_DIR
        audit_path.set_value(str(core.LOCAL_AUDIT_DIR or ''))
        from_datetime.set_value('')
        to_datetime.set_value('')
        clear_filters()
        background_status.set_text('')
        selected_date.set_text('Selected date: Not selected')
        status.set_text('Workspace closed. Use File to load another source.')

    def about():
        with ui.dialog() as dialog, ui.card():
            ui.label('About LogComparator').classes('text-lg')
            ui.label(f'Version: {core.APP_BUILD_DESCRIBE}')
            ui.label(f'Release: {core.APP_VERSION} | Commit: {core.APP_GIT_HASH}')
            ui.label(f'Author: {core.APP_AUTHOR}')
            ui.label('NiceGUI / Quasar UI / diff2html. All browser assets are served locally.')
            ui.button('Close', on_click=dialog.close)
        dialog.open()

    async def ssh_dialog():
        nonlocal ssh_picker
        if busy:
            ui.notify('Wait for the current operation to finish.', type='info')
            return
        if ssh_picker is not None:
            ssh_picker.delete()
        available = {}
        ready = False
        with ui.dialog() as dialog, ui.card():
            ui.label('SSH/SCP (UAT) — Select date and bank').classes('text-lg')
            availability = ui.label('Loading available dates from UAT…').classes('text-sm')
            files = ui.label().classes('text-sm whitespace-pre-wrap max-w-[600px]')

            def show_files():
                paths = available.get(remote_date.value, [])
                files.set_text('Files on UAT:\n' + '\n'.join(core.any_path_name(path) for path in paths) if paths else '')

            remote_date = ui.input('SSH date', value=source_day or date.today().isoformat(), on_change=show_files).props('outlined dense type=date readonly')
            calendar = ui.date(value=remote_date.value).bind_value(remote_date)
            calendar.props['options'] = []
            calendar.disable()
            date_list = ui.select([], label='Available dates').props('outlined dense').classes('w-full').bind_value(remote_date)
            date_list.disable()
            remote_bank = ui.select(['All'] + list(core.BANK_AUDIT_CODES), label='SSH Bank/Acquirer', value=bank.value).props('outlined dense').classes('w-full')

            async def confirm():
                nonlocal source_day
                try:
                    datetime.strptime(remote_date.value or '', '%Y-%m-%d')
                except ValueError:
                    ui.notify('Select a valid SSH date before downloading.', type='warning')
                    return
                if not ready or remote_date.value not in available:
                    ui.notify('No Tango log files are available for this date.', type='warning')
                    return
                if remote_bank.value != 'All' and remote_bank.value not in core.BANK_AUDIT_CODES:
                    ui.notify('Select a bank/acquirer.', type='warning')
                    return
                source_day = remote_date.value
                if remote_bank.value != 'All':
                    bank.set_value(remote_bank.value)
                dialog.close()
                clear_filters()
                await load_source(remote=True, download_bank=remote_bank.value)

            with ui.row():
                download_button = ui.button('Download and load', on_click=confirm)
                download_button.disable()
                retry_button = ui.button('Refresh dates', on_click=lambda: refresh_dates()).props('flat')
                ui.button('Cancel', on_click=dialog.close).props('flat')

            async def refresh_dates():
                nonlocal ready
                ready = False
                download_button.disable()
                calendar.disable()
                date_list.disable()
                retry_button.disable()
                availability.set_text('Loading available dates from UAT…')
                files.set_text('')
                try:
                    paths = await run.io_bound(with_settings, copy.copy(session_settings), list_remote_logs)
                    if dialog.is_deleted or ssh_picker is not dialog:
                        return
                    available.clear()
                    for path in paths:
                        day = core.parse_log_date(core.any_path_name(path))
                        if day:
                            available.setdefault(day, []).append(path)
                    days = sorted(available)
                    marked_days = [day.replace('-', '/') for day in days]
                    calendar.props['options'] = marked_days
                    calendar.props['events'] = marked_days
                    calendar.props['event-color'] = 'green'
                    date_list.set_options(days)
                    if not days:
                        availability.set_text('No dated Tango log files found on UAT. Use Refresh dates to check again.')
                        remote_date.set_value('')
                    else:
                        selected = remote_date.value if remote_date.value in available else days[-1]
                        remote_date.set_value(selected)
                        calendar.props['default-year-month'] = selected[:7].replace('-', '/')
                        calendar.enable()
                        date_list.enable()
                        ready = True
                        download_button.enable()
                        availability.set_text(f'{len(days)} available dates. Green dots mark existing logs; other dates are disabled.')
                    calendar.update()
                    show_files()
                except Exception as error:
                    if not dialog.is_deleted:
                        availability.set_text(f'Could not list UAT logs: {error}. Use Refresh dates to retry.')
                finally:
                    if not dialog.is_deleted:
                        retry_button.enable()
        ssh_picker = dialog
        dialog.open()
        await refresh_dates()

    with ui.row().classes('menubar'):
        for label in ('File', 'Edit', 'View', 'Tools', 'Help'):
            with ui.button(label).props('flat dense'):
                with ui.menu():
                    if label == 'File':
                        ui.menu_item('Import…', on_click=import_dialog).mark('import-menu')
                        if core.ENABLE_SSH:
                            ui.menu_item('SSH/SCP (UAT)', on_click=ssh_dialog).mark('ssh-menu')
                        ui.menu_item('Open', on_click=lambda: export_action('open'))
                        ui.menu_item('Export', on_click=export_action)
                        ui.menu_item('Settings', on_click=settings_dialog).mark('settings-menu')
                        ui.menu_item('Close workspace', on_click=close_workspace).mark('close-workspace')
                    elif label == 'Edit':
                        ui.menu_item('Clear filters', on_click=clear_filters)
                        ui.menu_item('Select all visible', on_click=lambda: (setattr(table, 'selected', list(table.rows)), table.update(), selection_changed()))
                        ui.menu_item('Clear selection', on_click=lambda: (setattr(table, 'selected', []), table.update(), selection_changed()))
                    elif label == 'View':
                        ui.menu_item('Columns / Filters…', on_click=show_columns)
                        ui.menu_item('Increase font size', on_click=lambda: zoom(1))
                        ui.menu_item('Decrease font size', on_click=lambda: zoom(-1))
                    elif label == 'Tools':
                        ui.menu_item('Export options', on_click=export_options_dialog).mark('export-options-menu')
                        ui.menu_item('Open', on_click=lambda: export_action('open'))
                        ui.menu_item('Export', on_click=export_action)
                        ui.menu_item('Compare', on_click=lambda: export_action('compare'))
                    else:
                        ui.menu_item('About', on_click=about)

    def panel(title):
        fieldset = ui.element('fieldset').classes('panel')
        with fieldset:
            with ui.element('legend'):
                ui.label(title)
        return fieldset

    with ui.row().classes('toolbar'):
        with panel('Generated files'):
            protocol = ui.radio(list(core.PROTOCOL_CHOICES), value=core.PROTOCOL_CHOICES[0]).props('inline dense')
        with panel('Byte/Data'):
            byte_data = ui.checkbox('Include', value=False).props('dense')
        with panel('Audit blocks'), ui.row().classes('gap-3'):
            internal = ui.checkbox('Tango Internal', value=False).props('dense')
            outbound = ui.checkbox('Tango→Network', value=True).props('dense')
            inbound = ui.checkbox('Network→Tango', value=True).props('dense')
        selected_date = ui.label('Selected date:  Not selected').classes('text-sm')
        open_button = ui.button('Open', on_click=toolbar_open).props('outline dense').classes('w-24')
        export_button = ui.button('Export', on_click=export_action).props('outline dense').classes('w-24')
        compare_button = ui.button('Compare', on_click=lambda: export_action('compare')).props('outline dense').classes('w-24')

    def datetime_picker(label, default_time):
        async def open_picker():
            current = control.value or f'{source_day or date.today().isoformat()} {default_time}'
            with ui.dialog() as picker, ui.card():
                ui.label(f'{label} - Date and time').classes('text-lg')
                with ui.row().classes('items-start gap-4'):
                    day = ui.date(value=current[:10]).mark(f'{label}-date')
                    clock = ui.time(value=current[11:], mask='HH:mm:ss').props('format24h with-seconds').mark(f'{label}-time')

                def apply():
                    value = f'{day.value} {clock.value}'
                    try:
                        parsed = datetime.fromisoformat(value)
                    except (ValueError, TypeError):
                        ui.notify('Select a date and a valid 24-hour time.', type='warning')
                        return
                    control.set_value(parsed.strftime('%Y-%m-%d %H:%M:%S'))
                    picker.close()

                with ui.row():
                    ui.button('Apply', on_click=apply).mark(f'{label}-apply')
                    ui.button('Cancel', on_click=picker.close)
            picker.open()

        control = ui.input(label, on_change=refresh).props('outlined dense readonly placeholder="YYYY-MM-DD HH:MM:SS"').classes('w-64')
        control.on('click', open_picker)
        with control.add_slot('append'):
            ui.button(icon='event').props('flat dense round').on('click.stop', open_picker).mark(f'{label}-picker')
        return control

    with ui.row().classes('toolbar items-start'):
        with panel('Data').classes('grow'), ui.row().classes('items-center gap-3'):
            folder = ui.input('Log folder', value='' if core.ENABLE_SSH else str(core.DEFAULT_IMPORT), placeholder=str(core.DEFAULT_IMPORT)).props('outlined dense readonly').classes('w-80 grow')
            audit_path = ui.input('Audit folder', value=str(core.LOCAL_AUDIT_DIR or '')).props('outlined dense readonly').classes('w-80 grow')
            bank = ui.select(list(core.BANK_AUDIT_CODES), label='Bank/Acquirer', value=next(iter(core.BANK_AUDIT_CODES)), on_change=change_bank).props('outlined dense').classes('w-48')
            live_enabled = ui.checkbox('Live update', value=False, on_change=configure_live).props('dense').mark('live-update')
            live_status = ui.label().classes('status').mark('live-status')
        with panel('Time range'), ui.row().classes('items-center gap-2'):
            from_datetime = datetime_picker('From', '00:00:00')
            to_datetime = datetime_picker('To', '23:59:59')
            timezone = ui.select([f'UTC{i:+d}' if i else 'UTC' for i in range(-3, 4)], value='UTC', label='Timezone', on_change=change_timezone).props('outlined dense').classes('w-28')

    with panel('Filters').classes('w-full'), ui.row().classes('w-full gap-3'):
        filters['possibleproblem'] = ui.input('Possible problem', on_change=refresh).props('outlined dense debounce=350 clearable').classes('problem-filter').mark('possible-problem-filter')
        for key, label in COLUMNS:
            if key in ('datetime', 'possibleproblem'):
                continue
            filters[key] = ui.input(label, on_change=refresh).props('outlined dense debounce=350').classes('filter-input')

    table = ui.table(columns=[dict(name=key, label=label, field=key, align='left', sortable=True) for key, label in COLUMNS],
                     rows=[], row_key='transuid', selection='multiple', pagination=100,
                     on_select=selection_changed)
    table.classes('log-table').props('dense flat bordered separator=cell virtual-scroll')
    table.props['visible-columns'] = [key for key, _ in COLUMNS]
    table.add_slot('body', '''
        <q-tr :props="props" :class="[props.row.severity, {selected: props.selected}]" @click="props.selected = !props.selected" @dblclick="event => { const a = event.currentTarget.ownerDocument.createElement('a'); a.href = props.row.preview_url; a.target = '_blank'; a.rel = 'noopener'; a.click(); }">
          <q-td auto-width @click.stop><q-checkbox dense v-model="props.selected" /></q-td>
          <q-td v-for="col in props.cols" :key="col.name" :props="props"><a v-if="col.name === 'transuid'" :href="props.row.preview_url" target="_blank" rel="noopener" @click.stop>{{ col.value }}</a><span v-else>{{ col.value }}</span></q-td>
          <q-menu context-menu touch-position><q-list style="min-width:140px">
            <q-item v-for="action in ['Open', 'Export', 'Compare']" :key="action" clickable v-close-popup @click="$parent.$emit('context-action', {uid:props.row.transuid, action:action})"><q-item-section>{{ action }}</q-item-section></q-item>
          </q-list></q-menu>
        </q-tr>''')

    async def context_action(event):
        uid = event.args.get('uid')
        row = next((row for row in table.rows if row['transuid'] == uid), None)
        if row is None:
            return
        if not any(selected['transuid'] == uid for selected in table.selected):
            table.selected = [row]
            table.update()
        await export_action({'Open': 'open', 'Export': 'download', 'Compare': 'compare'}.get(event.args.get('action'), 'open'))
    table.on('context-action', context_action)
    with ui.row().classes('w-full items-center justify-between'):
        status = ui.label('Use File > Import to load logs.' if not core.ENABLE_SSH else 'Use File > Import or File > SSH/SCP (UAT) to load logs.').classes('status')
        ui.label(f'LogComparator {core.APP_BUILD_DESCRIBE} · Web').classes('status text-gray-600')
    progress_bar = ui.linear_progress(value=0).classes('w-full')
    background_status = ui.label().classes('status')
    for control in (protocol, byte_data, internal, outbound, inbound):
        control.on_value_change(update_preview_options)
    progress_bar.set_visibility(False)
    update_actions()
    ui.timer(0.2, poll_progress)
    ui.timer(0.25, live_tick)
    ui.context.client.on_delete(stop_watching)
    # Browser Ctrl +/- zooms the entire interface using the browser's native control.


def run_web(*, port=8080, show=True, output=None):
    global WEB_OUTPUT
    from nicegui import helpers
    WEB_OUTPUT = Path(output or core.DEFAULT_OUTPUT)
    if not helpers.is_user_simulation() and not helpers.is_pytest():
        with socket.socket() as probe:
            occupied = probe.connect_ex(('127.0.0.1', port)) == 0
        if occupied:
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=2) as response:
                    existing = json.load(response)
                if existing.get('app') != 'LogComparator' or existing.get('ui') != 'web':
                    raise ValueError('different service')
            except Exception:
                raise RuntimeError(f'Port {port} is already in use. Start with --port and a free port.') from None
            if show:
                webbrowser.open(f'http://127.0.0.1:{port}')
            print(f'LogComparator is already running at http://127.0.0.1:{port}')
            return 0
    ui.run(host='0.0.0.0', port=port, title=f'LogComparator {core.APP_BUILD_DESCRIBE}',
           reload=False, show=show, favicon='🔎')
    return 0


def main():
    parser = argparse.ArgumentParser(description='LogComparator network web interface (NiceGUI / Quasar)')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    return run_web(port=args.port, show=not args.no_browser)


if __name__ in {'__main__', '__mp_main__'}:
    main()
