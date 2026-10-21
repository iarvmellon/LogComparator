"""Optional web tests: install requirements-web.txt before running this module."""
import tempfile
import asyncio
import unittest
import os
from unittest.mock import patch
from pathlib import Path

from web_services import comparison_diff, export_logs, filter_rows, inspect_local_sources, load_logs, with_settings


def source_fixture(folder):
    def block(flow, ref, mti):
        return ('=' * 80 + '\nRP date time GMT : 2026-10-14 06:47:58, timestamp: 20261014064758109\n'
                'Process name : OPNBISOBKT01\n'
                f"Flow dir : {'TANGO-->NETWORK' if flow == 'request' else 'NETWORK-->TANGO'}\n"
                f'Flow type : {flow}, ref: {ref}\nMessage type : out logon\n'
                f'msgId : asc<{mti}>\nnetworkManageCode : asc<001>\nauditNumber : asc<{115 if ref == "123" else 116:06d}>\n'
                'responseCode : asc<00>\n')
    (folder / 'tango.log.2026-10-14').write_text('', encoding='utf-8')
    (folder / 'audit.OPNBISOBKT01.2026-10-14').write_text(
        ''.join(block('request', ref, '0800') + block('response', ref, '0810')
                for ref in ('123', '456')), encoding='utf-8')


class WebServicesTests(unittest.TestCase):
    def test_preview_export_has_priority_over_background_parser(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        import web_services
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source_fixture(folder)
            loaded = load_logs(folder, 'AKTIF/BKT', '2026-10-14')
            locked = threading.Event()
            observed = threading.Event()
            def background():
                with web_services.CORE_LOCK:
                    locked.set()
                    if web_services.FOREGROUND_PENDING.wait(3):
                        observed.set()
            worker = threading.Thread(target=background)
            worker.start()
            self.assertTrue(locked.wait(2))
            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    result = pool.submit(export_logs, loaded, [loaded.rows[0]['transuid']], folder / 'preview').result(timeout=2)
                self.assertTrue(observed.is_set())
                self.assertTrue(result[0].is_file())
                self.assertFalse(web_services.FOREGROUND_PENDING.is_set())
            finally:
                worker.join(4)

    def test_local_file_listing_includes_each_day_and_compression_without_reading_logs(self):
        from web_services import list_local_source_files
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logs, audits = root / 'logs', root / 'audits'
            logs.mkdir()
            audits.mkdir()
            (logs / 'tango.log.2026-10-14.gz').write_bytes(b'not read during listing')
            (logs / 'tango.log.2026-10-15').write_text('')
            (audits / 'audit.OPNBISOBKT01.20261014.gz').write_bytes(b'not read during listing')
            (audits / 'unrelated.txt').write_text('')
            files = list_local_source_files(logs, audits)
            self.assertEqual(len(files), 3)
            self.assertEqual({item['date'] for item in files}, {'2026-10-14', '2026-10-15'})
            audit = next(item for item in files if item['kind'] == 'Audit')
            self.assertIn('AKTIF/BKT', audit['banks'])
            self.assertEqual(audit['path'], str((audits / 'audit.OPNBISOBKT01.20261014.gz').resolve()))

    def test_local_background_prepares_ready_results_with_separate_audit_folder(self):
        from web_services import LocalAuditJob
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logs, audits = root / 'logs', root / 'audits'
            logs.mkdir()
            audits.mkdir()
            source_fixture(root)
            for path in root.glob('audit.*'):
                path.rename(audits / path.name)
            for path in root.glob('tango.log.*'):
                path.rename(logs / path.name)
            job = LocalAuditJob(logs, ['AKTIF/BKTKOS'], '2026-10-14', audit_folder=audits)
            try:
                self.assertTrue(job.done.wait(10))
                self.assertIsNone(job.error)
                with patch('web_services._load_logs', side_effect=AssertionError('must use prepared bank')):
                    prepared = load_logs(logs, 'AKTIF/BKTKOS', '2026-10-14', audit_folder=audits)
                self.assertEqual(prepared.audit_folder, audits.resolve())
                self.assertEqual(len(prepared.rows), 2)
            finally:
                job.cancel_event.set()
                job.thread.join(10)

    @patch('log_core.current_log_date', return_value='2026-10-14')
    def test_filesystem_watcher_detects_writes_and_stops(self, current_day):
        from web_services import SourceWatcher
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            watcher = SourceWatcher(folder)
            try:
                watcher.changed.clear()
                # Repeated writes allow the native watcher to finish starting.
                for attempt in range(30):
                    (folder / 'tango.log.2026-10-14').write_text(str(attempt))
                    if watcher.changed.wait(0.1):
                        break
                self.assertTrue(watcher.changed.is_set())
                self.assertIsNone(watcher.error)
                # Drain coalesced events from the current-day writes before
                # checking that unrelated historical writes are ignored.
                for _ in range(10):
                    watcher.changed.clear()
                    if not watcher.changed.wait(0.35):
                        break
                else:
                    self.fail('Filesystem watcher never became quiet')
                (folder / 'tango.log.2026-10-13').write_text('old data')
                (folder / 'audit.OPNBISOBKT01.20261013').write_text('old audit')
                self.assertFalse(watcher.changed.wait(0.5))
            finally:
                watcher.close()
                watcher.thread.join(timeout=3)
            self.assertFalse(watcher.thread.is_alive())

    def test_split_folders_gzip_and_multiple_dates_do_not_modify_originals(self):
        import gzip
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logs, audits, cache = root / 'log', root / 'audit', root / 'cache'
            logs.mkdir()
            audits.mkdir()
            source_fixture(root)
            source_audit = root / 'audit.OPNBISOBKT01.2026-10-14'
            (audits / (source_audit.name + '.gz')).write_bytes(gzip.compress(source_audit.read_bytes()))
            (logs / 'tango.log.2026-10-14.gz').write_bytes(gzip.compress(b''))
            (logs / 'tango.log.2026-10-15').write_text('')
            before = {path: path.read_bytes() for path in [*logs.iterdir(), *audits.iterdir()]}
            dates, banks = inspect_local_sources(logs, audits)
            self.assertEqual(dates, ['2026-10-14', '2026-10-15'])
            self.assertIn('AKTIF/BKT', banks)
            with self.assertRaisesRegex(ValueError, 'Choose a date'):
                load_logs(logs, 'AKTIF/BKT', audit_folder=audits, cache_folder=cache)
            loaded = load_logs(logs, 'AKTIF/BKT', '2026-10-14', audit_folder=audits, cache_folder=cache)
            self.assertEqual(len(loaded.rows), 2)
            self.assertEqual(loaded.audit_folder, audits.resolve())
            self.assertTrue(loaded.audits[0].resolve().is_relative_to(cache.resolve()))
            self.assertEqual({path: path.read_bytes() for path in [*logs.iterdir(), *audits.iterdir()]}, before)
            paths = export_logs(loaded, [loaded.rows[0]['transuid']], root / 'exports')
            self.assertIn('asc<0810>', paths[0].read_text(encoding='utf-8'))

    def test_diff_has_valid_lines_and_session_settings_are_isolated(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        import log_core as core
        diff = comparison_diff('a\nlast', 'a\nchanged', 'left.log', 'right.log')
        self.assertIn('-last\n+changed\n', diff)
        self.assertEqual(comparison_diff('same', 'same', 'a', 'b'), '')
        with patch('log_core.shutil.which', return_value='ssh'), patch('log_core.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout='ok')) as execute:
            for user in ('session-a', 'session-b'):
                with_settings(core.RuntimeSettings(user=user, sudo_password='test-only'), core.run_remote_command, 'echo ok', True)
                self.assertIn(f'{user}@{core.DEFAULT_HOST}', execute.call_args.args[0])
                self.assertEqual(execute.call_args.kwargs['input'], 'test-only\n')
        self.assertIs(core.ACTIVE_RUNTIME_SETTINGS.get(), core.RUNTIME_SETTINGS)

    def test_real_load_filter_and_targeted_export(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source_fixture(folder)
            loaded = load_logs(folder, 'AKTIF/BKT')
            self.assertEqual(loaded.selected_date, '2026-10-14')
            self.assertEqual(len(loaded.rows), 2)
            self.assertIn('LOGON', loaded.rows[0]['transactiontype'])
            rows = filter_rows(loaded.rows, {'stan': loaded.rows[0]['stan']})
            self.assertEqual(len(rows), 1)
            shifted = filter_rows(rows, {}, '2026-10-14 08:47:58', '2026-10-14 08:47:58', 2)
            self.assertEqual(len(shifted), 1)
            self.assertEqual(shifted[0]['datetime'][:19], '2026-10-14 08:47:58')
            self.assertEqual(filter_rows(rows, {}, maximum='2026-10-14 06:47:57'), [])
            paths = export_logs(loaded, [rows[0]['transuid']], folder / 'out', protocol_choice='ISO')
            self.assertEqual(len(paths), 1)
            self.assertIn('asc<0810>', paths[0].read_text(encoding='utf-8'))
            with self.assertRaises(ValueError):
                export_logs(loaded, [], folder / 'empty')
            with self.assertRaises(ValueError):
                export_logs(loaded, ['foreign-uid'], folder / 'foreign')

    def test_warning_and_error_display_preserves_color(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source_fixture(folder)
            original = load_logs(folder, 'AKTIF/BKT')
            for findings, expected in [(('warning: timeout', 'warning: timeout'), 'warning'),
                                       (('warning: timeout', 'error: bad field'), 'problem')]:
                problems = {row['transuid']: findings for row in original.rows}
                with patch('web_services.build_problem_columns', return_value=problems):
                    from web_services import LOADED_CACHE
                    LOADED_CACHE.clear()  # Each case supplies a different diagnostics implementation.
                    loaded = load_logs(folder, 'AKTIF/BKT')
                for row in loaded.rows:
                    self.assertEqual(row['severity'], expected)
                    self.assertNotIn('warning:', row['possibleproblem'])
                    self.assertNotIn('error:', row['possibleproblem'])
                    self.assertEqual(row['possibleproblem'].count('timeout'), 1)


class WebPageTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_linux_import_uses_separate_folders_without_ssh(self):
        if 'PYTEST_CURRENT_TEST' not in os.environ:
            self.skipTest('Run the NiceGUI simulation with pytest.')
        from contextlib import ExitStack
        from unittest.mock import patch
        from nicegui import ui
        from nicegui.testing.user_simulation import user_simulation
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            logs, audits = root / 'log', root / 'audit'
            logs.mkdir()
            audits.mkdir()
            source_fixture(root)
            (root / 'tango.log.2026-10-14').replace(logs / 'tango.log.2026-10-14')
            (root / 'audit.OPNBISOBKT01.2026-10-14').replace(audits / 'audit.OPNBISOBKT01.2026-10-14')
            (logs / 'tango.log.2026-10-15').write_text('')
            for name, value in {'ENABLE_SSH': False, 'DEFAULT_IMPORT': logs,
                                'LOCAL_AUDIT_DIR': audits, 'DEFAULT_OUTPUT': root / 'exports',
                                'DEFAULT_CACHE': root / 'cache'}.items():
                stack.enter_context(patch('log_core.' + name, value))
            current_day = stack.enter_context(patch('log_core.current_log_date', return_value='2026-10-14'))
            with patch('sys.argv', ['web_app.py', '--no-browser']):
                simulation = user_simulation(main_file=Path(__file__).resolve().parents[1] / 'web_app.py')
                user = await simulation.__aenter__()
            try:
                await user.open('/')
                self.assertFalse(next(iter(user.find(marker='live-update').elements)).value)
                await user.should_not_see(marker='ssh-menu')
                await user.should_see('Import local logs')
                await user.should_see('Import remote logs (UAT)')
                user.find(marker='import-menu').click()
                await user.should_see('Import local log folder', retries=100)
                await user.should_not_see('Choose a folder on the computer running LogComparator.')
                self.assertFalse(any(e.props.get('label') in ('Folder path', 'Audit folder (empty = same folder)')
                                     for e in user.find(ui.input).elements))
                self.assertFalse(any(e.props.get('label') in ('Browse folders', 'Browse audit folder', 'Inspect dates and banks')
                                     for e in user.find(ui.button).elements))
                self.assertTrue(max(user.find(ui.dialog).elements, key=lambda e: e.id).value)
                dates = next(iter(user.find(marker='local-import-calendar').elements))
                for _ in range(100):
                    if len(dates.props['options']) == 2:
                        break
                    await asyncio.sleep(0.1)
                self.assertEqual(dates.props['options'], ['2026/10/14', '2026/10/15'])
                with user:
                    dates.set_value('2026-10-14')
                self.assertFalse(any(e.props.get('label') == 'Source file' for e in user.find(ui.select).elements))
                self.assertEqual(dates.value, '2026-10-14')
                user.find('Load Files').click()
                await user.should_see('Loaded transactions: 2', retries=100)
                table = next(iter(user.find(ui.table).elements))
                self.assertEqual(len(table.rows), 2)
                self.assertFalse(table.props['virtual-scroll'])
                live_timer = next(e for e in user.find(ui.timer).elements if e.interval == 0.25)
                audit_file = audits / 'audit.OPNBISOBKT01.2026-10-14'
                addition = audit_file.read_text().replace('ref: 123', 'ref: 789').replace('ref: 456', 'ref: 790')
                with audit_file.open('a') as stream:
                    stream.write(addition)
                with user:
                    await live_timer.callback()
                self.assertEqual(len(table.rows), 2)  # disabled by default
                inputs = {e.props.get('label'): e for e in user.find(ui.input).elements}
                with user:
                    table.selected = [table.rows[0]]
                    inputs['From'].set_value('2026-10-14 06:00:00')
                    inputs['TransactionType'].set_value('LOGON')
                    next(iter(user.find(marker='live-update').elements)).set_value(True)
                    from unittest.mock import Mock
                    with patch.dict(live_timer.callback.__globals__, load_logs=Mock(side_effect=OSError('temporary read failure'))):
                        await live_timer.callback()
                self.assertEqual(len(table.rows), 2)
                await user.should_see('Live update delayed')
                # A later filesystem event retries the read without clearing rows.
                with audit_file.open('a') as stream:
                    stream.write('\n')
                await asyncio.sleep(0.4)
                with user:
                    await live_timer.callback()
                self.assertEqual(len(table.rows), 4)

                self.assertEqual(len(table.selected), 1)
                self.assertEqual(inputs['From'].value, '2026-10-14 06:00:00')
                self.assertEqual(inputs['TransactionType'].value, 'LOGON')
                self.assertIs(table.selected[0], table.rows[0])
                with user:
                    await live_timer.callback()
                self.assertEqual(len(table.rows), 4)

                # Remote import is available even with the legacy UAT menu off.
                from remote_logs import UnknownHostKey
                from unittest.mock import Mock
                import shutil
                fixture = root / 'remote-fixture'
                fixture.mkdir()
                source_fixture(fixture)
                remote_name = 'audit.OPNBISOBKT01.2026-10-14'
                listing = Mock(side_effect=[TimeoutError('timed out'), UnknownHostKey('SHA256:test-host'),
                                            TimeoutError('timed out'), TimeoutError('timed out'),
                                            ([remote_name], ['tango.log.2026-10-14'])])

                def copy_remote(connection, names, target, progress):
                    import log_core as core
                    self.assertEqual(connection.endpoint, f'{core.DEFAULT_HOST}:{core.SSH_PORT}')
                    self.assertEqual(connection.username, core.RUNTIME_SETTINGS.user)
                    self.assertTrue(connection.password == core.RUNTIME_SETTINGS.sudo_password)
                    for name in names:
                        shutil.copyfile(fixture / name, target / name)

                transfer = Mock(side_effect=copy_remote)
                log_transfer = Mock(side_effect=copy_remote)
                with patch.dict(live_timer.callback.__globals__, list_remote_sources=listing, download_audits=transfer, download_tango_logs=log_transfer, RemoteSourceWatcher=Mock(return_value=Mock(changed=__import__('threading').Event(), error=None))):
                    user.find(marker='remote-import-menu').click()
                    await user.should_see('Import remote logs (UAT)')
                    remote_inputs = {e.props.get('label'): e for e in user.find(ui.input).elements}
                    import log_core as core
                    for label in ('Remote host (IP:port)', 'Remote username', 'Remote password'):
                        self.assertNotIn(label, remote_inputs)
                    self.assertFalse(any(e.text == 'Connect and list logs' for e in user.find(ui.button).elements))
                    await user.should_see('1 audit files; 1 Tango logs; 1 dates available.', retries=100)
                    self.assertEqual(listing.call_count, 5)
                    self.assertFalse(any('Trust this host fingerprint' in e.text for e in user.find(ui.button).elements))
                    self.assertEqual(listing.call_args.args[0].fingerprint, 'SHA256:test-host')
                    self.assertEqual(listing.call_args.args[0].audit_folder, '/opt/tango/MLNPSP01/audit')
                    self.assertEqual(listing.call_args.args[0].log_folder, '/opt/tango/MLNPSP01/log')
                    calendar = next(iter(user.find(marker='remote-import-calendar').elements))
                    self.assertEqual(calendar.props['events'], ['2026/10/14'])
                    self.assertEqual(calendar.props['options'], calendar.props['events'])
                    remote_bank = next(e for e in user.find(ui.select).elements if e.props.get('label') == 'Remote Bank/Acquirer')
                    with user:
                        remote_bank.set_value('AKTIF/BKT')
                    user.find('Read remote logs').click()
                    await user.should_see('Loaded transactions: 2', retries=100)
                    self.assertTrue(next(e for e in user.find(ui.select).elements if e.props.get('label') == 'Bank/Acquirer').enabled)
                    transfer.assert_called_once()
                    log_transfer.assert_called_once()
                    self.assertEqual(log_transfer.call_args.args[1], ['tango.log.2026-10-14'])
                    self.assertEqual(len(table.rows), 2)
                    live_control = next(iter(user.find(marker='live-update').elements))
                    self.assertTrue(live_control.enabled)
                    self.assertFalse(live_control.value)
                    with user:
                        live_control.set_value(True)
                    await user.should_see('Selected date:  2026-10-14  |  AKTIF/BKT')
                    with user:
                        await live_timer.callback()
                    self.assertEqual(len(table.rows), 2)
                    cache_folder = Path(transfer.call_args.args[2])
                    with (cache_folder / remote_name).open('a') as stream:
                        stream.write(addition)
                    with user:
                        table.selected = [table.rows[0]]
                        inputs['From'].set_value('2026-10-14 06:00:00')
                        inputs['TransactionType'].set_value('LOGON')
                        live_timer.callback.__globals__['RemoteSourceWatcher'].return_value.changed.set()
                        await live_timer.callback()
                    self.assertEqual(len(table.rows), 4)
                    self.assertEqual(len(table.selected), 1)
                    self.assertEqual(inputs['From'].value, '2026-10-14 06:00:00')
                    self.assertEqual(inputs['TransactionType'].value, 'LOGON')
                    import inspect
                    load_callback = inspect.getclosurevars(live_timer.callback).nonlocals['load_source']
                    perform_callback = inspect.getclosurevars(load_callback).nonlocals['perform']
                    started, release = asyncio.Event(), asyncio.Event()

                    async def held_operation():
                        started.set()
                        await release.wait()

                    with user:
                        operation = asyncio.create_task(perform_callback(held_operation))
                        await asyncio.wait_for(started.wait(), 3)
                        bank_control = next(e for e in user.find(ui.select).elements if e.props.get('label') == 'Bank/Acquirer')
                        self.assertTrue(bank_control.enabled)
                        bank_control.set_value('AKTIF/BKTKOS')
                    try:
                        await user.should_see('AKTIF/BKTKOS selected; opening after the current operation finishes.', retries=100)
                        self.assertEqual(inspect.getclosurevars(load_callback).nonlocals['loaded'].bank, 'AKTIF/BKT')
                        self.assertEqual(table.rows, [])
                        self.assertEqual(table.selected, [])
                        self.assertTrue(table.props.get('loading'))
                        with user:
                            inspect.getclosurevars(load_callback).nonlocals['refresh']()
                        self.assertEqual(table.rows, [])
                    finally:
                        release.set()
                        await operation
                    await user.should_see('Selected date:  2026-10-14  |  AKTIF/BKTKOS', retries=100)
                    for _ in range(100):
                        if not table.props.get('loading'):
                            break
                        await asyncio.sleep(0.05)
                    self.assertFalse(table.props.get('loading'))
                    self.assertTrue(table.rows)
                    self.assertTrue(live_control.enabled)
                    user.find(marker='import-menu').click()
                    await asyncio.sleep(0.1)  # let the new dialog be created before selecting its button
                    await user.should_see('Import local log folder')
                    max(user.find('Load Files').elements, key=lambda element: element.id).mark('latest-local-load')
                    user.find(marker='latest-local-load').click()
                    for _ in range(100):
                        if not any(dialog.value for dialog in user.find(ui.dialog).elements) and not inspect.getclosurevars(load_callback).nonlocals['busy']:
                            break
                        await asyncio.sleep(0.05)
                    await user.should_see('Loaded transactions: 4', retries=100)
                    self.assertTrue(live_control.enabled)
                    listing.reset_mock(side_effect=True)
                    listing.side_effect = [TimeoutError('timed out')] * 3 + [([remote_name], ['tango.log.2026-10-14'])]
                    user.find(marker='remote-import-menu').click()
                    await user.should_see('Use Retry listing to try again.', retries=100)
                    self.assertEqual(listing.call_count, 3)
                    user.find(kind=ui.button, content='Retry listing').click()
                    await user.should_see('1 audit files; 1 Tango logs; 1 dates available.', retries=100)
                    self.assertEqual(listing.call_count, 4)
                    max(user.find('Cancel').elements, key=lambda element: element.id).mark('cancel-retry-dialog')
                    user.find(marker='cancel-retry-dialog').click()
                    listing.reset_mock(side_effect=True)
                    listing.side_effect = TimeoutError('timed out')
                    user.find(marker='remote-import-menu').click()
                    await user.should_see('Retrying automatically', retries=100)
                    max(user.find('Cancel').elements, key=lambda element: element.id).mark('cancel-pending-retry')
                    user.find(marker='cancel-pending-retry').click()
                    await asyncio.sleep(1.2)
                    self.assertEqual(listing.call_count, 1)
                    current_day.return_value = '2026-10-15'
                    with user:
                        await live_timer.callback()
                    self.assertFalse(live_control.enabled)
                    self.assertFalse(live_control.value)
                    await user.should_see('Live update is available only for today (2026-10-15)')
                    watcher_factory = live_timer.callback.__globals__['RemoteSourceWatcher']
                    watcher_starts = watcher_factory.call_count
                    listing.reset_mock(side_effect=True)
                    listing.return_value = ([remote_name], ['tango.log.2026-10-14'])
                    user.find(marker='remote-import-menu').click()
                    await user.should_see('1 audit files; 1 Tango logs; 1 dates available.', retries=100)
                    remote_bank = max((e for e in user.find(ui.select).elements if e.props.get('label') == 'Remote Bank/Acquirer'), key=lambda e: e.id)
                    with user:
                        remote_bank.set_value('AKTIF/BKT')
                    user.find(kind=ui.button, content='Read remote logs').click()
                    await user.should_see('Loaded transactions: 2', retries=100)
                    self.assertFalse(live_control.enabled)
                    self.assertFalse(live_control.value)
                    self.assertEqual(watcher_factory.call_count, watcher_starts)
                    await user.should_see('Live update is available only for today')

            finally:
                await simulation.__aexit__(None, None, None)

    async def test_page_load_filter_open_compare_and_download(self):
        if 'PYTEST_CURRENT_TEST' not in os.environ:
            self.skipTest('Run the NiceGUI simulation with pytest.')
        from nicegui import ui
        from nicegui.testing.user_simulation import user_simulation
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source_fixture(folder)
            output_patch = patch('log_core.DEFAULT_OUTPUT', folder / 'exports')
            output_patch.start()
            local_log_patch = patch('log_core.DEFAULT_IMPORT', folder)
            local_audit_patch = patch('log_core.LOCAL_AUDIT_DIR', folder)
            local_log_patch.start()
            local_audit_patch.start()
            with patch('sys.argv', ['web_app.py', '--no-browser']):
                simulation = user_simulation(main_file=Path(__file__).resolve().parents[1] / 'web_app.py')
                user = await simulation.__aenter__()
            try:
                await user.open('/')
                inputs = {element.props.get('label'): element for element in user.find(ui.input).elements}
                self.assertFalse(any('Source date' in (label or '') for label in inputs))
                self.assertNotIn('Log folder', inputs)
                self.assertNotIn('Audit folder', inputs)
                with patch.object(user.navigate, 'to') as navigate:
                    user.find(marker='help-readme').click()
                    navigate.assert_called_once_with('/readme', new_tab=True)
                guide = await user.http_client.get('/readme')
                self.assertEqual(guide.status_code, 200)
                self.assertIn('<h1>LogComparator</h1>', guide.text)
                self.assertIn('Import local logs', guide.text)
                self.assertIn('Import remote logs', guide.text)
                self.assertIn('Consistency viewer', guide.text)
                self.assertIn('<table>', guide.text)

                selects = {element.props.get('label'): element for element in user.find(ui.select).elements}
                self.assertEqual(selects['Timezone'].options, ['UTC-3', 'UTC-2', 'UTC-1', 'UTC', 'UTC+1', 'UTC+2', 'UTC+3'])
                self.assertFalse(selects['Bank/Acquirer'].enabled)
                with user:
                    selects['Bank/Acquirer'].set_value('AKTIF/BKT')
                self.assertFalse(any(e.props.get('label') in ('Load', 'SSH/SCP (UAT)') for e in user.find(ui.button).elements))
                await user.should_not_see(marker='ssh-menu')
                await user.should_see('Import local logs')
                await user.should_see('Import remote logs (UAT)')
                user.find(marker='import-menu').click()
                await user.should_see('Import local log folder')
                local_inputs = {e.props.get('label'): e for e in user.find(ui.input).elements}
                local_selects = {e.props.get('label'): e for e in user.find(ui.select).elements}
                with user:
                    local_selects['Import Bank/Acquirer'].set_value('AKTIF/BKT')
                user.find('Load Files').click()
                await user.should_see('Loaded transactions: 2', retries=100)
                table = next(iter(user.find(ui.table).elements))
                self.assertEqual(len(table.rows), 2)
                self.assertTrue(selects['Bank/Acquirer'].enabled)
                with user:
                    inputs['Possible problem'].set_value('nonexistent-problem')
                self.assertEqual(len(table.rows), 0)
                with user:
                    inputs['Possible problem'].set_value('')
                self.assertEqual(len(table.rows), 2)
                self.assertEqual(table.columns[-1]['label'], 'Possible problem')
                self.assertFalse(any(e.props.get('label', '').startswith('Time') for e in user.find(ui.input).elements))
                self.assertEqual(inputs['From'].value, '2026-10-14 00:00:00')
                self.assertEqual(inputs['To'].value, '2026-10-14 23:59:59')
                user.find(marker='From-picker').trigger('click.stop')
                await user.should_see('From - Date and time')
                day = next(iter(user.find(marker='From-date').elements))
                clock = next(iter(user.find(marker='From-time').elements))
                self.assertTrue(clock.props['format24h'])
                with user:
                    day.set_value('2026-10-14')
                    clock.set_value('06:47:59')
                user.find(marker='From-apply').click()
                self.assertEqual(inputs['From'].value, '2026-10-14 06:47:59')
                self.assertEqual(len(table.rows), 0)
                with user:
                    inputs['From'].set_value('2026-10-14 06:47:59')
                self.assertEqual(len(table.rows), 0)
                with user:
                    inputs['From'].set_value('2026-10-14 06:47:58')
                    inputs['To'].set_value('2026-10-14 06:47:58')
                self.assertEqual(len(table.rows), 2)
                with user:
                    inputs['TransUID'].set_value(table.rows[0]['transuid'])
                self.assertEqual(len(table.rows), 0)
                with user:
                    inputs['TransUID'].set_value('')
                    inputs['STAN'].set_value(table.rows[0]['stan'])
                self.assertEqual(len(table.rows), 1)
                with user:
                    inputs['STAN'].set_value('')
                    table.selected = []
                user.find(ui.table).trigger('selection', {'added': True, 'rows': list(table.rows), 'keys': [row['transuid'] for row in table.rows]})
                compare = next(iter(user.find(kind=ui.button, content='Compare').elements))
                comparison_url = compare.props['href']
                self.assertEqual(compare.props['target'], '_blank')
                self.assertTrue(all('open_urls' not in row and 'comparison_url' not in row for row in table.rows))
                with patch.object(user.navigate, 'to') as navigate:
                    user.find(kind=ui.button, content='Compare').click()
                    navigate.assert_not_called()
                with patch('web_app.export_logs', side_effect=AssertionError('page must open before export')):
                    comparison = await user.http_client.get(comparison_url)
                self.assertEqual(comparison.status_code, 200)
                self.assertIn('Preparing comparison...', comparison.text)
                self.assertIn('diff2html-comparison', comparison.text)
                self.assertIn('Download diff', comparison.text)
                data_url = comparison_url.replace('/comparison/', '/comparison-data/')
                with patch('web_services.build_problem_columns', side_effect=AssertionError('must not reparse')):
                    result = await user.http_client.get(data_url)
                self.assertEqual(result.status_code, 200)
                self.assertEqual(set(result.json()), {'left', 'right', 'diff'})
                with patch('web_app.export_logs', side_effect=AssertionError('must reuse comparison')):
                    cached = await user.http_client.get(data_url)
                self.assertEqual(cached.json(), result.json())
                assets = await user.http_client.get('/logcomparator-assets/diff2html-ui-base.min.js')
                self.assertEqual(assets.status_code, 200)
                with patch.object(user.navigate, 'to') as navigate:
                    user.find(kind=ui.button, content='Open').click()
                    await asyncio.sleep(0.1)
                    navigate.assert_not_called()
                    open_control = next(iter(user.find(kind=ui.button, content='Open').elements))
                    import json
                    self.assertEqual(json.loads(open_control.props['data-open-urls']), [row['preview_url'] for row in table.selected])
                preview = await user.http_client.get(table.rows[0]['preview_url'])
                self.assertEqual(preview.status_code, 200)
                self.assertIn('Loading transaction log...', preview.text)
                self.assertNotIn('LogComparator - ' + table.rows[0]['transuid'], preview.text)
                self.assertIn('LogComparator - Transaction', preview.text)
                self.assertNotIn(table.rows[1]['transuid'], preview.text)
                user.find(kind=ui.button, content='Export').click()
                response = await user.download.next(timeout=10)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.content.startswith(b'PK'))
                with user:
                    selects['Bank/Acquirer'].set_value('AKTIF/BKTKOS')
                await user.should_see('Selected date:  2026-10-14  |  AKTIF/BKTKOS', retries=100)
                self.assertFalse(any(e.text == 'Settings' for e in user.find(ui.item_section).elements))
                user.find(marker='export-options-menu').click()
                await user.should_see('Export options')
                user.find(kind=ui.button, content='Close').click()
                self.assertFalse(any(e.text == 'Close workspace' for e in user.find(ui.item_section).elements))
                user.find(marker='import-menu').click()
                await user.should_see('Import local log folder')
                import_inputs = {e.props.get('label'): e for e in user.find(ui.input).elements}
                import_selects = {e.props.get('label'): e for e in user.find(ui.select).elements}
                with user:
                    import_selects['Import Bank/Acquirer'].set_value('AKTIF/BKT')
                user.find('Load Files').click()
                await user.should_see('Loaded transactions: 2', retries=100)
                from nicegui import run
                original_io_bound = run.io_bound

                publish_started = asyncio.Event()
                release_publish = asyncio.Event()

                async def slow_export(function, *args, **kwargs):
                    if function.__name__ == 'export_logs':
                        await asyncio.sleep(3.2)  # Longer than NiceGUI's page response timeout.
                    if function.__name__ == 'publish_exports':
                        publish_started.set()
                        await release_publish.wait()
                    return await original_io_bound(function, *args, **kwargs)

                from urllib.parse import urljoin
                preview_url = table.rows[0]['preview_url']
                with patch('nicegui.run.io_bound', side_effect=slow_export):
                    shell = await asyncio.wait_for(user.http_client.get(preview_url), timeout=2)
                    self.assertEqual(shell.status_code, 200)
                    self.assertIn('Loading transaction log...', shell.text)
                    self.assertNotIn('nicegui.js', shell.text)
                    self.assertNotIn('socket.io', shell.text)
                    self.assertNotIn('setInterval', shell.text)
                    self.assertNotIn('location.reload', shell.text)
                    data_url = preview_url.replace('/transaction/', '/transaction-data/', 1)
                    data = await asyncio.wait_for(user.http_client.get(data_url), timeout=6)
                    self.assertEqual(data.status_code, 200)
                    snapshot = data.json()
                    self.assertIn('asc<0810>', snapshot['text'])
                    await asyncio.wait_for(publish_started.wait(), timeout=2)
                    self.assertFalse(release_publish.is_set())
                    with patch('web_app.export_logs', side_effect=AssertionError('ready preview must be reused')):
                        ready = await user.http_client.get(data_url)
                    self.assertEqual(ready.json(), snapshot)
                    release_publish.set()
                    saved = await user.http_client.get(urljoin(preview_url, snapshot['save_url']))
                    self.assertEqual(saved.status_code, 200)
                    download = await user.http_client.get(urljoin(preview_url, snapshot['download_url']))
                    self.assertEqual(download.status_code, 200)
                    self.assertEqual(download.text.replace('\r\n', '\n'), snapshot['text'])
                    expired = await user.http_client.get('/transaction-data/expired?uid=test')
                    self.assertEqual(expired.status_code, 404)
            finally:
                await simulation.__aexit__(None, None, None)
                output_patch.stop()
                local_audit_patch.stop()
                local_log_patch.stop()


if __name__ == '__main__':
    unittest.main()
