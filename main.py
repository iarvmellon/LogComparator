from __future__ import annotations

import argparse
from pathlib import Path

from gui_app import run_gui_workflow
from log_core import DEFAULT_OUTPUT, PROTOCOL_CHOICES, split_audit_files


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load and split TANGO audit logs into complete transaction flows."
    )
    parser.add_argument(
        "input",
        nargs="*",
        type=Path,
        help="Optional local audit files. Without inputs, the GUI application opens.",
    )
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--tango-log",
        type=Path,
        help="Optional local tango.log whose matching TransUID lines are prepended.",
    )
    parser.add_argument(
        "--protocol",
        choices=PROTOCOL_CHOICES,
        help="Export only the selected protocol blocks: SPDH/PTMS, ISO/OPN, or both.",
    )
    parser.add_argument("--stan", help="Export only transactions matching this STAN.")
    parser.add_argument("--rrn", help="Export only transactions matching this RRN.")
    parser.add_argument("--authcode", help="Export only transactions matching this AuthCode.")
    parser.add_argument(
        "--sequence-number",
        help="Export only transactions matching this Sequence_Number.",
    )
    parser.add_argument(
        "--response-code-spdh",
        help="Export only transactions matching this SPDH response code.",
    )
    parser.add_argument(
        "--response-code-iso",
        help="Export only transactions matching this ISO response code.",
    )
    parser.add_argument(
        "--exclude-byte-data",
        action="store_true",
        help="Remove Raw data (hex) and Bus data sections from exported logs.",
    )
    parser.add_argument(
        "--exclude-internal",
        action="store_true",
        help="Exclude internal TANGO request/action blocks from exported logs.",
    )
    parser.add_argument(
        "--exclude-tango-to-network",
        action="store_true",
        help="Exclude TANGO->NETWORK blocks from exported logs.",
    )
    parser.add_argument(
        "--exclude-network-to-tango",
        action="store_true",
        help="Exclude NETWORK->TANGO blocks from exported logs.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.output.expanduser().resolve()
    if not args.input:
        return run_gui_workflow(output_dir)

    input_paths = [path.expanduser().resolve() for path in args.input]
    missing = [path for path in input_paths if not path.is_file()]
    if missing:
        raise SystemExit(f"Input file not found: {missing[0]}")

    tango_log_path = (
        args.tango_log.expanduser().resolve()
        if args.tango_log
        else None
    )
    if tango_log_path is not None and not tango_log_path.is_file():
        raise SystemExit(f"Tango log file not found: {tango_log_path}")

    stats = split_audit_files(
        input_paths,
        output_dir,
        tango_log_path=tango_log_path,
        protocol_choice=args.protocol,
        stan=args.stan,
        rrn=args.rrn,
        authcode=args.authcode,
        sequence_number=args.sequence_number,
        response_code_spdh=args.response_code_spdh,
        response_code_iso=args.response_code_iso,
        include_byte_data=not args.exclude_byte_data,
        include_internal=not args.exclude_internal,
        include_tango_to_network=not args.exclude_tango_to_network,
        include_network_to_tango=not args.exclude_network_to_tango,
    )
    print(f"Inputs: {len(input_paths)}")
    print(f"Output: {output_dir}")
    print(f"Protocol: {args.protocol or 'ALL'}")
    print(f"STAN: {args.stan or 'ALL'}")
    print(f"RRN: {args.rrn or 'ALL'}")
    print(f"AuthCode: {args.authcode or 'ALL'}")
    print(f"Sequence_Number: {args.sequence_number or 'ALL'}")
    print(f"responseCodeSPDH: {args.response_code_spdh or 'ALL'}")
    print(f"responseCodeISO: {args.response_code_iso or 'ALL'}")
    print(f"Byte/Data: {'EXCLUDED' if args.exclude_byte_data else 'INCLUDED'}")
    print(f"Transactions: {stats['transactions']}")
    print(f"Transaction blocks: {stats['transaction_blocks']}")
    print(f"Correlated blocks without transUId: {stats['correlated_blocks']}")
    print(f"NO_TRANSUID blocks: {stats['no_transuid_blocks']}")
    print(f"Tango lines prepended: {stats['tango_lines']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
