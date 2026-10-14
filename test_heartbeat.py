import unittest
from diagnostic_common import problem_row_tag
from iso_checks import parse_iso_message, check_iso_messages
from log_core import Transaction, parse_block, parse_block_for_list
from transaction_checks import is_one_way_heartbeat, build_problem_columns


class HeartbeatTests(unittest.TestCase):
    def transaction(self, process, code='301', mti='0800'):
        message = parse_iso_message(f'msgId : asc<{mti}>\nDE070 : asc<{code}>', process, 'request', '')
        return Transaction('test', 0, iso_messages=[message])

    def test_one_way_echo_for_supported_acquirers_is_green(self):
        for process in ['OPNBISOCAS01', 'OPNBISOA01', 'OPNWAY4B01', 'OPNBISOE01']:
            with self.subTest(process=process):
                transaction = self.transaction(process)
                self.assertTrue(is_one_way_heartbeat(transaction))
                columns = build_problem_columns([transaction])['test']
                self.assertEqual(columns, ('', ''))
                self.assertEqual(problem_row_tag('; '.join(columns), 'Unknown', 'Unknown', True), 'approved')

    def test_logon_other_acquirers_and_payment_requests_still_warn(self):
        for process, code, mti in [('OPNBISOCAS01', '001', '0800'),
                                   ('OPNBISOC01', '301', '0800'),
                                   ('OPNWAY4N01', '301', '0800'),
                                   ('OPNBISOA01', '301', '0200')]:
            transaction = self.transaction(process, code, mti)
            self.assertFalse(is_one_way_heartbeat(transaction))
            self.assertIn('missing ISO response', check_iso_messages(transaction.iso_messages)[1][0])

    def test_diagnostics_override_heartbeat_green(self):
        self.assertEqual(problem_row_tag('invalid ISO message format', '', '', True), 'problem')
        self.assertEqual(problem_row_tag('warning: communication timeout', '', '', True), 'warning')
        transaction = self.transaction('OPNBISOA01')
        columns = build_problem_columns([transaction], {'test': {'ISO': [('error', 'HSM failure')]}})['test']
        self.assertIn('HSM failure', columns[0])

    def test_parser_variants_capture_network_management_code(self):
        for parser in [parse_block, parse_block_for_list]:
            for field in ['70. networkManageCode : asc<301>', "<field name='networkManageCode'>301</field>"]:
                block = parser('Process name : OPNBISOCAS01\nFlow type : request\nmsgId : asc<0800>\n' + field, 0)
                self.assertEqual(check_iso_messages([block.iso_message]), ([], []))


if __name__ == '__main__':
    unittest.main()
