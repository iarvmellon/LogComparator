import gzip
import tempfile
import threading
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from gui_services import download_remaining_uat_audits


class BackgroundAuditTests(unittest.TestCase):
    def test_downloads_other_banks_and_publishes_extracted_files(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / 'audit.PTMS01.day').write_text('selected')
            paths = ['/logs/tango.log.day', '/audit/audit.PTMS01.day',
                     '/audit/audit.OPN02.day.gz']

            def download(remote, staging):
                self.assertFalse((target / 'audit.OPN02.day').exists())
                path = staging / Path(remote).name
                with gzip.open(path, 'wb') as stream:
                    stream.write(b'other bank')
                return path

            with patch('gui_services.list_remote_uat_sources', return_value=paths), \
                 patch('gui_services.download_remote_file', side_effect=download) as mocked:
                download_remaining_uat_audits(date.today().isoformat(), target,
                                              {'audit.PTMS01.day'})
            self.assertEqual(mocked.call_count, 1)
            self.assertEqual((target / 'audit.OPN02.day').read_text(), 'other bank')
            self.assertEqual((target / 'audit.PTMS01.day').read_text(), 'selected')
            self.assertFalse(any(p.is_dir() for p in target.iterdir()))

    def test_failure_does_not_publish_partial_file_and_continues(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)

            def download(remote, staging):
                path = staging / Path(remote).name
                path.write_text('data')
                if 'OPN01' in remote:
                    raise RuntimeError('connection lost')
                return path

            with patch('gui_services.list_remote_uat_sources', return_value=[
                    '/audit/audit.OPN01.day', '/audit/audit.OPN02.day']), \
                 patch('gui_services.download_remote_file', side_effect=download):
                with self.assertRaisesRegex(RuntimeError, 'connection lost'):
                    download_remaining_uat_audits('2020-01-01', target, set())
            self.assertFalse((target / 'audit.OPN01.day').exists())
            self.assertTrue((target / 'audit.OPN02.day').exists())

    def test_cancelled_download_does_not_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            cancel = threading.Event()

            def download(remote, staging):
                path = staging / Path(remote).name
                path.write_text('data')
                cancel.set()
                return path

            with patch('gui_services.list_remote_uat_sources', return_value=['/audit/audit.OPN01.day']), \
                 patch('gui_services.download_remote_file', side_effect=download):
                download_remaining_uat_audits('2020-01-01', target, set(), cancel_event=cancel)
            self.assertEqual(list(target.iterdir()), [])

    def test_historical_files_are_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / 'audit.OPN01.day').write_text('cached')
            with patch('gui_services.list_remote_uat_sources', return_value=['/audit/audit.OPN01.day']), \
                 patch('gui_services.download_remote_file') as mocked:
                download_remaining_uat_audits('2020-01-01', target, set())
            mocked.assert_not_called()


if __name__ == '__main__':
    unittest.main()
