import unittest
from diagnostic_common import AuditMessage, problem_row_tag
from log_core import Transaction
from transaction_checks import successful_local_reversal_uids, build_problem_columns

class LocalReversalTests(unittest.TestCase):
    def transactions(self):
        original = Transaction('original', 0, mtis=['4530'], spdh_messages=[
            AuditMessage('PTMS01', 'request', {'tid': 'TERM', 'sequence': '000123', 'currency': '978'}),
            AuditMessage('PTMS01', 'response', {'rc': '000'})])
        reversal = Transaction('reversal', 1, mtis=['4546'], spdh_messages=[
            AuditMessage('PTMS01', 'request', {'tid': 'TERM', 'original_sequence': '123', 'currency': '978'}),
            AuditMessage('PTMS01', 'response', {'rc': '000'})])
        return original, reversal

    def test_matched_local_reversal_is_green(self):
        original, reversal = self.transactions()
        self.assertEqual(successful_local_reversal_uids([original, reversal]), {'reversal'})
        columns = build_problem_columns([original, reversal])['reversal']
        self.assertEqual(columns, ('', ''))
        self.assertEqual(problem_row_tag('; '.join(columns), 'Approved(000)', 'Unknown',
                                         protocol_only_success=True), 'approved')

    def test_host_connected_original_and_decline_are_not_green(self):
        for change in ['iso', 'opn', 'decline', 'mismatch', 'missing', 'later']:
            original, reversal = self.transactions()
            if change == 'iso': original.iso_messages.append(AuditMessage('OPN01', 'request'))
            if change == 'opn': original.process_names.add('OPNBISOA01')
            if change == 'decline': reversal.spdh_messages[1].values['rc'] = '074'
            if change == 'mismatch': reversal.spdh_messages[0].values['currency'] = '840'
            if change == 'missing': reversal.spdh_messages.pop()
            if change == 'later': original.first_index = 2
            self.assertEqual(successful_local_reversal_uids([original, reversal]), set(), change)

    def test_missing_or_ambiguous_original_is_not_green(self):
        original, reversal = self.transactions()
        self.assertEqual(successful_local_reversal_uids([reversal]), set())
        other, _ = self.transactions()
        other.trans_uid = 'other'
        self.assertEqual(successful_local_reversal_uids([original, other, reversal]), set())

    def test_other_diagnostics_override_green(self):
        original, reversal = self.transactions()
        columns = build_problem_columns([original, reversal],
                    {'reversal': {'SPDH': [('error', 'HSM failure')]}})['reversal']
        self.assertEqual(problem_row_tag('; '.join(columns), '', '', protocol_only_success=True), 'problem')

if __name__ == '__main__': unittest.main()
