"""Optional LAN-accessible NiceGUI/Quasar interface. Run separately from main.py."""
from __future__ import annotations

import argparse
import asyncio
import difflib
import io
import queue
import tempfile
import zipfile
import uuid
from collections import OrderedDict
from urllib.parse import urlencode
from datetime import date, datetime
from pathlib import Path

from nicegui import run, ui

import log_core as core
from gui_services import download_uat_sources, list_remote_logs
from web_services import BackgroundAudits, COLUMNS, CORE_LOCK, export_logs, filter_rows, load_logs

WORKSPACE = tempfile.TemporaryDirectory(prefix='LogComparator-web-')
PREVIEW_SOURCES = OrderedDict()


@ui.page('/transaction/{source_id}')
async def transaction_page(source_id: str, uid: str):
    entry = PREVIEW_SOURCES.get(source_id)
    if entry is None:
        ui.label('This transaction link has expired. Reload the source in LogComparator.')
        return
    loaded, settings = entry
    ui.label(f'LogComparator - {uid}').classes('text-lg')
    try:
        output = Path(tempfile.mkdtemp(prefix='preview-', dir=WORKSPACE.name))
        paths = await run.io_bound(export_logs, loaded, [uid], output, **dict(settings))
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
.q-table th, .q-table td { font-size:var(--log-font,13px); padding:3px 8px!important; height:26px!important; white-space:nowrap; }
.q-table tbody tr.problem { background:#ff9999; }
.q-table tbody tr.warning { background:#fff2b3; }
.q-table tbody tr.approved { background:#c8f7c5; }
.q-table tbody tr.selected { background:#0078d7!important; color:white; }
.log-table .q-table__middle { max-height:calc(100vh - 380px); min-height:240px; }
.filter-input { width:120px; flex:1 0 95px; }
.status { font-size:13px; }
.log-text { white-space:pre; overflow:auto; font-family:Consolas,monospace; font-size:13px; max-height:70vh; margin:0; }
@media(max-width:900px) { .log-table .q-table__middle { max-height:65vh; } }
'''


def download_uat(selected_date: str, bank: str, progress) -> Path:
    # Share the same parser/cache lock with local loading and exports.
    with CORE_LOCK:
        return download_uat_sources(selected_date, bank, core.DEFAULT_OUTPUT.parent, progress)


@ui.page('/')
def index():
    ui.add_css(CSS)
    loaded = None
    source_day = ''
    busy = False
    ssh_picker = None
    background_job = None
    pending_bank = None
    preview_id = None
    font_size = 13
    events = queue.Queue()
    filters = {}
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
            visible_uids = {row['transuid'] for row in table.rows}
            table.selected = [row for row in table.selected if row['transuid'] in visible_uids]
            table.update()
            status.set_text(f'Loaded transactions: {len(loaded.rows)}; visible: {len(table.rows)}; selected: {len(table.selected)}')
        except ValueError as error:
            ui.notify(str(error), type='warning')

    async def perform(callback):
        nonlocal busy
        if busy:
            ui.notify('Wait for the current operation to finish.', type='info')
            return
        async with operation_lock:
            busy = True
            bank.disable()
            progress_bar.set_visibility(True)
            try:
                await callback()
            except Exception as error:
                status.set_text(str(error))
                ui.notify(str(error), type='negative', close_button=True, timeout=10000)
            finally:
                poll_progress()
                busy = False
                bank.enable()
                progress_bar.set_visibility(False)

    async def change_bank():
        nonlocal pending_bank
        if loaded is not None and bank.value == loaded.bank:
            pending_bank = None
            return
        if busy or loaded is None:
            return
        if bank.value not in core.available_banks_for_folder(loaded.folder):
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

    async def load_source(remote=False):
        async def action():
            nonlocal loaded, source_day, background_job, pending_bank, preview_id
            bank_value = bank.value
            date_value = source_day
            folder_value = folder.value or ''
            if not bank_value:
                raise ValueError('Select a bank/acquirer.')
            if remote:
                if background_job:
                    background_job.cancel_event.set()
                pending_bank = None
                try:
                    datetime.strptime(date_value, '%Y-%m-%d')
                except ValueError:
                    raise ValueError('Select a valid SSH date before downloading.') from None
                source = await run.io_bound(download_uat, date_value, bank_value, progress)
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
            status.set_text('Loading source files…')
            result = await run.io_bound(load_logs, source, bank_value, date_value, progress)
            loaded = result
            preview_id = uuid.uuid4().hex
            PREVIEW_SOURCES[preview_id] = (result, options())
            while len(PREVIEW_SOURCES) > 32:
                PREVIEW_SOURCES.popitem(last=False)
            source_day = result.selected_date
            selected_date.set_text(f'Selected date:  {result.selected_date}  |  {result.bank}')
            from_datetime.set_value(f'{result.selected_date} 00:00:00')
            to_datetime.set_value(f'{result.selected_date} 23:59:59')
            table.selected = []
            poll_progress()
            refresh()
            if remote:
                background_status.set_text('Downloading audits for all banks in background...')
                background_job = BackgroundAudits(result.selected_date, result.folder)
        await perform(action)

    def options():
        return dict(protocol_choice=protocol.value, include_byte_data=byte_data.value,
                    include_internal=internal.value, include_tango_to_network=outbound.value,
                    include_network_to_tango=inbound.value)

    def update_preview_options():
        if preview_id in PREVIEW_SOURCES:
            PREVIEW_SOURCES[preview_id] = (loaded, options())

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
                return
            output = Path(tempfile.mkdtemp(prefix='export-', dir=WORKSPACE.name))
            status.set_text(f'Exporting {len(rows)} transaction(s)…')
            paths = await run.io_bound(export_logs, loaded, [row['transuid'] for row in rows], output, **options())
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
                        ui.label('Compare transactions' if mode == 'compare' else 'Transaction logs').classes('text-lg')
                        ui.button('Close', on_click=dialog.close).props('flat')
                    if mode == 'compare':
                        diff = ''.join(difflib.unified_diff(texts[0].splitlines(True), texts[1].splitlines(True),
                                                         fromfile=paths[0].name, tofile=paths[1].name))
                        ui.label(diff or 'The exported logs are identical.').classes('log-text w-full')
                    else:
                        with ui.tabs().classes('w-full') as tabs:
                            tab_items = [ui.tab(str(i), label=path.stem) for i, path in enumerate(paths)]
                        with ui.tab_panels(tabs, value=tab_items[0]).classes('w-full'):
                            for tab, text in zip(tab_items, texts):
                                with ui.tab_panel(tab):
                                    ui.label(text).classes('log-text w-full')
                dialog.open()
            status.set_text(f'Exported {len(paths)} transaction(s).')
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

    def import_dialog():
        with ui.dialog() as dialog, ui.card().classes('w-[700px] max-w-[95vw]'):
            ui.label('Import local log folder').classes('text-lg')
            ui.label('Choose a folder on the computer running LogComparator.').classes('text-sm')
            path_input = ui.input('Folder path', value=folder.value).props('outlined dense').classes('w-full')
            async def choose_path():
                nonlocal source_day
                folder.set_value(path_input.value)
                source_day = ''
                dialog.close()
                await load_source()
            ui.button('Load folder', on_click=choose_path)
        dialog.open()

    def about():
        ui.notify(f'LogComparator {core.APP_BUILD_DESCRIBE} · NiceGUI / Quasar UI · Local web interface', timeout=6000)

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
            remote_bank = ui.select(list(core.BANK_AUDIT_CODES), label='SSH Bank/Acquirer', value=bank.value).props('outlined dense').classes('w-full')

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
                if remote_bank.value not in core.BANK_AUDIT_CODES:
                    ui.notify('Select a bank/acquirer.', type='warning')
                    return
                source_day = remote_date.value
                bank.set_value(remote_bank.value)
                dialog.close()
                await load_source(remote=True)

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
                    paths = await run.io_bound(list_remote_logs)
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
                        ui.menu_item('Import…', on_click=import_dialog)
                        ui.menu_item('SSH/SCP (UAT)', on_click=ssh_dialog).mark('ssh-menu')
                        ui.menu_item('Export', on_click=export_action)
                    elif label == 'Edit':
                        ui.menu_item('Clear filters', on_click=clear_filters)
                        ui.menu_item('Select all visible', on_click=lambda: (setattr(table, 'selected', list(table.rows)), table.update()))
                        ui.menu_item('Clear selection', on_click=lambda: (setattr(table, 'selected', []), table.update()))
                    elif label == 'View':
                        ui.menu_item('Columns / Filters…', on_click=show_columns)
                        ui.menu_item('Increase font size', on_click=lambda: zoom(1))
                        ui.menu_item('Decrease font size', on_click=lambda: zoom(-1))
                    elif label == 'Tools':
                        ui.menu_item('Open', on_click=lambda: export_action('open'))
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
        ui.button('Open', on_click=lambda: export_action('open')).props('outline dense').classes('w-24')
        ui.button('Export', on_click=export_action).props('outline dense').classes('w-24')
        ui.button('Compare', on_click=lambda: export_action('compare')).props('outline dense').classes('w-24')

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
            folder = ui.input('Log folder', placeholder=r'C:\…\YYYY-MM-DD').props('outlined dense').classes('w-80 grow')
            bank = ui.select(list(core.BANK_AUDIT_CODES), label='Bank/Acquirer', value=next(iter(core.BANK_AUDIT_CODES)), on_change=change_bank).props('outlined dense').classes('w-48')
        with panel('Time range'), ui.row().classes('items-center gap-2'):
            from_datetime = datetime_picker('From', '00:00:00')
            to_datetime = datetime_picker('To', '23:59:59')
            timezone = ui.select([f'UTC{i:+d}' if i else 'UTC' for i in range(-3, 4)], value='UTC', label='Timezone', on_change=refresh).props('outlined dense').classes('w-28')

    with panel('Filters').classes('w-full'), ui.row().classes('w-full gap-3'):
        for key, label in COLUMNS:
            if key == 'datetime':
                continue
            filters[key] = ui.input(label, on_change=refresh).props('outlined dense debounce=350').classes('filter-input')

    table = ui.table(columns=[dict(name=key, label=label, field=key, align='left', sortable=True) for key, label in COLUMNS],
                     rows=[], row_key='transuid', selection='multiple', pagination=100,
                     on_select=lambda _: status.set_text(f'Loaded transactions: {len(loaded.rows) if loaded else 0}; visible: {len(table.rows)}; selected: {len(table.selected)}'))
    table.classes('log-table').props('dense flat bordered separator=cell virtual-scroll')
    table.props['visible-columns'] = [key for key, _ in COLUMNS]
    table.add_slot('body', '''
        <q-tr :props="props" :class="[props.row.severity, {selected: props.selected}]" @dblclick="event => { const a = event.currentTarget.ownerDocument.createElement('a'); a.href = props.row.preview_url; a.target = '_blank'; a.rel = 'noopener'; a.click(); }">
          <q-td auto-width><q-checkbox dense v-model="props.selected" /></q-td>
          <q-td v-for="col in props.cols" :key="col.name" :props="props"><a v-if="col.name === 'transuid'" :href="props.row.preview_url" target="_blank" rel="noopener" @click.stop>{{ col.value }}</a><span v-else>{{ col.value }}</span></q-td>
        </q-tr>''')
    with ui.row().classes('w-full items-center justify-between'):
        status = ui.label('Use File > Import or File > SSH/SCP (UAT) to load logs.').classes('status')
        ui.label(f'LogComparator {core.APP_BUILD_DESCRIBE} · Web').classes('status text-gray-600')
    progress_bar = ui.linear_progress(value=0).classes('w-full')
    background_status = ui.label().classes('status')
    for control in (protocol, byte_data, internal, outbound, inbound):
        control.on_value_change(update_preview_options)
    progress_bar.set_visibility(False)
    ui.timer(0.2, poll_progress)
    # Browser Ctrl +/- zooms the entire interface using the browser's native control.


def main():
    parser = argparse.ArgumentParser(description='LogComparator network web interface (NiceGUI / Quasar)')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    ui.run(host='0.0.0.0', port=args.port, title=f'LogComparator {core.APP_BUILD_DESCRIBE}',
           reload=False, show=not args.no_browser, favicon='🔎')


if __name__ in {'__main__', '__mp_main__'}:
    main()
