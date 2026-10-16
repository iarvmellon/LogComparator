"""Optional, loopback-only NiceGUI/Quasar interface. Run separately from main.py."""
from __future__ import annotations

import argparse
import asyncio
import difflib
import io
import queue
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from nicegui import run, ui

import log_core as core
from gui_services import download_uat_sources
from web_services import COLUMNS, CORE_LOCK, export_logs, filter_rows, load_logs

WORKSPACE = tempfile.TemporaryDirectory(prefix='LogComparator-web-')

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
    busy = False
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

    def offset():
        return int(timezone.value.replace('UTC', '') or 0)

    def refresh():
        if loaded is None:
            return
        try:
            minimum = datetime.fromisoformat(f'{from_date.value}T{from_time.value or "00:00:00"}').isoformat(sep=' ', timespec='seconds') if from_date.value else ''
            maximum = datetime.fromisoformat(f'{to_date.value}T{to_time.value or "23:59:59"}').isoformat(sep=' ', timespec='seconds') if to_date.value else ''
            if minimum and maximum and minimum > maximum:
                raise ValueError('From must be before To.')
            table.rows = filter_rows(loaded.rows, {key: control.value or '' for key, control in filters.items()}, minimum, maximum, offset())
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
            progress_bar.set_visibility(True)
            try:
                await callback()
            except Exception as error:
                status.set_text(str(error))
                ui.notify(str(error), type='negative', close_button=True, timeout=10000)
            finally:
                poll_progress()
                busy = False
                progress_bar.set_visibility(False)

    async def load_source(remote=False):
        async def action():
            nonlocal loaded
            bank_value = bank.value
            date_value = source_date.value or ''
            folder_value = folder.value or ''
            if not bank_value:
                raise ValueError('Select a bank/acquirer.')
            if remote:
                datetime.strptime(date_value, '%Y-%m-%d')
                source = await run.io_bound(download_uat, date_value, bank_value, progress)
                folder.set_value(str(source))
            else:
                if not folder_value.strip():
                    raise ValueError('Enter a log folder or use File > Import.')
                source = Path(folder_value)
            status.set_text('Loading source files…')
            result = await run.io_bound(load_logs, source, bank_value, date_value, progress)
            loaded = result
            source_date.set_value(result.selected_date)
            selected_date.set_text(f'Selected date:  {result.selected_date}  |  {result.bank}')
            from_date.set_value(result.selected_date)
            to_date.set_value(result.selected_date)
            table.selected = []
            poll_progress()
            refresh()
        await perform(action)

    def options():
        return dict(protocol_choice=protocol.value, include_byte_data=byte_data.value,
                    include_internal=internal.value, include_tango_to_network=outbound.value,
                    include_network_to_tango=inbound.value)

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
                folder.set_value(path_input.value)
                source_date.set_value('')
                dialog.close()
                await load_source()
            ui.button('Load folder', on_click=choose_path)
        dialog.open()

    def about():
        ui.notify(f'LogComparator {core.APP_BUILD_DESCRIBE} · NiceGUI / Quasar UI · Local web interface', timeout=6000)

    with ui.row().classes('menubar'):
        for label in ('File', 'Edit', 'View', 'Tools', 'Help'):
            with ui.button(label).props('flat dense'):
                with ui.menu():
                    if label == 'File':
                        ui.menu_item('Import…', on_click=import_dialog)
                        ui.menu_item('SSH/SCP (UAT)', on_click=lambda: load_source(remote=True))
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

    with ui.row().classes('toolbar items-start'):
        with panel('Data').classes('grow'), ui.row().classes('items-center gap-3'):
            folder = ui.input('Log folder', placeholder=r'C:\…\YYYY-MM-DD').props('outlined dense').classes('w-80 grow')
            bank = ui.select(list(core.BANK_AUDIT_CODES), label='Bank/Acquirer', value=next(iter(core.BANK_AUDIT_CODES))).props('outlined dense').classes('w-48')
            source_date = ui.input('Source date (auto if empty)').props('outlined dense type=date').classes('w-48')
            ui.button('Load', on_click=lambda: load_source()).props('outline dense')
            ui.button('SSH/SCP (UAT)', on_click=lambda: load_source(remote=True)).props('outline dense')
        with panel('Time range'), ui.row().classes('items-center gap-2'):
            from_date = ui.input('From', on_change=refresh).props('outlined dense type=date').classes('w-36')
            from_time = ui.input('Time', value='00:00:00', on_change=refresh).props('outlined dense type=time step=1').classes('w-32')
            to_date = ui.input('To', on_change=refresh).props('outlined dense type=date').classes('w-36')
            to_time = ui.input('Time', value='23:59:59', on_change=refresh).props('outlined dense type=time step=1').classes('w-32')
            timezone = ui.select(['UTC'] + [f'UTC{i:+d}' for i in range(-12, 15) if i], value='UTC', label='Timezone', on_change=refresh).props('outlined dense').classes('w-28')

    with panel('Filters').classes('w-full'), ui.row().classes('w-full gap-3'):
        for key, label in COLUMNS:
            if key in ('datetime', 'possibleproblem'):
                continue
            filters[key] = ui.input(label, on_change=refresh).props('outlined dense debounce=350').classes('filter-input')

    table = ui.table(columns=[dict(name=key, label=label, field=key, align='left', sortable=True) for key, label in COLUMNS],
                     rows=[], row_key='transuid', selection='multiple', pagination=100,
                     on_select=lambda _: status.set_text(f'Loaded transactions: {len(loaded.rows) if loaded else 0}; visible: {len(table.rows)}; selected: {len(table.selected)}'))
    table.classes('log-table').props('dense flat bordered separator=cell virtual-scroll')
    table.props['visible-columns'] = [key for key, _ in COLUMNS]
    table.add_slot('body', '''
        <q-tr :props="props" :class="[props.row.severity, {selected: props.selected}]">
          <q-td auto-width><q-checkbox dense v-model="props.selected" /></q-td>
          <q-td v-for="col in props.cols" :key="col.name" :props="props">{{ col.value }}</q-td>
        </q-tr>''')
    with ui.row().classes('w-full items-center justify-between'):
        status = ui.label('Select a log folder and bank/acquirer, then press Load.').classes('status')
        ui.label(f'LogComparator {core.APP_BUILD_DESCRIBE} · Web').classes('status text-gray-600')
    progress_bar = ui.linear_progress(value=0).classes('w-full')
    progress_bar.set_visibility(False)
    ui.timer(0.2, poll_progress)
    # Browser Ctrl +/- zooms the entire interface using the browser's native control.


def main():
    parser = argparse.ArgumentParser(description='LogComparator local web interface (NiceGUI / Quasar)')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    ui.run(host='127.0.0.1', port=args.port, title=f'LogComparator {core.APP_BUILD_DESCRIBE}',
           reload=False, show=not args.no_browser, favicon='🔎')


if __name__ in {'__main__', '__mp_main__'}:
    main()
