import gzip
import io
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import source_memory
from remote_logs import _mirror_file, RemoteConnection, RemoteSourceWatcher
from web_services import load_logs, export_logs
from test_web_interface import source_fixture

class RemoteMemoryTests(unittest.TestCase):
    @patch("remote_logs.core.current_log_date", return_value="2026-10-14")
    def test_archive_load_and_export_without_source_files(self, today):
        with tempfile.TemporaryDirectory() as fixture, tempfile.TemporaryDirectory() as target:
            source_fixture(Path(fixture))
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode='w:gz') as archive:
                for path in Path(fixture).iterdir():
                    archive.add(path, arcname='logs/' + path.name)
            payload = stream.getvalue()
            class SFTP:
                def stat(self, path):
                    return SimpleNamespace(st_size=len(payload), st_mtime=1)
                def open(self, path, mode):
                    return io.BytesIO(payload)
            local = Path(target) / 'audit.OPNBISOBKT01.2026-10-14.tar.gz'
            _mirror_file(SFTP(), '/archive', local)
            self.assertEqual(list(Path(target).iterdir()), [])
            loaded = load_logs(Path(target), 'AKTIF/BKT', '2026-10-14')
            self.assertEqual(len(loaded.rows), 2)
            with tempfile.TemporaryDirectory() as output:
                paths = export_logs(loaded, [row['transuid'] for row in loaded.rows], Path(output))
                self.assertTrue(paths)
                self.assertTrue(all(path.is_file() for path in paths))
            self.assertEqual(list(Path(target).iterdir()), [])
            # Corrupt and cancelled updates cannot replace a usable snapshot.
            original = source_memory.snapshot(loaded.audits[0])[0]
            payload = b'corrupt'
            with self.assertRaises((tarfile.TarError, OSError)):
                _mirror_file(SFTP(), '/archive', local)
            self.assertEqual(source_memory.snapshot(loaded.audits[0])[0], original)
            stop = threading.Event(); stop.set()
            payload = gzip.compress(b'replacement')
            _mirror_file(SFTP(), '/gzip', local.with_name('audit.OPNBISOBKT01.2026-10-14.gz'), stop)
            self.assertEqual(source_memory.snapshot(loaded.audits[0])[0], original)

    @patch('remote_logs.core.current_log_date', return_value='2026-10-19')
    def test_historical_sources_download_and_extract_locally(self, today):
        with tempfile.TemporaryDirectory() as fixture, tempfile.TemporaryDirectory() as target:
            source_fixture(Path(fixture))
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode='w:gz') as archive:
                for path in Path(fixture).iterdir():
                    archive.add(path, arcname='logs/' + path.name)
            payload = stream.getvalue()
            class SFTP:
                def stat(self, path):
                    return SimpleNamespace(st_size=len(payload), st_mtime=1)
                def open(self, path, mode):
                    return io.BytesIO(payload)
            local = Path(target) / 'audit.OPNBISOBKT01.2026-10-14.tar.gz'
            _mirror_file(SFTP(), '/archive', local)
            self.assertEqual(local.read_bytes(), payload)
            loaded = load_logs(Path(target), 'AKTIF/BKT', '2026-10-14')
            self.assertEqual(len(loaded.rows), 2)
            self.assertTrue(all(path.is_file() for path in loaded.audits + loaded.tango_logs))
            self.assertTrue(all(source_memory.snapshot(path) is None for path in loaded.audits))
            payload = gzip.compress(b'historical gzip')
            zipped = Path(target) / 'tango.log.2026-10-13.gz'
            _mirror_file(SFTP(), '/gzip', zipped)
            self.assertEqual(zipped.read_bytes(), payload)
            self.assertEqual(zipped.with_suffix('').read_bytes(), b'historical gzip')
            payload = b'historical plain'
            plain = Path(target) / 'tango.log.2026-10-12'
            _mirror_file(SFTP(), '/plain', plain)
            self.assertEqual(plain.read_bytes(), payload)

    def test_ready_bank_cache_reuses_checks_and_invalidates_changed_sources(self):
        import web_services
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source_fixture(folder)
            with patch('web_services.build_problem_columns', wraps=web_services.build_problem_columns) as checks:
                first = load_logs(folder, 'AKTIF/BKT', '2026-10-14')
                first.rows[0]['possibleproblem'] = 'client edit'
                second = load_logs(folder, 'AKTIF/BKT', '2026-10-14')
                self.assertEqual(checks.call_count, 1)
                self.assertNotEqual(second.rows[0]['possibleproblem'], 'client edit')
                tango = folder / 'tango.log.2026-10-14'
                tango.write_text('changed Tango diagnostics')
                load_logs(folder, 'AKTIF/BKT', '2026-10-14')
                self.assertEqual(checks.call_count, 2)
                audit = next(folder.glob('audit.*'))
                audit.write_bytes(audit.read_bytes() + b'\n')
                load_logs(folder, 'AKTIF/BKT', '2026-10-14')
                self.assertEqual(checks.call_count, 3)

    def test_background_prepares_bank_and_ready_hit_bypasses_parser_lock(self):
        import web_services
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source_fixture(folder)
            stop = threading.Event()
            web_services.prepare_bank_results(folder, ['AKTIF/BKTKOS'], '2026-10-14', stop)
            locked, release = threading.Event(), threading.Event()

            def hold_parser():
                with web_services.CORE_LOCK:
                    locked.set()
                    release.wait(5)

            worker = threading.Thread(target=hold_parser)
            worker.start()
            self.assertTrue(locked.wait(3))
            try:
                # A ready bank must be available even while another parser holds CORE_LOCK.
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(web_services.load_logs, folder, 'AKTIF/BKTKOS', '2026-10-14')
                    try:
                        result = future.result(timeout=1)
                    finally:
                        release.set()
                self.assertEqual(result.bank, 'AKTIF/BKTKOS')
                self.assertTrue(result.rows)
            finally:
                release.set()
                worker.join(3)

    def test_background_analysis_yields_at_checkpoint_for_foreground(self):
        import web_services
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source_fixture(folder)
            original = web_services.core.scan_transactions_for_list

            def foreground_arrives(paths, progress):
                web_services.FOREGROUND_PENDING.set()
                return original(paths, progress)

            try:
                with patch('web_services.core.scan_transactions_for_list', side_effect=foreground_arrives):
                    result = web_services.load_logs(folder, 'AKTIF/BKT', '2026-10-14', background=True)
                self.assertIsNone(result)
                self.assertFalse(any(key[0] == str(folder) for key in web_services.LOADED_CACHE))
            finally:
                web_services.FOREGROUND_PENDING.clear()
            self.assertTrue(web_services.load_logs(folder, 'AKTIF/BKT', '2026-10-14').rows)

    def test_watcher_skips_other_banks(self):
        names = ['audit.OPNBISOBKT01.2026-10-14', 'audit.OPNOTHER01.2026-10-14', 'audit.PTMS01.20261014']
        settings = RemoteConnection('localhost', 'test', '')
        class SFTP:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def get_channel(self): return self
            def settimeout(self, value): pass
            def listdir_attr(self, root):
                return [SimpleNamespace(filename=n, st_mode=0o100644) for n in names] if root == settings.audit_folder else []
        class Client(SFTP):
            def get_transport(self): return self
            def set_keepalive(self, value): pass
            def open_sftp(self): return SFTP()
            def close(self): pass
        with tempfile.TemporaryDirectory() as folder, patch('remote_logs.connect', return_value=Client()), patch('remote_logs.open_sftp', return_value=SFTP()), patch('remote_logs.core.current_log_date', return_value='2026-10-14'), patch('remote_logs._mirror_file', return_value=(True, (1, 1))) as read:
            watcher = RemoteSourceWatcher(settings, '2026-10-14', folder, interval=10, bank='AKTIF/BKT')
            try:
                self.assertTrue(watcher.changed.wait(3))
            finally:
                watcher.close(); watcher.thread.join(3)
            self.assertEqual({call.args[2].name for call in read.call_args_list}, {names[0], names[2]})
