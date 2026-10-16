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
