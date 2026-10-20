import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import log_core as core
import source_memory


class ParallelParserTests(unittest.TestCase):
    def test_spawned_workers_preserve_transactions_locations_and_ram_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / 'audit.one', root / 'audit.two']
            content = []
            for file_index in range(2):
                blocks = []
                for i in range(30):
                    blocks.append('=' * 80 + '\nRP date time GMT : 2026-10-14 06:47:58\n'
                                  'Process name : OPNBISOBKT01\n'
                                  'Flow dir : TANGO-->NETWORK\nFlow type : request\n'
                                  f'transUId : asc<UID-{i % 7}>\n'
                                  'msgId : asc<0200>\nauditNumber : asc<000115>\n')
                blocks.append('=' * 80 + '\ntransUId : \n')
                content.append(''.join(blocks).encode())
                paths[file_index].write_bytes(content[-1])
            expected = core.scan_transactions_for_list(paths)
            key = core.input_paths_cache_key(paths)
            locations = core.AUDIT_BLOCK_LOCATION_CACHE[key]
            progress = []
            with patch.object(core, 'PARALLEL_AUDIT_MIN_BYTES', 0), \
                 patch.object(core, 'AUDIT_BATCH_BLOCKS', 3), \
                 patch.dict(os.environ, {'LOGCOMPARATOR_PARSE_WORKERS': '2'}):
                actual = core.scan_transactions_for_list(paths, lambda *args: progress.append(args))
                self.assertEqual(actual, expected)
                self.assertEqual(core.AUDIT_BLOCK_LOCATION_CACHE[key], locations)
                self.assertEqual(progress[-1][:2], (sum(map(len, content)),) * 2)
                archive = root / 'snapshot.tar.gz'
                source_memory.publish(archive, dict(zip(paths, content)))
                try:
                    self.assertEqual(core.scan_transactions_for_list(paths), expected)
                finally:
                    with source_memory._LOCK:
                        source_memory._GROUPS.pop(source_memory.key(archive), None)

    def test_interruption_does_not_publish_partial_locations(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'audit'
            path.write_text(('=' * 80 + '\ntransUId : asc<UID>\n') * 20)
            key = core.input_paths_cache_key([path])
            def interrupt(*args):
                raise RuntimeError('cancelled')
            with patch.object(core, 'PARALLEL_AUDIT_MIN_BYTES', 0), \
                 patch.object(core, 'AUDIT_BATCH_BLOCKS', 2), \
                 patch.dict(os.environ, {'LOGCOMPARATOR_PARSE_WORKERS': '2'}):
                with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                    core.scan_transactions_for_list([path], interrupt)
            self.assertNotIn(key, core.AUDIT_BLOCK_LOCATION_CACHE)

    def test_worker_configuration_is_bounded(self):
        for value, expected in [('1', 1), ('0', 1), ('100', 4), ('bad', 4)]:
            with patch.dict(os.environ, {'LOGCOMPARATOR_PARSE_WORKERS': value}), \
                 patch.object(core.os, 'cpu_count', return_value=8):
                self.assertEqual(core.audit_worker_count(), expected)
