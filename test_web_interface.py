"""Optional web tests: install requirements-web.txt before running this module."""
import tempfile
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
            with patch('sys.argv', ['web_app.py', '--no-browser']):
                simulation = user_simulation(main_file=Path(__file__).with_name('web_app.py'))
                user = await simulation.__aenter__()
            try:
                await user.open('/')
                inputs = {element.props.get('label'): element for element in user.find(ui.input).elements}
                selects = {element.props.get('label'): element for element in user.find(ui.select).elements}
                with user:
                    inputs['Log folder'].set_value(str(folder))
                    selects['Bank/Acquirer'].set_value('AKTIF/BKT')
                user.find('Load').click()
                await user.should_see('Loaded transactions: 2', retries=100)
                table = next(iter(user.find(ui.table).elements))
                self.assertEqual(len(table.rows), 2)
                self.assertEqual(table.columns[-1]['label'], 'Possible problem')
                with user:
                    inputs['TransUID'].set_value(table.rows[0]['transuid'])
                self.assertEqual(len(table.rows), 1)
                with user:
                    inputs['TransUID'].set_value('')
                    table.selected = list(table.rows)
                user.find(kind=ui.button, content='Compare').click()
                await user.should_see('Compare transactions', retries=100)
                user.find('Close').click()
                user.find(kind=ui.button, content='Open').click()
                await user.should_see('Transaction logs', retries=100)
                user.find('Close').click()
                user.find(kind=ui.button, content='Export').click()
                response = await user.download.next(timeout=10)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.content.startswith(b'PK'))
            finally:
                await simulation.__aexit__(None, None, None)


if __name__ == '__main__':
    unittest.main()
