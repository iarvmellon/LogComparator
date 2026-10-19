import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from windows_runtime import configure_standard_streams


class WindowlessRuntimeTests(unittest.TestCase):
    def test_windowless_logging_and_existing_console(self):
        original_stdout = sys.stdout
        self.assertIsNone(configure_standard_streams())
        self.assertIs(sys.stdout, original_stdout)
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict('os.environ', {'LOCALAPPDATA': folder}), \
                    patch('sys.stdout', None), patch('sys.stderr', None):
                stream = configure_standard_streams()
                try:
                    print('server ready')
                    print('diagnostic', file=sys.stderr)
                    self.assertFalse(stream.isatty())
                    stream.flush()
                finally:
                    stream.close()
            self.assertEqual((Path(folder) / 'LogComparator' / 'LogComparator.log').read_text(),
                             'server ready\ndiagnostic\n')
