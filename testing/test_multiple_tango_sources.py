import tempfile
import unittest
from pathlib import Path

import log_core as core
import source_memory
from web_services import LoadedLogs, export_logs, comparison_diff


class MultipleTangoSourceTests(unittest.TestCase):
    def test_export_includes_later_files_and_keeps_transactions_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit = root / 'audit.OPNBISOBKT01.2026-10-14'
            audit.write_text(''.join('=' * 80 + '\n'
                'RP date time GMT : 2026-10-14 06:47:58\n'
                'Process name : OPNBISOBKT01\n'
                'Flow dir : TANGO-->NETWORK\nFlow type : request\n'
                f'transUId : {uid}\nmsgId : asc<0200>\n'
                for uid in ('TRX-A', 'TRX-B')))
            first, second, third = [root / name for name in ('first.log', 'second.log', 'third.log')]
            first.write_text('TRX-B first-bank-line\n')
            second.write_text('TRX-A second-bank-line\nTRX-B other-bank-line\n')
            third.write_text('TRX-A rotated-bank-line')
            loaded = LoadedLogs(root, 'AKTIF/BKT', '2026-10-14', [audit],
                                [first, second, third, second],
                                [{'transuid': 'TRX-A'}, {'transuid': 'TRX-B'}])
            paths = export_logs(loaded, ['TRX-A', 'TRX-B'], root / 'out')
            left, right = [path.read_text() for path in paths]
            self.assertEqual(left.count('TRX-A second-bank-line'), 1)
            self.assertEqual(left.count('TRX-A rotated-bank-line'), 1)
            self.assertLess(left.index('second-bank-line'), left.index('rotated-bank-line'))
            self.assertNotIn('TRX-B', left)
            self.assertIn('TRX-B first-bank-line', right)
            self.assertIn('TRX-B other-bank-line', right)
            self.assertNotIn('TRX-A', right)
            diff = comparison_diff(left, right, 'a.log', 'b.log')
            self.assertIn('-TRX-A second-bank-line', diff)
            self.assertIn('+TRX-B first-bank-line', diff)
            legacy = root / 'legacy'
            stats = core.split_audit_files([audit], legacy, transaction_uids={'TRX-A'},
                                           tango_log_path=second)
            self.assertEqual(stats['tango_lines'], 1)
            self.assertIn('second-bank-line', (legacy / 'TRX-A.log').read_text())

    def test_memory_sources_and_missing_sources_preserve_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second, archive = root / 'one', root / 'two', root / 'snapshot.tar.gz'
            source_memory.publish(archive, {first: b'TRX-A one\n', second: b'TRX-A two\n'})
            try:
                result = core.collect_tango_lines_from_sources(
                    [first, root / 'missing', second, first], {'TRX-A'})
                self.assertEqual(result['TRX-A'], ['TRX-A one\n', 'TRX-A two\n'])
                self.assertEqual(core.collect_tango_lines_from_sources([], {'TRX-A'}), {})
            finally:
                with source_memory._LOCK:
                    source_memory._GROUPS.pop(source_memory.key(archive), None)
