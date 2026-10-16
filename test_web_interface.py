"""Optional web tests: install requirements-web.txt before running this module."""
import tempfile
import asyncio
import unittest
import os
from pathlib import Path

from web_services import export_logs, filter_rows, load_logs


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
                    table.selected = list(table.rows)
                user.find(kind=ui.button, content='Compare').click()
                await user.should_see('Compare transactions', retries=100)
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
            finally:
                await simulation.__aexit__(None, None, None)
                remote_patch.stop()
                listing_patch.stop()
                background_patch.stop()


if __name__ == '__main__':
    unittest.main()
