import unittest
from diagnostic_common import AuditMessage, problem_row_tag
from log_core import Transaction
from transaction_checks import is_successful_protocol_only

class SpdhOnlySuccessTests(unittest.TestCase):
    def transaction(self, mti, rc='000'):
        return Transaction('test', 0, mtis=[mti], spdh_messages=[
            AuditMessage('PTMS01', 'request'), AuditMessage('PTMS01', 'response', {'rc': rc})])

    def test_close_batch_and_generate_key_are_green_without_iso(self):
        for mti in ['4850', '6001']:
            t = self.transaction(mti)
            self.assertTrue(is_successful_protocol_only(t))
            self.assertEqual(problem_row_tag('', 'Approved(000)', 'Unknown',
                                             protocol_only_success=True), 'approved')

    def test_declines_incomplete_flows_other_operations_are_not_green(self):
        for mti, rc in [('4850', '074'), ('6001', ''), ('4530', '000')]:
            self.assertFalse(is_successful_protocol_only(self.transaction(mti, rc)))
        t = self.transaction('4850')
        t.spdh_messages.pop()
        self.assertFalse(is_successful_protocol_only(t))
        t = self.transaction('6001')
        t.iso_messages.append(AuditMessage('OPN01', 'request'))
        self.assertFalse(is_successful_protocol_only(t))
        t = self.transaction('6001')
        t.spdh_messages.append(AuditMessage('PTMS02', 'request'))
        self.assertFalse(is_successful_protocol_only(t))

    def test_diagnostics_take_priority(self):
        self.assertEqual(problem_row_tag('warning: communication timeout', '', '',
                                         protocol_only_success=True), 'warning')
        self.assertEqual(problem_row_tag('invalid SPDH message format', '', '',
                                         protocol_only_success=True), 'problem')

if __name__ == '__main__':
    unittest.main()
