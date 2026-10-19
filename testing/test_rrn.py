import unittest

from log_core import Transaction, parse_block, parse_block_for_list, select_possible_problem, transactions_with_shared_rrns


class RrnTests(unittest.TestCase):
    def test_request_response_rrns(self):
        cases = (
            ([('OPN01', 'request', '001'), ('OPN01', 'response', '001')], ''),
            ([('OPN01', 'request', '001'), ('OPN01', 'response', '002')], 'wrong RRN'),
            ([('PTMS01', 'response', '002'), ('PTMS01', 'request', '001')], ''),
            ([('OPN01', 'request', '001')], ''),
            ([('OPN01', 'response', '002')], ''),
            ([('OPN01', 'request', ''), ('OPN01', 'response', '002')], ''),
            ([('OPN01', 'request', '001'), ('OPN01', 'response', '')], ''),
            ([('PTMS01', 'request', '001'), ('PTMS01', 'response', '001'),
              ('OPN01', 'request', '002'), ('OPN01', 'response', '002')], ''),
            ([('OPN01', 'request', '001'), ('OPN02', 'response', '002')], ''),
            ([('OPN01', 'request', '001'), ('INTERNAL01', 'response', '002')], ''),
            ([('OPN01', 'request', '001'), ('OPN01', 'request', '001'),
              ('OPN01', 'response', '001')], ''),
            ([('OPN01', 'request', '001'), ('OPN01', 'response', '1')], 'wrong RRN'),
        )
        for parser in (parse_block, parse_block_for_list):
            for blocks, expected in cases:
                with self.subTest(parser=parser.__name__, blocks=blocks):
                    transaction = Transaction('test', 0)
                    for index, (process, phase, rrn) in enumerate(blocks):
                        transaction.add(parser(
                            f'Process name : {process}\nFlow type : {phase}, ref: 123\n'
                            f'rrn : asc<{rrn}>\n', index))
                    errors = '; '.join(p for p in select_possible_problem(transaction).split('; ')
                                       if p and not p.startswith('warning: '))
                    self.assertEqual(errors,
                                     'differentRRN on the same transaction' if expected else '')

    def test_shared_rrns_mark_all_transactions_and_all_observed_values(self):
        first = Transaction('first', 0, rrns=['001', '002', '001'])
        second = Transaction('second', 1, rrns=['002'])
        third = Transaction('third', 2, rrns=['002'])
        distinct = Transaction('distinct', 3, rrns=['1', '1', '', 'asc<>'])
        empty = Transaction('empty', 4, rrns=['', 'asc<>'])
        for transaction in (first, second, third, distinct, empty):
            transaction.rrns_by_flow = {'OPN01': {'request': set(transaction.rrns)}}
        shared = transactions_with_shared_rrns([first, second, third, distinct, empty])
        self.assertEqual(shared, {'first', 'second', 'third'})
        self.assertEqual(select_possible_problem(second, second.trans_uid in shared),
                         'RRN identical with other transaction')
        self.assertEqual(select_possible_problem(distinct, distinct.trans_uid in shared), '')

    def test_both_problems_are_reported(self):
        transaction = Transaction('test', 0)
        for index, (phase, rrn) in enumerate((('request', '001'), ('response', '002'))):
            transaction.add(parse_block(
                f'Process name : OPN01\nFlow type : {phase}\nrrn : asc<{rrn}>\n', index))
        self.assertEqual(select_possible_problem(transaction, True),
                         'differentRRN on the same transaction; RRN identical with other transaction')

    def test_reversal_and_void_allow_shared_rrn_without_hiding_other_duplicates(self):
        for mti in ('0400', '0410', '0420', '4546', '4554', '4555', '8760', '4581'):
            with self.subTest(mti=mti):
                original = Transaction('original', 0, mtis=['4530'], rrns=['001'])
                exempt = Transaction('exempt', 1, mtis=[mti], rrns=['001'])
                duplicate = Transaction('duplicate', 2, mtis=['4530'], rrns=['001'])
                for transaction in (original, exempt, duplicate):
                    transaction.rrns_by_flow = {'OPN01': {'request': set(transaction.rrns)}}
                self.assertEqual(transactions_with_shared_rrns([original, exempt]), set())
                self.assertEqual(transactions_with_shared_rrns([exempt, original]), set())
                self.assertEqual(transactions_with_shared_rrns([exempt, original, duplicate]),
                                 {'original', 'duplicate'})
                exempt.rrns_by_flow = {'OPN01': {'request': {'001'}, 'response': {'002'}}}
                self.assertEqual(select_possible_problem(exempt),
                                 'differentRRN on the same transaction')


if __name__ == '__main__':
    unittest.main()
