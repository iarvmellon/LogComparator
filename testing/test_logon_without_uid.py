import tempfile
import unittest
from pathlib import Path
from log_core import (parse_block, parse_block_for_list, scan_transactions_for_list,
                      scan_transactions, split_audit_files, transaction_matches_bank,
                      select_transaction_type, Transaction)


def block(flow, ref="123", process="OPNBISOBKT01", code="001", mti="0800"):
    return ("=" * 80 + "\nRP date time GMT : 2026-10-14 06:47:58, timestamp: 20261014064758109\n"
            f"Process name : {process}\nFlow dir : {'TANGO-->NETWORK' if flow == 'request' else 'NETWORK-->TANGO'}\n"
            f"Flow type : {flow}, ref: {ref}\nMessage type : out logon\n"
            f"msgId : asc<{mti}>\nnetworkManageCode : asc<{code}>\nauditNumber : asc<000115>\n")


class LogonWithoutUidTests(unittest.TestCase):
    def test_parser_variants_and_shared_bank_link(self):
        for parser in (parse_block, parse_block_for_list):
            request = parser(block("request"), 0)
            response = parser(block("response", mti="0810"), 1)
            self.assertTrue(request.trans_uid.startswith("LOGON-"))
            self.assertEqual(request.trans_uid, response.trans_uid)
            transaction = Transaction(request.trans_uid, 0)
            transaction.add(request); transaction.add(response)
            self.assertEqual(select_transaction_type(transaction), "LOGON (ISOreq-ISOresp)")
            self.assertTrue(transaction_matches_bank(transaction, "AKTIF/BKT"))
            self.assertTrue(transaction_matches_bank(transaction, "AKTIF/BKTKOS"))
            self.assertFalse(transaction_matches_bank(transaction, "NEXI/ALPHA"))
            transaction.acquirer_ids = {"065"}
            self.assertFalse(transaction_matches_bank(transaction, "AKTIF/BKT"))

    def test_complete_outbound_logon_is_green_for_both_parsers(self):
        from transaction_checks import build_problem_columns, is_successful_protocol_only
        from diagnostic_common import problem_row_tag
        for parser in (parse_block, parse_block_for_list):
            for rc in ('', 'responseCode : asc<00>\n'):
                request = parser(block('request'), 0)
                response = parser(block('response', mti='810') + rc, 1)
                self.assertEqual(response.trans_uid, request.trans_uid)
                transaction = Transaction(request.trans_uid, 0)
                transaction.add(request); transaction.add(response)
                problems = build_problem_columns([transaction])[transaction.trans_uid]
                self.assertEqual(problems, ('', ''))
                self.assertTrue(is_successful_protocol_only(transaction))
                self.assertEqual(problem_row_tag('', '', '', protocol_only_success=is_successful_protocol_only(transaction)), 'approved')

    def test_standalone_inbound_logon_is_green(self):
        from transaction_checks import build_problem_columns, is_successful_protocol_only
        from diagnostic_common import problem_row_tag
        for parser in (parse_block, parse_block_for_list):
            for mti in ('800', '0800'):
                incoming = parser(block('request', mti=mti).replace('TANGO-->NETWORK', 'NETWORK-->TANGO'), 0)
                self.assertTrue(incoming.trans_uid.startswith('LOGON-'))
                transaction = Transaction(incoming.trans_uid, 0)
                transaction.add(incoming)
                problems = build_problem_columns([transaction])[transaction.trans_uid]
                self.assertEqual(problems, ('', ''))
                self.assertTrue(is_successful_protocol_only(transaction))
                self.assertEqual(problem_row_tag('', '', '', protocol_only_success=is_successful_protocol_only(transaction)), 'approved')

    def test_logon_rows_are_green_in_web_results(self):
        from web_services import load_logs
        for content in (block('request', mti='800') + block('response', mti='810'),
                        block('request', mti='800').replace('TANGO-->NETWORK', 'NETWORK-->TANGO')):
            with tempfile.TemporaryDirectory() as directory:
                folder = Path(directory)
                (folder / 'tango.log.2026-10-14').write_text('')
                (folder / 'audit.OPNBISOBKT01.2026-10-14').write_text(content)
                loaded = load_logs(folder, 'AKTIF/BKT', '2026-10-14')
                self.assertEqual(len(loaded.rows), 1)
                self.assertEqual(loaded.rows[0]['transuid_display'], '')
                self.assertTrue(loaded.rows[0]['transuid'].startswith('LOGON-'))
                from web_services import filter_rows, render_results_report
                self.assertEqual(filter_rows(loaded.rows, {'transuid': 'LOGON-'}), [])
                report = render_results_report(loaded.rows, [('transuid', 'TransUID')], [])
                self.assertNotIn(loaded.rows[0]['transuid'], report)
                self.assertEqual(loaded.rows[0]['severity'], 'approved')
                self.assertEqual(loaded.rows[0]['possibleproblem'], '')

    def test_incomplete_reversed_and_declined_logon_are_not_green(self):
        from transaction_checks import is_successful_protocol_only, build_problem_columns
        from diagnostic_common import problem_row_tag
        request = parse_block_for_list(block('request'), 0)
        for response in (None,
                         block('response', mti='0810').replace('NETWORK-->TANGO', 'TANGO-->NETWORK'),
                         block('response', mti='0810') + 'responseCode : asc<05>\n'):
            transaction = Transaction(request.trans_uid, 0)
            transaction.add(request)
            if response:
                transaction.add(parse_block_for_list(response, 1))
            self.assertFalse(is_successful_protocol_only(transaction))
        transaction = Transaction(request.trans_uid, 0)
        transaction.add(request); transaction.add(parse_block_for_list(block('response', mti='0810'), 1))
        problems = build_problem_columns([transaction], {transaction.trans_uid: {'ISO': [('error', 'HSM failure')]}})
        self.assertEqual(problem_row_tag('; '.join(problems[transaction.trans_uid]), '', '',
                                       protocol_only_success=is_successful_protocol_only(transaction)), 'problem')

    def test_non_logon_and_missing_reference_do_not_get_generated_uid(self):
        for text in (block("request", code="301"), block("request", mti="0200"),
                     block("request", ref="")):
            self.assertIsNone(parse_block(text, 0).trans_uid)

    def test_list_and_targeted_export_without_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "audit.OPNBISOBKT01.day"
            source.write_text(block("request") + block("response", mti="0810"))
            transactions = scan_transactions_for_list([source])
            self.assertEqual(len(transactions), 1)
            uid = next(iter(transactions))
            # A fresh source path bypasses the list-location cache.
            second = Path(directory) / "audit.copy"
            second.write_text(source.read_text())
            scanned, _ = scan_transactions([second], correlate_missing=False, target_uids={uid})
            self.assertEqual(set(scanned), {uid})
            output = Path(directory) / "export"
            split_audit_files([second], output, bank="AKTIF/BKT", transaction_uids={uid})
            files = list(output.glob("*.log"))
            self.assertEqual(len(files), 1)
            self.assertIn("ref: 123", files[0].read_text())
            self.assertIn("asc<0810>", files[0].read_text())


if __name__ == "__main__":
    unittest.main()
