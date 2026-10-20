import tempfile
import unittest
from pathlib import Path

import log_core as core
from web_services import LoadedLogs, export_logs

HEADER_UID = '37169483570199148300181'
BUS_UID = '37169483570099148300179'


def echo_block(header=HEADER_UID, bus=BUS_UID):
    return ('=' * 40 + '\nSP date time GMT : 2026-10-12 00:33:55, timestamp: 20261012003355701\n'
            'Process name : OPNWAY4B01\nFlow dir : NETWORK-->TANGO\n'
            'Flow type : request, ref: 6370796899608\n'
            'Message type : in echotest, MTI = - Incoming Echo Test\n'
            + (f'transUId : {header}\n' if header is not None else '')
            + 'Raw data (hex):\n00\nAudit data:\nmsgId : asc<0800>\n'
            '70. networkManageCode : hex<0301>\nBus data:\n'
            f"<field type='A' name='transUId'>{bus}</field>\n")


class TransactionUidIdentityTests(unittest.TestCase):
    def test_both_parsers_prefer_header_over_bus_uid(self):
        for parser in (core.parse_block, core.parse_block_for_list):
            with self.subTest(parser=parser.__name__):
                self.assertEqual(parser(echo_block(), 0).trans_uid, HEADER_UID)
                self.assertEqual(parser(echo_block(header=None), 0).trans_uid, BUS_UID)
                self.assertEqual(parser(echo_block(header=''), 0).trans_uid, BUS_UID)

    def test_list_targeted_scan_and_export_keep_header_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit = root / 'audit.OPNWAY4B01.2026-10-12'
            audit.write_text(echo_block() + echo_block(bus=HEADER_UID))
            listed = core.scan_transactions_for_list([audit])
            self.assertEqual(set(listed), {HEADER_UID})
            locations = core.AUDIT_BLOCK_LOCATION_CACHE[core.input_paths_cache_key([audit])]
            self.assertEqual(set(locations), {HEADER_UID})
            self.assertEqual(len(locations[HEADER_UID]), 2)
            # Cached and uncached targeted search must both reject a UID that
            # appears only in the payload of another transaction.
            for cached in (True, False):
                if not cached:
                    core.AUDIT_BLOCK_LOCATION_CACHE.pop(core.input_paths_cache_key([audit]), None)
                found, _ = core.scan_transactions([audit], target_uids={BUS_UID},
                                                 correlate_missing=False)
                self.assertEqual(found, {})
            loaded = LoadedLogs(root, 'BORICA/PROCREDIT', '2026-10-12', [audit], [],
                                [{'transuid': HEADER_UID}])
            for include_data in (True, False):
                paths = export_logs(loaded, [HEADER_UID], root / str(include_data),
                                    include_byte_data=include_data)
                text = paths[0].read_text()
                self.assertEqual(paths[0].name, HEADER_UID + '.log')
                self.assertIn('transUId             : ' + HEADER_UID, text)
                self.assertEqual(text.count('transUId : ' + HEADER_UID), 2)
                if not include_data:
                    self.assertNotIn(BUS_UID, text)
