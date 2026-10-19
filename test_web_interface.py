"""Optional web tests: install requirements-web.txt before running this module."""
import tempfile
import asyncio
import unittest
import os
from pathlib import Path

from web_services import comparison_diff, export_logs, filter_rows, inspect_local_sources, load_logs, with_settings


def source_fixture(folder):
    def block(flow, ref, mti):
        return ('=' * 80 + '\nRP date time GMT : 2026-10-14 06:47:58, timestamp: 20261014064758109\n'
                'Process name : OPNBISOBKT01\n'
                f"Flow dir : {'TANGO-->NETWORK' if flow == 'request' else 'NETWORK-->TANGO'}\n"
                f'Flow type : {flow}, ref: {ref}\nMessage type : out logon\n'
                f'msgId : asc<{mti}>\nnetworkManageCode : asc<001>\nauditNumber : asc<000115>\n'
                'responseCode : asc<00>\n')
    (folder / 'tango.log.2026-10-14').write_text('', encoding='utf-8')
    (folder / 'audit.OPNBISOBKT01.2026-10-14').write_text(
        ''.join(block('request', ref, '0800') + block('response', ref, '0810')
                for ref in ('123', '456')), encoding='utf-8')


class WebServicesTests(unittest.TestCase):
    def test_filesystem_watcher_detects_writes_and_stops(self):
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
            rows = filter_rows(loaded.rows, {'transuid': loaded.rows[0]['transuid']})
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
            with patch('sys.argv', ['web_app.py', '--no-browser']):
                simulation = user_simulation(main_file=Path(__file__).with_name('web_app.py'))
                user = await simulation.__aenter__()
            try:
                await user.open('/')
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
                dates = next(e for e in user.find(ui.select).elements if e.props.get('label') == 'Log date (auto for one date)')
                for _ in range(100):
                    if len(dates.options) == 2:
                        break
                    await asyncio.sleep(0.1)
                self.assertEqual(dates.options, ['2026-10-14', '2026-10-15'])
                with user:
                    dates.set_value('2026-10-14')
                user.find('Load folder').click()
                await user.should_see('Loaded transactions: 2', retries=100)
                table = next(iter(user.find(ui.table).elements))
                self.assertEqual(len(table.rows), 2)
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
                listing = Mock(side_effect=[UnknownHostKey('SHA256:test-host'), ([remote_name], ['tango.log.2026-10-14'])])

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
                    await user.should_see('SHA256:test-host', retries=100)
                    user.find('Trust this host fingerprint and connect').click()
                    await user.should_see('1 audit files; 1 Tango logs; 1 dates available.', retries=100)
                    self.assertEqual(listing.call_args.args[0].fingerprint, 'SHA256:test-host')
                    self.assertEqual(listing.call_args.args[0].audit_folder, '/opt/tango/MLNPSP01/audit')
                    self.assertEqual(listing.call_args.args[0].log_folder, '/opt/tango/MLNPSP01/log')
                    calendar = next(iter(user.find(marker='remote-import-calendar').elements))
                    self.assertEqual(calendar.props['events'], ['2026/10/14'])
                    self.assertEqual(calendar.props['options'], calendar.props['events'])
                    remote_bank = next(e for e in user.find(ui.select).elements if e.props.get('label') == 'Remote Bank/Acquirer')
                    with user:
                        remote_bank.set_value('All')
                    user.find('Read remote logs').click()
                    await user.should_see('Loaded transactions: 2', retries=100)
                    transfer.assert_called_once()
                    log_transfer.assert_called_once()
                    self.assertEqual(log_transfer.call_args.args[1], ['tango.log.2026-10-14'])
                    self.assertEqual(len(table.rows), 2)
                    live_control = next(iter(user.find(marker='live-update').elements))
                    self.assertTrue(live_control.enabled)
                    self.assertTrue(live_control.value)
                    await user.should_see('SSH live update reads all banks')
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
                    with user:
                        next(e for e in user.find(ui.select).elements if e.props.get('label') == 'Bank/Acquirer').set_value('AKTIF/BKTKOS')
                    await user.should_see('Selected date:  2026-10-14  |  AKTIF/BKTKOS', retries=100)
                    self.assertTrue(live_control.enabled)
                    user.find(marker='import-menu').click()
                    await user.should_see('Import local log folder')
                    user.find('Load folder').click()
                    await user.should_see('Loaded transactions: 4', retries=100)
                    self.assertTrue(live_control.enabled)
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
            with patch('sys.argv', ['web_app.py', '--no-browser']):
                simulation = user_simulation(main_file=Path(__file__).with_name('web_app.py'))
                user = await simulation.__aenter__()
            try:
                await user.open('/')
                inputs = {element.props.get('label'): element for element in user.find(ui.input).elements}
                self.assertFalse(any('Source date' in (label or '') for label in inputs))
                selects = {element.props.get('label'): element for element in user.find(ui.select).elements}
                self.assertEqual(selects['Timezone'].options, ['UTC-3', 'UTC-2', 'UTC-1', 'UTC', 'UTC+1', 'UTC+2', 'UTC+3'])
                with user:
                    inputs['Log folder'].set_value(str(folder))
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
                    local_inputs['Folder path'].set_value(str(folder))
                    local_selects['Import Bank/Acquirer'].set_value('AKTIF/BKT')
                user.find('Load folder').click()
                await user.should_see('Loaded transactions: 2', retries=100)
                table = next(iter(user.find(ui.table).elements))
                self.assertEqual(len(table.rows), 2)
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
                self.assertEqual(len(table.rows), 1)
                with user:
                    inputs['TransUID'].set_value('')
                    table.selected = []
                user.find(ui.table).trigger('selection', {'added': True, 'rows': list(table.rows), 'keys': [row['transuid'] for row in table.rows]})
                user.find(kind=ui.button, content='Compare').click()
                await user.should_see('Compare transactions', retries=100)
                await user.should_see(marker='diff2html-comparison')
                assets = await user.http_client.get('/logcomparator-assets/diff2html-ui-base.min.js')
                self.assertEqual(assets.status_code, 200)
                user.find('Close').click()
                with patch.object(user.navigate, 'to') as navigate:
                    user.find(kind=ui.button, content='Open').click()
                    await asyncio.sleep(0.1)
                    self.assertEqual(navigate.call_count, 2)
                    self.assertTrue(all(call.kwargs.get('new_tab') for call in navigate.call_args_list))
                preview = await user.http_client.get(table.rows[0]['preview_url'])
                self.assertEqual(preview.status_code, 200)
                self.assertIn('Download log', preview.text)
                self.assertIn(table.rows[0]['transuid'], preview.text)
                self.assertNotIn(table.rows[1]['transuid'], preview.text)
                user.find(kind=ui.button, content='Export').click()
                response = await user.download.next(timeout=10)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.content.startswith(b'PK'))
                with user:
                    selects['Bank/Acquirer'].set_value('AKTIF/BKTKOS')
                await user.should_see('Selected date:  2026-10-14  |  AKTIF/BKTKOS', retries=100)
                user.find(marker='settings-menu').click()
                await user.should_see('Output folder')
                settings_inputs = {e.props.get('label'): e for e in user.find(ui.input).elements}
                self.assertNotIn('SSH user', settings_inputs)
                self.assertNotIn('Sudo password (leave empty to keep current)', settings_inputs)
                with user:
                    settings_inputs['Output folder'].set_value(str(folder / 'saved'))
                user.find('Save settings').click()
                await user.should_see('Settings updated.')
                user.find(marker='export-options-menu').click()
                await user.should_see('Export options')
                user.find(kind=ui.button, content='Close').click()
                user.find(marker='close-workspace').click()
                self.assertEqual(table.rows, [])
                user.find(marker='import-menu').click()
                await user.should_see('Import local log folder')
                import_inputs = {e.props.get('label'): e for e in user.find(ui.input).elements}
                import_selects = {e.props.get('label'): e for e in user.find(ui.select).elements}
                with user:
                    import_inputs['Folder path'].set_value(str(folder))
                    import_selects['Import Bank/Acquirer'].set_value('AKTIF/BKT')
                user.find('Load folder').click()
                await user.should_see('Loaded transactions: 2', retries=100)
            finally:
                await simulation.__aexit__(None, None, None)
                output_patch.stop()


if __name__ == '__main__':
    unittest.main()
