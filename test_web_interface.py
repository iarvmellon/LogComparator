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
                                'LOCAL_AUDIT_DIR': audits, 'DEFAULT_OUTPUT': root / 'exports'}.items():
                stack.enter_context(patch('log_core.' + name, value))
            with patch('sys.argv', ['web_app.py', '--no-browser']):
                simulation = user_simulation(main_file=Path(__file__).with_name('web_app.py'))
                user = await simulation.__aenter__()
            try:
                await user.open('/')
                await user.should_not_see(marker='ssh-menu')
                user.find(marker='import-menu').click()
                await user.should_see('Import local log folder', retries=100)
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
            remote_patch = patch('gui_services.download_uat_sources', return_value=folder)
            remote_download = remote_patch.start()
            background_patch = patch('gui_services.download_remaining_uat_audits')
            background_download = background_patch.start()
            output_patch = patch('log_core.DEFAULT_OUTPUT', folder / 'exports')
            output_patch.start()
            listing_patch = patch('gui_services.list_remote_logs', return_value=[
                '/uat/tango.log.2026-10-14.gz', '/uat/tango.log.2026-10-12',
                '/uat/tango.log.2026-10-14.part2.gz', '/uat/unrelated'])
            listing = listing_patch.start()
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
                # File > SSH lists available dates before contacting UAT for a download.
                user.find(marker='ssh-menu').click()
                await user.should_see('2 available dates', retries=100)
                calendar = next(iter(user.find(ui.date).elements))
                self.assertEqual(calendar.props['options'], ['2026/10/12', '2026/10/14'])
                self.assertEqual(calendar.props['events'], calendar.props['options'])
                await user.should_see('tango.log.2026-10-14.gz')
                remote_download.assert_not_called()
                user.find('Cancel').click()
                remote_download.assert_not_called()
                user.find(marker='ssh-menu').click()
                await user.should_see('2 available dates', retries=100)
                ssh_date = max((e for e in user.find(ui.input).elements if e.props.get('label') == 'SSH date'), key=lambda e: e.id)
                self.assertTrue(ssh_date.props['readonly'])
                with user:
                    ssh_date.set_value('2026-10-14')
                user.find('Download and load').click()
                await user.should_see('Loaded transactions: 2', retries=100)
                remote_download.assert_called_once()
                self.assertEqual(remote_download.call_args.args[:2], ('2026-10-14', 'AKTIF/BKT'))
                await user.should_see('Background audits ready for all banks', retries=100)
                background_download.assert_called_once()
                self.assertEqual(background_download.call_args.args[:2], ('2026-10-14', folder.resolve()))
                self.assertEqual(selects['Bank/Acquirer'].value, 'AKTIF/BKT')
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
                user.find(marker='ssh-menu').click()
                await user.should_see('2 available dates', retries=100)
                listing.return_value = []
                user.find(kind=ui.button, content='Refresh dates').click()
                await user.should_see('No dated Tango log files found on UAT.', retries=100)
                download_button = max((e for e in user.find(ui.button).elements if e.props.get('label') == 'Download and load'), key=lambda e: e.id)
                self.assertFalse(download_button.enabled)
                listing.side_effect = OSError('test SSH connection failure')
                user.find(kind=ui.button, content='Refresh dates').click()
                await user.should_see('Could not list UAT logs:', retries=100)
                self.assertFalse(download_button.enabled)
                with user:
                    selects['Bank/Acquirer'].set_value('AKTIF/BKTKOS')
                await user.should_see('Selected date:  2026-10-14  |  AKTIF/BKTKOS', retries=100)
                self.assertEqual(remote_download.call_count, 1)
                user.find(marker='settings-menu').click()
                await user.should_see('SSH user')
                settings_inputs = {e.props.get('label'): e for e in user.find(ui.input).elements}
                self.assertFalse(settings_inputs['Sudo password (leave empty to keep current)'].value)
                with user:
                    settings_inputs['Output folder'].set_value(str(folder / 'saved'))
                    settings_inputs['SSH user'].set_value('web-user')
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
                self.assertEqual(remote_download.call_count, 1)
                listing.side_effect = None
                listing.return_value = ['/uat/tango.log.2026-10-14.gz']
                user.find(marker='ssh-menu').click()
                await user.should_see('1 available dates', retries=100)
                ssh_banks = max((e for e in user.find(ui.select).elements if e.props.get('label') == 'SSH Bank/Acquirer'), key=lambda e: e.id)
                with user:
                    ssh_banks.set_value('All')
                user.find('Download and load').click()
                await user.should_see('All available banks downloaded.', retries=100)
                self.assertEqual(remote_download.call_args.args[:2], ('2026-10-14', 'All'))
                self.assertEqual(background_download.call_count, 1)
            finally:
                await simulation.__aexit__(None, None, None)
                remote_patch.stop()
                listing_patch.stop()
                background_patch.stop()
                output_patch.stop()


if __name__ == '__main__':
    unittest.main()
