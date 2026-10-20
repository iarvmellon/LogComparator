"""Primary LogComparator interface: NiceGUI, Quasar and local diff2html."""
from __future__ import annotations

import argparse
import asyncio
import inspect
import html
import socket
import webbrowser
import urllib.request
import json
import io
import codecs
import queue
import tempfile
import zipfile
import uuid
import time
from collections import OrderedDict
from urllib.parse import urlencode, quote
from datetime import date, datetime, timedelta
from pathlib import Path
from string import Template

from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from nicegui import app, run, ui
from nicegui.translations import translations
from logcomparator_ui.diff_view import register_assets

import log_core as core
from web_services import (COLUMNS, comparison_diff, export_logs,
                          filter_rows, load_logs, publish_exports)
from web_services import list_local_source_files, LocalAuditJob, source_signature, SourceWatcher
from remote_logs import (uat_connection, RemoteImportRequest, UnknownHostKey, list_remote_sources,
                         audit_date, banks_for_audits, names_for_bank, read_remote_files as download_audits, read_remote_logs as download_tango_logs,
                         RemoteSourceWatcher, RemoteAuditJob, is_transient_ssh_error)

WORKSPACE = tempfile.TemporaryDirectory(prefix='LogComparator-web-')
PREVIEW_SOURCES = OrderedDict()
PREVIEW_DOWNLOADS = OrderedDict()
PREVIEW_TASKS = OrderedDict()
PREVIEW_SAVES = OrderedDict()
COMPARISONS = OrderedDict()
WEB_OUTPUT = core.DEFAULT_OUTPUT
register_assets()
# The reconnect overlay is rendered by NiceGUI outside the page content.
translations['en-US'].update(
    connection_lost='Browser <-> LogComparator connection lost.',
    trying_to_reconnect='Trying to reconnect the browser to LogComparator...',
)


@app.get('/health')
def health():
    return {'app': 'LogComparator', 'ui': 'web', 'version': core.APP_BUILD_DESCRIBE}


@app.get('/Log_Comparator_Web_Interface_Rectangles.drawio.png')
def readme_diagram():
    return FileResponse(Path(__file__).with_name('Log_Comparator_Web_Interface_Rectangles.drawio.png'), media_type='image/png')


@app.get('/readme', response_class=HTMLResponse)
def readme_page():
    """Display the same README distributed with the application."""
    import markdown2
    source = Path(__file__).with_name('README.md').read_text(encoding='utf-8')
    content = markdown2.markdown(source, extras=['fenced-code-blocks', 'tables'])
    document = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                '<title>LogComparator - README</title><style>'
                'body{max-width:1050px;margin:32px auto;padding:0 20px;font:16px/1.6 Arial,sans-serif;color:#202124;background:#fff}'
                'img{max-width:100%;height:auto}h1,h2,h3{line-height:1.3}h2{margin-top:36px;border-bottom:1px solid #ddd;padding-bottom:8px}'
                'a{color:#1976d2}pre{padding:16px;background:#f4f5f6;overflow:auto}'
                'code{font-family:Consolas,monospace}table{display:block;overflow:auto;border-collapse:collapse;max-width:100%}'
                'th,td{border:1px solid #ddd;padding:8px 12px;text-align:left}th{background:#f4f5f6}'
                '</style></head><body>' + content + '</body></html>')
    return HTMLResponse(document, headers={'Cache-Control': 'no-store'})


@app.get('/transaction/{source_id}', response_class=HTMLResponse)
def transaction_page(source_id: str, uid: str):
    """A standalone snapshot viewer, independent of NiceGUI's reconnect lifecycle."""
    title = html.escape(f'LogComparator - {uid}')
    data_url = '../transaction-data/' + quote(source_id, safe='') + '?' + urlencode({'uid': uid})
    script_url = json.dumps(data_url).replace('<', '\\u003c')
    document = '''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>$preview_title</title><style>
body{font-family:Arial,sans-serif;margin:16px;color:#151515;background:#fff}
h1{font-size:18px;font-weight:500}pre{font:13px Consolas,monospace;white-space:pre;overflow:auto}
#loading{display:flex;align-items:center;gap:8px;margin:16px 0}
.spinner{width:18px;height:18px;border:3px solid #ddd;border-top-color:#1976d2;border-radius:50%;animation:spin 1s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}[hidden]{display:none!important}
button{margin-right:8px;padding:6px 12px;cursor:pointer}
a{display:inline-block;padding:6px 12px;border:1px solid #1976d2;color:#1976d2;text-decoration:none}
#error{color:#b00020}
</style></head><body><h1>$preview_title</h1>
<div id="loading" role="status"><span class="spinner" aria-hidden="true"></span>Loading transaction log...</div>
<p id="error" role="alert" hidden></p><a id="download" hidden>Download log</a><pre id="log"></pre>
<p id="log-status" role="status"></p><button id="more" hidden>Load more</button><button id="all" hidden>Load full log</button>
<script src="/logcomparator-assets/transaction_view.js"></script>
<script>window.logComparatorShowTransaction($preview_data_url);</script></body></html>'''
    document = Template(document).substitute(preview_title=title, preview_data_url=script_url)
    return HTMLResponse(document, headers={'Cache-Control': 'no-store'})


PREVIEW_CHUNK_SIZE = 256 * 1024


def read_preview_chunk(path, offset=0):
    total = path.stat().st_size
    if offset < 0 or offset > total:
        raise ValueError('Invalid log position.')
    with path.open('rb') as handle:
        handle.seek(offset)
        raw = handle.read(PREVIEW_CHUNK_SIZE)
    decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
    text = decoder.decode(raw, final=offset + len(raw) >= total)
    pending = decoder.getstate()[0]
    next_offset = offset + len(raw) - len(pending)
    if text.endswith('\r') and next_offset < total and next_offset > offset + 1:
        text = text[:-1]
        next_offset -= 1
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    return dict(text=text, next_offset=next_offset, total_bytes=total, has_more=next_offset < total)


def preview_task(source_id, uid):
    loaded, settings, destination = PREVIEW_SOURCES[source_id]
    settings = dict(settings)
    key = (source_id, id(loaded), uid, tuple(settings.items()), str(destination))
    if key in PREVIEW_TASKS:
        existing = PREVIEW_TASKS[key]
        if existing.cancelled() or (existing.done() and existing.exception() is not None):
            PREVIEW_TASKS.pop(key)
        else:
            PREVIEW_TASKS.move_to_end(key)
            return existing

    async def generate():
        output = Path(tempfile.mkdtemp(prefix='preview-', dir=WORKSPACE.name))
        paths = await run.io_bound(export_logs, loaded, [uid], output, **settings)
        chunk = await run.io_bound(read_preview_chunk, paths[0])
        token = uuid.uuid4().hex
        PREVIEW_DOWNLOADS[token] = paths[0]

        async def save():
            try:
                await run.io_bound(publish_exports, paths, loaded, destination)
                return {'saved': True}
            except Exception as error:
                return {'error': str(error)}

        PREVIEW_SAVES[token] = {'save': save, 'task': None}
        while len(PREVIEW_DOWNLOADS) > 128:
            expired, _ = PREVIEW_DOWNLOADS.popitem(last=False)
            PREVIEW_SAVES.pop(expired, None)
        return {**chunk, 'download_url': f'../transaction-download/{token}',
                'chunk_url': f'../transaction-chunk/{token}', 'save_url': f'../transaction-save/{token}'}

    task = asyncio.create_task(generate())
    # Read speculative failures so an un-opened selection never produces an
    # unhandled-task warning. An actual Open still receives the same exception.
    task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
    PREVIEW_TASKS[key] = task
    while len(PREVIEW_TASKS) > 32:
        PREVIEW_TASKS.popitem(last=False)
    return task


@app.get('/transaction-data/{source_id}')
async def transaction_data(source_id: str, uid: str):
    if source_id not in PREVIEW_SOURCES:
        return JSONResponse({'error': 'This transaction link has expired. Reload the source in LogComparator.'}, status_code=404)
    try:
        result = await asyncio.shield(preview_task(source_id, uid))
        token = result['download_url'].rsplit('/', 1)[-1]
        entry = PREVIEW_SAVES.get(token)
        if entry is not None and entry['task'] is None:
            entry['task'] = asyncio.create_task(entry['save']())
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})
    except Exception as error:
        return JSONResponse({'error': str(error)}, status_code=400)


@app.get('/transaction-save/{token}')
async def transaction_save(token: str):
    entry = PREVIEW_SAVES.get(token)
    if entry is None:
        return JSONResponse({'error': 'Save status expired.'}, status_code=404)
    if entry['task'] is None:
        entry['task'] = asyncio.create_task(entry['save']())
    result = await asyncio.shield(entry['task'])
    return JSONResponse(result, status_code=400 if 'error' in result else 200,
                        headers={'Cache-Control': 'no-store'})


@app.get('/transaction-chunk/{token}')
async def transaction_chunk(token: str, offset: int = 0):
    path = PREVIEW_DOWNLOADS.get(token)
    if path is None or not path.is_file():
        return JSONResponse({'error': 'This log has expired. Reopen the transaction.'}, status_code=404)
    try:
        chunk = await run.io_bound(read_preview_chunk, path, offset)
        return JSONResponse(chunk, headers={'Cache-Control': 'no-store'})
    except ValueError as error:
        return JSONResponse({'error': str(error)}, status_code=400)


@app.get('/transaction-download/{token}')
def transaction_download(token: str):
    path = PREVIEW_DOWNLOADS.get(token)
    if path is None or not path.is_file():
        return JSONResponse({'error': 'This download has expired. Reopen the transaction.'}, status_code=404)
    return FileResponse(path, filename=path.name, media_type='text/plain', headers={'Cache-Control': 'no-store'})


@app.get('/comparison/{token}', response_class=HTMLResponse)
def comparison_page(token: str):
    if token not in COMPARISONS:
        return HTMLResponse('This comparison has expired. Compare the transactions again.', status_code=404)
    document = Path(__file__).with_name('logcomparator_ui').joinpath('assets', 'comparison.html').read_text(encoding='utf-8')
    return HTMLResponse(document.replace('__COMPARISON_DATA_URL__', json.dumps('/comparison-data/' + token)),
                        headers={'Cache-Control': 'no-store'})


@app.get('/comparison-data/{token}')
async def comparison_data(token: str):
    entry = COMPARISONS.get(token)
    if entry is None:
        return JSONResponse({'error': 'This comparison has expired. Compare the transactions again.'}, status_code=404)

    async def generate():
        output = Path(tempfile.mkdtemp(prefix='compare-', dir=WORKSPACE.name))
        paths = await run.io_bound(export_logs, entry['source'], entry['uids'], output, **entry['options'])
        await run.io_bound(publish_exports, paths, entry['source'], entry['destination'])
        texts = await run.io_bound(lambda: [path.read_text(encoding='utf-8', errors='replace') for path in paths])
        diff = await run.io_bound(comparison_diff, texts[0], texts[1], paths[0].name, paths[1].name)
        return dict(left=paths[0].name, right=paths[1].name, diff=diff)

    try:
        if entry.get('task') is None:
            entry['task'] = asyncio.create_task(generate())
        data = await asyncio.shield(entry['task'])
        return JSONResponse(data, headers={'Cache-Control': 'no-store'})
    except Exception as error:
        entry['task'] = None
        return JSONResponse({'error': str(error)}, status_code=400)

CSS = '''
body { background:#f0f0f0; color:#151515; font-family:Arial,sans-serif; }
.q-page { padding:0; }
.nicegui-content { padding:8px 12px; gap:12px; }
html, body { height:100%; overflow:hidden; }
.workspace { height:100vh; height:100dvh; max-width:100%; box-sizing:border-box; overflow:hidden; flex-wrap:nowrap; }
.workspace > * { flex-shrink:0; }
.workspace > .log-table { flex:1 1 0; min-height:0; overflow:hidden; }
.workspace-footer { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,.8fr) 180px max-content; align-items:center; gap:12px; width:100%; height:28px; min-height:28px; overflow:hidden; white-space:nowrap; }
.footer-text { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.footer-progress { width:180px; height:20px; display:flex; align-items:center; }
.menubar { background:#fafafa; border-bottom:1px solid #c4c4c4; gap:0; width:100%; }
.menubar .q-btn { min-height:26px; padding:0 10px; font-weight:400; }
.panel { border:1px solid #aaa; border-radius:0; padding:8px 10px; min-width:0; }
.panel legend { padding:0 6px; font-size:13px; }
.toolbar { gap:8px; align-items:center; width:100%; flex-wrap:nowrap; overflow-x:auto; }
.toolbar > * { flex-shrink:0; }
.toolbar .selected-date, .toolbar .toolbar-action { margin-left:32px; }
.toolbar .panel { padding:6px; }
.toolbar .q-radio__label, .toolbar .q-checkbox__label { white-space:nowrap; }
.data-time-row { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr) max-content; gap:14px; align-items:start; width:100%; }
.data-panel, .time-panel { overflow:hidden; }
.selection-controls { display:flex; align-items:center; gap:8px; height:40px; white-space:nowrap; }
.filters-panel { overflow-x:auto; }
.time-controls { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)) minmax(80px,.55fr); gap:8px; align-items:center; width:100%; }
.time-controls > * { width:100%; min-width:0; }
.filter-controls { display:grid; grid-template-columns:repeat(11,minmax(70px,1fr)) minmax(160px,1.6fr); gap:8px; min-width:1050px; width:100%; }
.data-controls { display:grid; grid-template-columns:minmax(140px,1fr) max-content minmax(0,1fr); gap:8px; align-items:center; width:100%; }
.data-controls > * { min-width:0; }
.data-controls .status { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.data-time-row .q-field__control-container, .data-time-row .q-field__native { min-width:0; }
@media (max-width:1000px) { .data-time-row { grid-template-columns:minmax(0,1fr); } }
@media (max-width:600px) {
    .data-controls { grid-template-columns:minmax(0,1fr) max-content; }
    .data-controls .status { grid-column:1 / -1; }
}

.q-field--outlined .q-field__control { border-radius:0; background:white; }
.q-field--dense .q-field__control, .q-field--dense .q-field__marginal { height:32px; }
.data-time-row .q-field--dense .q-field__control, .data-time-row .q-field--dense .q-field__marginal { height:40px; min-height:40px; }
.data-time-row .q-field--auto-height .q-field__native { min-height:40px; }
.q-btn { border-radius:0; text-transform:none; }
.q-table__container { border:1px solid #aaa; border-radius:0; width:100%; }
.q-table th { font-weight:bold; background:white; }
.q-table th, .q-table td { font-size:var(--log-font,10px); padding:3px 8px!important; height:auto!important; line-height:1.4; white-space:nowrap; }
.log-table thead th { font-size:calc(var(--log-font,10px) + 2px); font-weight:800; }
.log-table th, .log-table td { box-sizing:border-box; overflow:hidden; text-overflow:ellipsis; }
.log-table th:first-child, .log-table td:first-child { width:44px!important; min-width:44px!important; max-width:44px!important; padding:0 6px!important; text-align:center; }
.log-table th:first-child .q-checkbox, .log-table td:first-child .q-checkbox { vertical-align:middle; }
.log-table th:first-child .q-checkbox__inner, .log-table td:first-child .q-checkbox__inner { font-size:32px!important; }

.q-table tbody tr.problem { background:#ff9999; }
.q-table tbody tr.warning { background:#fff2b3; }
.q-table tbody tr.approved { background:#c8f7c5; }
.q-table tbody tr.selected > td { box-shadow:inset 0 2px #0078d7,inset 0 -2px #0078d7; }
.q-table tbody tr.selected > td:first-child { box-shadow:inset 0 2px #0078d7,inset 0 -2px #0078d7,inset 2px 0 #0078d7; }
.q-table tbody tr.selected > td:last-child { box-shadow:inset 0 2px #0078d7,inset 0 -2px #0078d7,inset -2px 0 #0078d7; }
.q-table tbody tr.selected > td::after { background:transparent; }
.log-table .q-table__middle { flex:1 1 0; min-height:0; max-height:none; overflow:auto; }
.log-table .q-table__bottom { flex-shrink:0; }
.log-table thead th { position:sticky; top:0; z-index:1; }
.filter-input, .problem-filter { width:100%; min-width:0; }
.diff2html-view { max-height:72vh; overflow:auto; width:100%; }
.diff2html-view .d2h-file-side-diff { overflow-x:auto; }
.diff2html-view .d2h-code-line, .diff2html-view .d2h-code-side-line { font-family:Consolas,monospace; }
.status { font-size:13px; }
.log-text { white-space:pre; overflow:auto; font-family:Consolas,monospace; font-size:13px; max-height:70vh; margin:0; }
'''


@ui.page('/', title=f'LogComparator {core.APP_BUILD_DESCRIBE}')
def index():
    ui.add_css(CSS)
    ui.add_head_html('<script src="/logcomparator-assets/open_tabs.js"></script>')
    ui.context.client.content.classes('workspace')
    loaded = None
    source_day = ''
    source_is_remote = False
    remote_connection = None
    audit_source_folder = core.LOCAL_AUDIT_DIR
    source_folder = core.DEFAULT_IMPORT
    busy = False
    background_job = None
    pending_bank = None
    preview_id = None
    font_size = 10
    column_revision = 0
    comparison_key = comparison_url = None
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

    def clear_bank_results():
        nonlocal column_revision
        column_revision += 1
        table.props['data-column-revision'] = column_revision
        table.props['loading'] = True
        table.rows = []
        table.selected = []
        table.update()
        update_actions()
        status.set_text(f'Loading {bank.value}...')
        if source_day:
            selected_date.set_text(f'Selected date:  {source_day}  |  {bank.value} (loading)')

    def refresh():
        nonlocal column_revision
        if loaded is None:
            return
        if loaded.bank != bank.value:
            clear_bank_results()
            return
        try:
            try:
                minimum = datetime.strptime(from_datetime.value, '%Y-%m-%d %H:%M:%S').isoformat(sep=' ', timespec='seconds') if from_datetime.value else ''
                maximum = datetime.strptime(to_datetime.value, '%Y-%m-%d %H:%M:%S').isoformat(sep=' ', timespec='seconds') if to_datetime.value else ''
            except ValueError:
                raise ValueError('Use YYYY-MM-DD HH:MM:SS in From and To (24-hour time).') from None
            if minimum and maximum and minimum > maximum:
                raise ValueError('From must be before To.')
            column_revision += 1
            table.props['data-column-revision'] = column_revision
            table.props['loading'] = False
            table.rows = filter_rows(loaded.rows, {key: control.value or '' for key, control in filters.items()}, minimum, maximum, offset())
            hidden_severities = {severity for severity, control in viewer_filters.items() if not control.value}
            table.rows = [row for row in table.rows if row.get('severity') not in hidden_severities]
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
        nonlocal busy, pending_bank
        if busy:
            ui.notify('Wait for the current operation to finish.', type='info')
            return
        async with operation_lock:
            busy = True
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
                update_actions()
                progress_bar.set_visibility(False)
                if pending_bank and loaded is not None:
                    if bank.value == loaded.bank:
                        pending_bank = None
                        refresh()
                    else:
                        asyncio.create_task(change_bank())

    async def change_bank():
        nonlocal pending_bank
        if loaded is not None:
            clear_bank_results()
        if busy:
            pending_bank = bank.value
            background_status.set_text(f'{bank.value} selected; opening after the current operation finishes.')
            return
        if loaded is not None and bank.value == loaded.bank:
            pending_bank = None
            refresh()
            selected_date.set_text(f'Selected date:  {source_day}  |  {loaded.bank}')
            return
        if loaded is None:
            return
        configure_live()
        if bank.value not in core.available_banks_for_folder(loaded.audit_folder or loaded.folder):
            if (background_job and not background_job.done.is_set()) or (source_is_remote and live_enabled.value):
                pending_bank = bank.value
                background_status.set_text(f'Waiting for {bank.value} audits to be read over SSH...')
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
        if loaded and source_day != core.current_log_date():
            live_enabled.set_value(False)
            live_enabled.disable()
            live_status.set_text(f'Live update is available only for today ({core.current_log_date()})')
            return
        live_enabled.enable()
        if live_enabled.value and loaded:
            source_watcher = (RemoteSourceWatcher(remote_connection, source_day, loaded.folder, bank=bank.value) if source_is_remote
                              else SourceWatcher(loaded.folder, loaded.audit_folder or loaded.folder, selected_date=source_day, bank=bank.value))
            live_status.set_text('Live — watching source files')
        else:
            live_status.set_text('Live paused' if loaded else 'Load files to start live updates')

    async def live_tick():
        nonlocal last_live_check, pending_bank
        if loaded is not None and source_day != core.current_log_date():
            if source_watcher or live_enabled.value or live_enabled.enabled:
                configure_live()
            return
        if busy or loaded is None or not live_enabled.value or source_watcher is None:
            return
        if pending_bank:
            if pending_bank in core.available_banks_for_folder(loaded.audit_folder or loaded.folder):
                pending_bank = None
                await load_source()
            return
        # Events drive immediate updates; metadata polling also covers missed
        # notifications on network shares and changes during a failed read.
        if not source_watcher.changed.is_set() and time.monotonic() - last_live_check < 5:
            return
        source_watcher.changed.clear()
        last_live_check = time.monotonic()
        await load_source(live=True)
        if source_watcher and source_watcher.error:
            live_status.set_text(f'SSH connection (LogComparator <-> {remote_connection.endpoint}) interrupted; reconnecting: {source_watcher.error}' if source_is_remote
                                 else f'Filesystem watcher unavailable; checking every 5 s: {source_watcher.error}')

    async def load_source(live=False, remote_import=None, local_import=False):
        if live and (busy or loaded is None or not live_enabled.value or source_day != core.current_log_date()):
            return
        async def action():
            nonlocal loaded, source_day, background_job, pending_bank, preview_id, audit_source_folder, source_folder, last_source_signature, source_is_remote, remote_connection
            bank_value = bank.value
            date_value = source_day
            folder_value = str(source_folder) if source_folder else ''
            audit_for_load = audit_source_folder
            if not bank_value:
                raise ValueError('Select a bank/acquirer.')
            if remote_import:
                connection = remote_import.connection
                names = remote_import.audits
                date_value, bank_value = remote_import.selected_date, remote_import.bank
                if background_job:
                    background_job.cancel_event.set()
                    background_job = None
                pending_bank = None
                core.DEFAULT_CACHE.mkdir(parents=True, exist_ok=True)
                source = Path(tempfile.mkdtemp(prefix='remote-', dir=core.DEFAULT_CACHE))
                audit_for_load = source
                foreground = names_for_bank(names, bank_value)
                if not foreground:
                    raise ValueError('No audit files available for the selected bank.')
                await run.io_bound(download_audits, connection, foreground, source, progress)
                await run.io_bound(download_tango_logs, connection, remote_import.logs, source, progress)
            else:
                if not folder_value.strip():
                    raise ValueError('Enter a log folder or use File > Import local logs.')
                source = Path(folder_value)
                if background_job and (local_import or source.resolve() != background_job.folder):
                    background_job.cancel_event.set()
                    background_job = None
                    pending_bank = None
                    background_status.set_text('')
            signature = await run.io_bound(source_signature, source, audit_for_load, date_value, bank_value)
            if live and signature == last_source_signature:
                live_status.set_text(f'Checked {datetime.now():%H:%M:%S} — no changes')
                return
            status.set_text('Loading source files…')
            result = await run.io_bound(load_logs, source, bank_value, date_value, progress,
                                       audit_folder=audit_for_load)
            loaded = result
            if remote_import:
                source_is_remote = True
                remote_connection = connection
            elif local_import:
                source_is_remote = False
                remote_connection = None
            if remote_import:
                source_folder = source
                if pending_bank is None:
                    bank.set_value(bank_value)
            audit_source_folder = result.audit_folder
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
                if remote_import or local_import:
                    live_enabled.set_value(False)
                configure_live()
            if remote_import:
                remaining = [name for name in names if name not in foreground]
                other_banks = [b for b in banks_for_audits(names) if b != bank_value]
                if remaining or other_banks:
                    background_job = RemoteAuditJob(connection, remaining, result.folder,
                                                    prepare_banks=other_banks,
                                                    selected_date=source_day)
                    background_status.set_text('Reading and preparing other banks for the selected date in the background.')
                else:
                    background_status.set_text('SSH live update reads only the selected bank for today.' if live_enabled.value else 'Historical files loaded; live update is off.')
            elif local_import:
                files = await run.io_bound(list_local_source_files, result.folder, result.audit_folder)
                other_banks = [b for b in core.BANK_AUDIT_CODES if b != bank_value and any(
                    item['kind'] == 'Audit' and item['date'] == source_day and b in item['banks'] for item in files)]
                if other_banks:
                    background_job = LocalAuditJob(result.folder, other_banks, source_day, audit_folder=result.audit_folder)
                    background_status.set_text('Reading and preparing other local banks for the selected date in the background.')
                else:
                    background_status.set_text('Selected local bank ready; live update is off.')
        await perform(action, quiet=live)

    def options():
        return dict(protocol_choice=protocol.value, include_byte_data=byte_data.value,
                    include_internal=internal.value, include_tango_to_network=outbound.value,
                    include_network_to_tango=inbound.value)

    def update_actions():
        nonlocal comparison_key, comparison_url
        key = (preview_id, id(loaded), tuple(row['transuid'] for row in table.selected), tuple(options().items()), str(session_settings.output)) if len(table.selected) == 2 else None
        if key != comparison_key:
            comparison_key = key
            comparison_url = None
            if key:
                token = uuid.uuid4().hex
                COMPARISONS[token] = dict(source=loaded, uids=list(key[2]), options=options(), destination=session_settings.output)
                while len(COMPARISONS) > 128:
                    COMPARISONS.popitem(last=False)
                comparison_url = f'/comparison/{token}'
        open_urls = [row['preview_url'] for row in table.selected]
        open_button.props['data-transaction-opener'] = 'true'
        open_button.props['data-comparison-url'] = comparison_url or ''
        for control in (open_button, tools_open):
            control.props['data-open-urls'] = json.dumps(open_urls)
            control.set_enabled(bool(open_urls) and not busy)
            if len(open_urls) == 1:
                control.props['href'] = open_urls[0]
                control.props['target'] = '_blank'
            else:
                control.props.pop('href', None)
        for control in (compare_button, tools_compare):
            if comparison_url:
                control.props['href'] = comparison_url
                control.props['target'] = '_blank'
                control.props['rel'] = 'noopener'
            else:
                control.props.pop('href', None)
            control.set_enabled(bool(comparison_url) and not busy)
        open_button.set_enabled(bool(table.selected) and not busy)
        compare_button.set_enabled(len(table.selected) == 2 and not busy)
        export_button.set_enabled(bool(table.rows) and not busy)
    def warm_selection():
        if not busy and preview_id in PREVIEW_SOURCES and len(table.selected) == 1:
            preview_task(preview_id, table.selected[0]['transuid'])

    def toolbar_open():
        update_preview_options()

    def toolbar_compare():
        update_actions()

    def selection_changed():
        update_actions()
        warm_selection()
        status.set_text(f'Loaded transactions: {len(loaded.rows) if loaded else 0}; visible: {len(table.rows)}; selected: {len(table.selected)}')

    def update_preview_options():
        if preview_id in PREVIEW_SOURCES:
            PREVIEW_SOURCES[preview_id] = (loaded, options(), session_settings.output)
        update_actions()
        warm_selection()

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
            if mode == 'compare':
                update_actions()
                ui.navigate.to(comparison_url, new_tab=True)
                return
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
        local_files = []
        log_source = core.DEFAULT_IMPORT
        audit_source = core.LOCAL_AUDIT_DIR or log_source
        with ui.dialog() as dialog, ui.card().classes('w-[620px] max-w-[95vw]'):
            ui.label('Import local log folder').classes('text-lg')
            ui.label('Select an available date and bank/acquirer.').classes('text-sm')
            source_message = ui.label().classes('text-sm whitespace-pre-wrap')

            def update_local_banks():
                available = [b for b in core.BANK_AUDIT_CODES if any(
                    item['kind'] == 'Audit' and item['date'] == local_date.value and b in item['banks'] for item in local_files)]
                import_bank.set_options(available)
                if import_bank.value not in available:
                    import_bank.set_value(bank.value if bank.value in available else (available[0] if available else None))
                load_button.set_enabled(bool(available))

            async def inspect_folders():
                nonlocal local_files
                load_button.disable()
                local_date.disable()
                try:
                    files = await run.io_bound(list_local_source_files, log_source, audit_source)
                    if dialog.is_deleted:
                        return
                    local_files = files
                    dates = sorted({item['date'] for item in files})
                    local_date.props['options'] = [day.replace('-', '/') for day in dates]
                    local_date.props['events'] = local_date.props['options']
                    local_date.set_enabled(bool(dates))
                    local_date.update()
                    local_date.set_value(source_day if source_day in dates else (dates[-1] if dates else None))
                    update_local_banks()
                    source_message.set_text(f'{len(files)} source files; {len(dates)} dates available.' if dates else 'No dated source files found.')
                except (OSError, ValueError) as error:
                    if not dialog.is_deleted:
                        source_message.set_text(str(error))

            async def choose_path():
                nonlocal source_day, audit_source_folder, source_folder
                if not import_bank.value or not local_date.value:
                    ui.notify('Select an available date and bank/acquirer.', type='warning')
                    return
                source_folder = log_source
                source_day = local_date.value
                audit_source_folder = audit_source
                bank.set_value(import_bank.value)
                clear_filters()
                clear_bank_results()
                dialog.close()
                await load_source(local_import=True)

            local_date = ui.date(on_change=update_local_banks).mark('local-import-calendar')
            local_date.props['options'] = []
            local_date.props['events'] = []
            local_date.props['event-color'] = 'green'
            local_date.disable()
            import_bank = ui.select([], label='Import Bank/Acquirer').props('outlined dense').classes('w-full')
            ui.label('The selected bank loads first; other banks for the same date are prepared in the background.').classes('text-sm')
            with ui.row():
                load_button = ui.button('Load Files', on_click=choose_path)
                load_button.disable()
                ui.button('Cancel', on_click=dialog.close).props('flat')
        dialog.open()
        await inspect_folders()

    async def remote_import_dialog():
        if busy:
            ui.notify('Wait for the current operation to finish.', type='info')
            return
        listed_connection = None
        names = []
        log_names = []
        trusted_fingerprint = ''
        listing = False
        with ui.dialog() as dialog, ui.card().classes('w-[620px] max-w-[95vw]'):
            ui.label('Import remote logs (UAT)').classes('text-lg')
            message = ui.label().classes('text-sm whitespace-pre-wrap')

            def connection():
                return uat_connection(settings=session_settings, fingerprint=trusted_fingerprint)

            def update_banks():
                available = banks_for_audits([name for name in names if audit_date(name) == calendar.value])
                remote_bank.set_options(available)
                remote_bank.set_value(bank.value if bank.value in available else (available[0] if available else None))
                import_button.set_enabled(bool(available) and listed_connection is not None)

            async def inspect_remote():
                nonlocal listed_connection, names, log_names, listing, trusted_fingerprint
                if listing or dialog.is_deleted:
                    return
                listing = True
                listed_connection = None
                names = []
                log_names = []
                import_button.disable()
                calendar.disable()
                remote_bank.set_options([])
                retry_button.set_visibility(False)
                try:
                    attempt = 1
                    while attempt <= 3:
                        message.set_text(f'Connecting and listing remote audit files... Attempt {attempt}/3')
                        try:
                            candidate = connection()
                            try:
                                names, log_names = await run.io_bound(list_remote_sources, candidate)
                            except UnknownHostKey as error:
                                if dialog.is_deleted:
                                    return
                                if candidate.fingerprint:
                                    raise ValueError('Remote host key changed; connection refused.') from error
                                trusted_fingerprint = error.fingerprint
                                attempt = 1
                                candidate = connection()
                                names, log_names = await run.io_bound(list_remote_sources, candidate)
                            if dialog.is_deleted:
                                return
                            if candidate.effective_fingerprint:
                                trusted_fingerprint = candidate.effective_fingerprint
                                candidate = connection()
                            listed_connection = candidate
                            days = sorted({audit_date(name) for name in names} | {core.parse_log_date(name) for name in log_names})
                            calendar.props['options'] = [day.replace('-', '/') for day in days]
                            calendar.props['events'] = calendar.props['options']
                            calendar.set_enabled(bool(days))
                            calendar.update()
                            calendar.set_value(source_day if source_day in days else (days[-1] if days else None))
                            update_banks()
                            message.set_text(f'{len(names)} audit files; {len(log_names)} Tango logs; {len(days)} dates available.' if days else 'No dated source files found.')
                            return
                        except Exception as error:
                            if dialog.is_deleted:
                                return
                            if attempt < 3 and is_transient_ssh_error(error):
                                message.set_text(f'Temporary SSH connection problem: {error}. Retrying automatically ({attempt + 1}/3)...')
                                await asyncio.sleep(attempt)
                                attempt += 1
                                if dialog.is_deleted:
                                    return
                                continue
                            message.set_text(f'Could not list remote audits: {error}. Use Retry listing to try again.')
                            retry_button.set_visibility(True)
                            return
                finally:
                    listing = False

            async def import_remote():
                if busy:
                    ui.notify('Wait for the current operation to finish.', type='info')
                    return
                if listed_connection is None or connection() != listed_connection:
                    message.set_text('Connect and list UAT logs before downloading.')
                    return
                selected_names = [name for name in names if audit_date(name) == calendar.value]
                if not remote_bank.value or not selected_names:
                    message.set_text('Select an available date and bank.')
                    return
                available = banks_for_audits(selected_names)
                selected_bank = remote_bank.value
                if selected_bank not in available:
                    message.set_text('Select an available bank/acquirer.')
                    return
                request = RemoteImportRequest(listed_connection, selected_names,
                                              [name for name in log_names if core.parse_log_date(name) == calendar.value],
                                              calendar.value, selected_bank)
                clear_filters()
                dialog.close()
                dialog.delete()
                await load_source(remote_import=request)

            retry_button = ui.button('Retry listing', on_click=inspect_remote).props('outline')
            retry_button.set_visibility(False)
            calendar = ui.date(on_change=update_banks).mark('remote-import-calendar')
            calendar.props['options'] = []
            calendar.props['events'] = []
            calendar.props['event-color'] = 'green'
            calendar.disable()
            remote_bank = ui.select([], label='Remote Bank/Acquirer').props('outlined dense').classes('w-full')
            ui.label('The selected bank loads first; other banks for the same date load once in the background. Live updates apply only to today and the selected bank.').classes('text-sm')
            with ui.row():
                import_button = ui.button('Read remote logs', on_click=import_remote)
                import_button.disable()
                ui.button('Cancel', on_click=dialog.delete).props('flat')
        dialog.open()
        await inspect_remote()

    def settings_dialog():
        with ui.dialog() as dialog, ui.card().classes('w-[620px] max-w-[95vw]'):
            ui.label('Settings').classes('text-lg')
            output_input = ui.input('Output folder', value=str(session_settings.output)).props('outlined dense').classes('w-full')
            ui.button('Browse output folder', on_click=lambda: browse_folder(output_input.value, output_input.set_value)).props('outline dense')
            def save():
                if not (output_input.value or '').strip():
                    ui.notify('Fill in the required settings.', type='warning')
                    return
                session_settings.output = Path(output_input.value).expanduser().resolve()
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
        nonlocal loaded, background_job, pending_bank, preview_id, source_day, audit_source_folder, source_folder, source_is_remote, remote_connection
        if background_job:
            background_job.cancel_event.set()
        loaded = background_job = pending_bank = preview_id = None
        source_day = ''
        source_is_remote = False
        remote_connection = None
        live_enabled.enable()
        table.rows = []
        stop_watching()
        live_status.set_text('')
        table.selected = []
        table.update()
        update_actions()
        source_folder = core.DEFAULT_IMPORT
        audit_source_folder = core.LOCAL_AUDIT_DIR
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

    with ui.row().classes('menubar'):
        for label in ('File', 'Edit', 'View', 'Tools', 'Help'):
            with ui.button(label).props('flat dense'):
                with ui.menu():
                    if label == 'File':
                        ui.menu_item('Import local logs', on_click=import_dialog).mark('import-menu')
                        ui.menu_item('Import remote logs (UAT)', on_click=remote_import_dialog).mark('remote-import-menu')
                        ui.menu_item('Export', on_click=export_action)
                        ui.menu_item('Settings', on_click=settings_dialog).mark('settings-menu')
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
                        tools_open = ui.menu_item('Open', on_click=toolbar_open)
                        ui.menu_item('Export', on_click=export_action)
                        tools_compare = ui.menu_item('Compare', on_click=toolbar_compare)
                    else:
                        ui.menu_item('README', on_click=lambda: ui.navigate.to('/readme', new_tab=True)).mark('help-readme')
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
        selected_date = ui.label('Selected date:  Not selected').classes('text-sm selected-date')
        open_button = ui.button('Open', on_click=toolbar_open).props('outline dense').classes('w-24 toolbar-action')
        export_button = ui.button('Export', on_click=export_action).props('outline dense').classes('w-24 toolbar-action')
        compare_button = ui.button('Compare', on_click=toolbar_compare).props('outline dense').classes('w-24 toolbar-action')

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

    with ui.element('div').classes('data-time-row'):
        with panel('Data').classes('data-panel'), ui.element('div').classes('data-controls'):
            bank = ui.select(list(core.BANK_AUDIT_CODES), label='Bank/Acquirer', value=next(iter(core.BANK_AUDIT_CODES)), on_change=change_bank).props('outlined dense').classes('w-full')
            live_enabled = ui.checkbox('Live update', value=False, on_change=configure_live).props('dense').mark('live-update')
            live_status = ui.label().classes('status').mark('live-status')
            with live_status:
                ui.tooltip().bind_text_from(live_status, 'text')
        with panel('Time range').classes('time-panel'), ui.element('div').classes('time-controls'):
            from_datetime = datetime_picker('From', '00:00:00')
            to_datetime = datetime_picker('To', '23:59:59')
            timezone = ui.select([f'UTC{i:+d}' if i else 'UTC' for i in range(-3, 4)], value='UTC', label='Timezone', on_change=change_timezone).props('outlined dense').classes('w-28')

        with panel('Selection viewer'), ui.element('div').classes('selection-controls'):
            viewer_filters = {
                severity: ui.checkbox(label, value=True, on_change=refresh).props('dense').mark(f"viewer-{severity or 'unknown'}")
                for severity, label in (('warning', 'Warnings'), ('problem', 'Errors'), ('approved', 'Succeeded'), ('', 'Unknown'))
            }

    with panel('Filters').classes('w-full filters-panel'), ui.element('div').classes('filter-controls'):
        for key, label in COLUMNS:
            if key in ('datetime', 'possibleproblem'):
                continue
            filters[key] = ui.input(label, on_change=refresh).props('outlined dense debounce=350').classes('filter-input')
        filters['possibleproblem'] = ui.input('Possible problem', on_change=refresh).props('outlined dense debounce=350 clearable').classes('problem-filter').mark('possible-problem-filter')

    table = ui.table(columns=[dict(name=key, label=label, field=key, align='left', sortable=True) for key, label in COLUMNS],
                     rows=[], row_key='transuid', selection='multiple', pagination=100,
                     on_select=selection_changed)
    table.classes('log-table').props('dense flat bordered separator=cell virtual-scroll')
    table.props['visible-columns'] = [key for key, _ in COLUMNS]

    def install_table_sizing():
        ui.run_javascript("const {installColumnSizing} = await import('/logcomparator-assets/table_sizing.js'); "
                          + f'installColumnSizing(getElement({table.id}));')

    ui.context.client.on_connect(install_table_sizing)

    def report_blocked_tabs(event):
        if (event.args or {}).get('blocked'):
            ui.notify('Your browser blocked transaction tabs. Allow pop-ups for this site, then click Open again.',
                      type='warning', timeout=10000, close_button=True)

    for control in (open_button, tools_open):
        control.on('click', report_blocked_tabs, js_handler="""event => {
            const urls = JSON.parse(event.currentTarget.getAttribute('data-open-urls') || '[]');
            if (urls.length > 1) {
                event.preventDefault();
                emit({blocked: event.currentTarget.ownerDocument.defaultView.logComparatorOpenTabs(urls)});
            }
        }""")


    table.add_slot('body', '''
        <q-tr :props="props" :class="[props.row.severity, {selected: props.selected}]" @click="props.selected = !props.selected" @dblclick="event => { const a = event.currentTarget.ownerDocument.createElement('a'); a.href = props.row.preview_url; a.target = '_blank'; a.rel = 'noopener'; a.click(); }">
          <q-td auto-width @click.stop><q-checkbox dense size="sm" v-model="props.selected" aria-label="Select transaction" /></q-td>
          <q-td v-for="col in props.cols" :key="col.name" :props="props" :style="col.style" :title="col.name === 'possibleproblem' ? '' : String(col.value ?? '')"><a v-if="col.name === 'transuid'" :href="props.row.preview_url" target="_blank" rel="noopener" @click.stop>{{ col.value }}</a><span v-else-if="col.name === 'possibleproblem'">{{ String(col.value || '').length > 100 ? String(col.value).slice(0, 97) + '...' : col.value }}<q-tooltip v-if="col.value" style="max-width:70vw;white-space:pre-wrap;overflow-wrap:anywhere">{{ props.row.possibleproblem }}</q-tooltip></span><span v-else>{{ col.value }}</span></q-td>
          <q-menu context-menu touch-position><q-list style="min-width:140px">
            <q-item v-for="action in ['Open', 'Export', 'Compare']" :key="action"
              :tag="action === 'Export' ? 'div' : 'a'"
              :href="action === 'Open' ? props.row.preview_url : '#'"
              target="_blank" rel="noopener" clickable v-close-popup
              @click="event => {
                const opener = event.currentTarget.ownerDocument.querySelector('[data-transaction-opener]');
                if (action === 'Open') {
                  const urls = JSON.parse(opener.getAttribute('data-open-urls') || '[]');
                  if (props.selected &amp;&amp; urls.length > 1) {
                    event.preventDefault();
                    const blocked = event.currentTarget.ownerDocument.defaultView.logComparatorOpenTabs(urls);
                    if (blocked.length) $parent.$emit('context-action', {uid:props.row.transuid, action:'tabs-blocked'});
                  }
                  return;
                }
                if (action === 'Compare') {
                  const url = opener.getAttribute('data-comparison-url');
                  if (props.selected &amp;&amp; url) { event.currentTarget.href = url; return; }
                  event.preventDefault();
                }
                $parent.$emit('context-action', {uid:props.row.transuid, action:action});
              }"><q-item-section>{{ action }}</q-item-section></q-item>
          </q-list></q-menu>
        </q-tr>''')

    async def context_action(event):
        if event.args.get('action') == 'tabs-blocked':
            ui.notify('Your browser blocked transaction tabs. Allow pop-ups for this site, then click Open again.', type='warning', timeout=10000)
            return
        uid = event.args.get('uid')
        row = next((row for row in table.rows if row['transuid'] == uid), None)
        if row is None:
            return
        if not any(selected['transuid'] == uid for selected in table.selected):
            table.selected = [row]
            table.update()
        await export_action({'Open': 'open', 'Export': 'download', 'Compare': 'compare'}.get(event.args.get('action'), 'open'))
    table.on('context-action', context_action)
    with ui.element('footer').classes('workspace-footer'):
        status = ui.label('Use File > Import local logs or Import remote logs (UAT) to load logs.').classes('status footer-text')
        with status:
            ui.tooltip().bind_text_from(status, 'text')
        background_status = ui.label().classes('status footer-text')
        with background_status:
            ui.tooltip().bind_text_from(background_status, 'text')
        # Keep the slot allocated even while the progress indicator is hidden.
        with ui.element('div').classes('footer-progress'):
            progress_bar = ui.linear_progress(value=0, size='8px', show_value=False).classes('w-full')
        ui.label(f'LogComparator {core.APP_BUILD_DESCRIBE} - Web').classes('status text-gray-600')
    for control in (protocol, byte_data, internal, outbound, inbound):
        control.on_value_change(update_preview_options)
    progress_bar.set_visibility(False)
    update_actions()
    ui.timer(0.2, poll_progress)
    ui.timer(0.25, live_tick)
    def stop_session_workers():
        stop_watching()
        if background_job:
            background_job.cancel_event.set()

    ui.context.client.on_delete(stop_session_workers)
    # Browser Ctrl +/- zooms the entire interface using the browser's native control.


def run_web(*, port=8080, show=True, output=None, ssl_certfile=None, ssl_keyfile=None):
    global WEB_OUTPUT
    from nicegui import helpers
    from web_tls import tls_options, local_tls_context
    tls = tls_options(ssl_certfile, ssl_keyfile, default_folder=core.DEFAULT_CACHE / 'tls')
    address = f'https://127.0.0.1:{port}'
    WEB_OUTPUT = Path(output or core.DEFAULT_OUTPUT)
    if not helpers.is_user_simulation() and not helpers.is_pytest():
        with socket.socket() as probe:
            occupied = probe.connect_ex(('127.0.0.1', port)) == 0
        if occupied:
            try:
                with urllib.request.urlopen(address + '/health', timeout=2,
                                            context=local_tls_context(tls['ssl_certfile'])) as response:
                    existing = json.load(response)
                if existing.get('app') != 'LogComparator' or existing.get('ui') != 'web':
                    raise ValueError('different service')
            except Exception:
                raise RuntimeError(f'Port {port} is already in use. Start with --port and a free port.') from None
            if show:
                webbrowser.open(address)
            print(f'LogComparator is already running at {address}')
            return 0
    ui.run(host='0.0.0.0', port=port, title=f'LogComparator {core.APP_BUILD_DESCRIBE}',
           reload=False, show=show, **tls, favicon='🔎')
    return 0


def main():
    parser = argparse.ArgumentParser(description='LogComparator network web interface (NiceGUI / Quasar)')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--ssl-certfile')
    parser.add_argument('--ssl-keyfile')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    return run_web(port=args.port, show=not args.no_browser, ssl_certfile=args.ssl_certfile, ssl_keyfile=args.ssl_keyfile)


if __name__ in {'__main__', '__mp_main__'}:
    main()
