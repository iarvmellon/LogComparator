"""Synthetic parallel audit benchmark; run as a module from the project root."""
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
import log_core as core


def main():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'audit.benchmark'
        block = ('='*80 + '\nRP date time GMT : 2026-10-14 06:47:58\n'
                 'Process name : OPNBISOBKT01\nFlow dir : TANGO-->NETWORK\n'
                 'Flow type : request\ntransUId : asc<BENCH>\n'
                 'msgId : asc<0200>\nauditNumber : asc<000115>\n'
                 + ''.join(f'<field name="field{i}">value{i}</field>\n' for i in range(30)))
        path.write_text(block * 30000)
        times = []
        expected = None
        for workers in (1, 2):
            with patch.dict(os.environ, {'LOGCOMPARATOR_PARSE_WORKERS': str(workers)}), \
                 patch.object(core, 'PARALLEL_AUDIT_MIN_BYTES', 0):
                start = time.perf_counter()
                result = core.scan_transactions_for_list([path])
                times.append(time.perf_counter()-start)
                if expected is None:
                    expected = result
                else:
                    assert result == expected
        print(f'{path.stat().st_size / 1024**2:.1f} MiB, 30000 blocks: sequential {times[0]:.2f}s; 2 workers {times[1]:.2f}s; ratio {times[0]/times[1]:.2f}x')


if __name__ == '__main__':
    main()
