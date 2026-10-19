"""Compare sparse-transaction lookup with the previous line-by-line search."""
import argparse
import tempfile
import time
from collections import defaultdict
from pathlib import Path

from log_core import collect_tango_lines


def previous_search(path, uids):
    result=defaultdict(list)
    targets={uid:uid.encode() for uid in uids}
    with path.open('rb') as stream:
        for line in stream:
            for uid,encoded in targets.items():
                if encoded in line:
                    result[uid].append(line.decode('utf-8',errors='replace'))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--size-mb',type=int,default=64)
    args=parser.parse_args()
    if args.size_mb<1:
        parser.error('--size-mb must be positive')
    target='BENCHMARK-TARGET-UID-0001'
    line=b'2026-10-19 | unrelated TANGO debug line | OTHER-TRANSACTION-UID | details\n'
    block=line*((1024*1024)//len(line))
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/'tango.log.2026-10-19'
        with path.open('wb') as stream:
            for index in range(args.size_mb):
                stream.write(block)
                stream.write(f'match {index} {target}\n'.encode())
        start=time.perf_counter()
        expected=previous_search(path,{target})
        baseline=time.perf_counter()-start
        start=time.perf_counter()
        actual=collect_tango_lines(path,{target})
        optimized=time.perf_counter()-start
        assert actual==expected
        print(f'Synthetic {path.stat().st_size/1024/1024:.1f} MiB log; identical {len(actual[target])} matching lines')
        print(f'Line-by-line: {baseline:.3f}s; chunk search: {optimized:.3f}s; speedup: {baseline/optimized:.1f}x')


if __name__=='__main__':
    main()
