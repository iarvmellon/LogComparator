import io
import json
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch

import log_core as core
import source_memory


class LargeLogTests(unittest.TestCase):
    def test_chunk_search_preserves_all_matching_lines_and_boundary_cases(self):
        content = (b'ignored line\n' + b'prefix-XABC-suffix ABC twice\r\n'
                   + b'long ' + b'x'*177 + b' ABC other DEF\n'
                   + b'invalid \xff ABC\n' + b'DEF '+chr(0x03b1).encode() + b'\nlast ABC')
        expected = defaultdict(list)
        for line in content.splitlines(keepends=True):
            for uid in ('ABC', 'DEF', 'missing'):
                if uid.encode() in line:
                    expected[uid].append(line.decode('utf-8', errors='replace'))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'tango.log.2026-10-14'
            path.write_bytes(content)
            for size in (1, 7, 32, 256):
                with self.subTest(chunk_size=size), patch.object(core, 'TANGO_READ_CHUNK_SIZE', size):
                    self.assertEqual(core.collect_tango_lines(path, {'ABC','DEF','missing'}), expected)
            memory = Path(directory) / 'memory.log'
            source_memory.publish(Path(directory)/'snapshot.tar.gz', {memory: content})
            try:
                with patch.object(core, 'TANGO_READ_CHUNK_SIZE', 7):
                    self.assertEqual(core.collect_tango_lines(memory, {'ABC','DEF','missing'}), expected)
            finally:
                # Remove just this fixture's in-memory source group.
                with source_memory._LOCK:
                    source_memory._GROUPS.pop(source_memory.key(Path(directory)/'snapshot.tar.gz'), None)

    def test_preview_chunks_preserve_utf8_and_do_not_read_the_whole_file(self):
        import web_app
        raw = (('abc'+chr(0x03b1)+chr(0x1F600)+'\r\n')*23).encode() + b'bad\xfflast'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'transaction.log'
            path.write_bytes(raw)
            with patch.object(web_app,'PREVIEW_CHUNK_SIZE',7):
                offset=0
                parts=[]
                while True:
                    chunk=web_app.read_preview_chunk(path,offset)
                    parts.append(chunk['text'])
                    self.assertEqual(chunk['total_bytes'],len(raw))
                    self.assertLessEqual(chunk['next_offset']-offset,7)
                    if not chunk['has_more']:
                        break
                    self.assertGreater(chunk['next_offset'],offset)
                    offset=chunk['next_offset']
            self.assertEqual(''.join(parts),raw.decode('utf-8',errors='replace').replace('\r\n','\n').replace('\r','\n'))
            with self.assertRaises(ValueError):
                web_app.read_preview_chunk(path,-1)
            with self.assertRaises(ValueError):
                web_app.read_preview_chunk(path,len(raw)+1)
            path.write_bytes(b'x'*(web_app.PREVIEW_CHUNK_SIZE*4))
            first=web_app.read_preview_chunk(path)
            self.assertEqual(len(first['text']),web_app.PREVIEW_CHUNK_SIZE)
            self.assertTrue(first['has_more'])
            self.assertEqual(first['total_bytes'],web_app.PREVIEW_CHUNK_SIZE*4)


class ChunkEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_chunk_endpoint_handles_expired_tokens_and_preserves_full_download(self):
        import web_app
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'large.log'
            path.write_bytes(b'initial\nremaining\n')
            web_app.PREVIEW_DOWNLOADS['large-log-test']=path
            try:
                with patch.object(web_app,'PREVIEW_CHUNK_SIZE',8):
                    result=await web_app.transaction_chunk('large-log-test',8)
                self.assertEqual(json.loads(result.body)['text'],'remainin')
                self.assertTrue(json.loads(result.body)['has_more'])
                download=web_app.transaction_download('large-log-test')
                self.assertEqual(Path(download.path).read_bytes(),b'initial\nremaining\n')
                self.assertEqual((await web_app.transaction_chunk('large-log-test',-1)).status_code,400)
                self.assertEqual((await web_app.transaction_chunk('expired-large-log',0)).status_code,404)
            finally:
                web_app.PREVIEW_DOWNLOADS.pop('large-log-test',None)
