import unittest

from iso_checks import (IsoMessage, check_iso_messages, check_original_transactions,
                       parse_iso_message, problem_row_tag)
from log_core import Transaction, parse_block, parse_block_for_list, select_possible_problem


def message(phase, **values):
    defaults = dict(mti='0200' if phase == 'request' else '0210', stan='000001',
                    amount='000000001000', currency='978', tid='TERM0001', mid='MERCHANT0000001')
    if phase == 'response':
        defaults['rc'] = '00'
    defaults.update(values)
    return IsoMessage('OPN01', phase, defaults)


class IsoCheckTests(unittest.TestCase):
    def test_matching_exchange_and_decline_are_not_errors(self):
        for code in ('00', '05'):
            self.assertEqual(check_iso_messages([message('request'), message('response', rc=code)]), ([], []))

    def test_field_mismatches(self):
        for key, value, expected in (
            ('stan', '2', 'different STAN on the same transaction'),
            ('currency', '840', 'currency mismatch'),
            ('tid', 'OTHER', 'terminal or merchant mismatch'),
            ('mid', 'OTHER', 'terminal or merchant mismatch'),
            ('mti', '0110', 'unexpected response MTI'),
            ('mti', '0200', 'unexpected response MTI'),
        ):
            with self.subTest(key=key, value=value):
                errors, _ = check_iso_messages([message('request'), message('response', **{key: value})])
                self.assertIn(expected, errors)

    def test_missing_optional_fields_are_not_mismatches(self):
        self.assertEqual(check_iso_messages([message('request'), message('response', tid='', mid='',
                                                                               currency='', amount='', stan='')]), ([], []))

    def test_numeric_padding_is_ignored(self):
        self.assertEqual(check_iso_messages([message('request'), message('response', stan='1', amount='1000')]), ([], []))

    def test_partial_approval_amount_is_a_warning(self):
        errors, warnings = check_iso_messages([message('request'), message('response', amount='500', rc='10')])
        self.assertEqual(errors, [])
        self.assertIn('amount mismatch (check partial approval/adjustment)', warnings)

    def test_incomplete_flows_and_missing_code_are_warnings(self):
        for messages, expected in (([message('request')], 'missing ISO response'),
                                   ([message('response')], 'ISO response without request'),
                                   ([message('request'), message('response', rc='')], 'missing response code')):
            errors, warnings = check_iso_messages(messages)
            self.assertEqual(errors, [])
            self.assertTrue(any(w.startswith(expected) for w in warnings))

    def test_duplicate_responses_and_conflicting_responses(self):
        for code, expected in (('00', []), ('05', ['conflicting responses'])):
            errors, _ = check_iso_messages([message('request'), message('response'), message('response', rc=code)])
            self.assertEqual(errors, expected)

    def test_connection_isolation(self):
        response = message('response', stan='2')
        response.process = 'OPN02'
        errors, warnings = check_iso_messages([message('request'), response])
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 2)

    def test_multiple_exchanges_pair_by_mti_and_stan(self):
        self.assertEqual(check_iso_messages([
            message('request'), message('request', stan='2', amount='2000'),
            message('response'), message('response', stan='2', amount='2000')]), ([], []))

    def test_ambiguous_pairing_is_warning_not_false_mismatch(self):
        errors, warnings = check_iso_messages([
            message('request', amount='1000'), message('request', amount='2000'), message('response')])
        self.assertEqual(errors, [])
        self.assertIn('ambiguous ISO request/response pairing', warnings)

    def test_proprietary_mti_is_not_assumed_invalid(self):
        errors, warnings = check_iso_messages([message('request', mti='6000'), message('response', mti='6100')])
        self.assertEqual((errors, warnings), ([], []))

    def test_both_parsers_extract_iso_fields_without_original_stan_contamination(self):
        for parser in (parse_block, parse_block_for_list):
            for template in ('{number}. hostSpecificName : asc<{value}>',
                             'DE{number:03} : asc<{value}>',
                             '<field name="DE{number:03}">{value}</field>'):
                with self.subTest(parser=parser.__name__, template=template):
                    transaction = Transaction('test', 0)
                    for index, (phase, mti, stan) in enumerate((('request', '0200', '000001'),
                                                               ('response', '0210', '000002'))):
                        fields = '\n'.join(template.format(number=n, value=v) for n, v in
                                           ((11, stan), (4, '000000001000'), (49, '978'), (39, '00')))
                        text = (f'Process name : OPN01\nFlow type : {phase}\n'
                                'Message type : Purchase, MTI = 4530\n'
                                f'msgId : asc<{mti}>\norigAuditNumber : asc<999999>\n{fields}\n')
                        transaction.add(parser(text, index))
                    self.assertEqual(select_possible_problem(transaction), 'different STAN on the same transaction')

    def test_internal_and_spdh_blocks_are_not_iso_messages(self):
        for process in ('PTMS01', 'INTERNAL01'):
            self.assertIsNone(parse_iso_message('DE011 : asc<bad>', process, 'request', ''))
        self.assertIsNone(parse_iso_message('DE011 : asc<bad>', 'OPN01', 'internal action', ''))

    def test_format_checks_only_explicit_decoded_fields(self):
        for text, invalid in (('DE011 : asc<ABC123>', True), ('DE004 : asc<123>', True),
                              ('DE049 : asc<978>', False), ('DE011 : int<1>', False),
                              ('amount : asc<10.00>', False), ('DE004 : hex<0010>', False),
                              ('bitmap : hex<FFFFFFFFFFFFFFFF>', False), ('bitmap : asc<XYZ>', True)):
            with self.subTest(text=text):
                parsed = parse_iso_message(text, 'OPN01', 'request', '')
                self.assertEqual(bool(parsed.invalid_fields), invalid)

    def test_nested_emv_numbers_are_not_iso_data_elements(self):
        parsed = parse_iso_message(
            '      4. transactionAmt : asc<000000001000>\n'
            '     11. auditNumber : asc<000001>\n'
            '         55. iccData :\n'
            '          4. applicationCryptogram : asc<ABCDEF0123456789>\n'
            '         11. terminalTransDate : asc<261002>\n', 'OPN01', 'request', '')
        self.assertEqual(parsed.invalid_fields, set())
        self.assertEqual(parsed.values['amount'], '000000001000')
        self.assertEqual(parsed.values['stan'], '000001')

    def test_original_reference_matches_and_missing_original_is_warning(self):
        original = message('request', rrn='000000000001')
        reversal = message('request', mti='0400', original_stan='000001', original_mti='0200')
        result = check_original_transactions([('original', [original], False), ('reversal', [reversal], True)])
        self.assertEqual(result['reversal'], ([], []))
        result = check_original_transactions([('reversal', [reversal], True)])
        self.assertEqual(result['reversal'][0], [])
        self.assertIn('original transaction not found (incomplete log)', result['reversal'][1])

    def test_original_mismatch_and_partial_reversal(self):
        original = message('request')
        reversal = message('request', mti='0400', original_stan='1', amount='500')
        self.assertEqual(check_original_transactions([('a', [original], False), ('b', [reversal], True)])['b'], ([], []))
        reversal.values['tid'] = 'OTHER'
        self.assertEqual(check_original_transactions([('a', [original], False), ('b', [reversal], True)])['b'][0],
                         ['original transaction mismatch (TID: current=OTHER, original=TERM0001)'])

    def test_de90_extraction(self):
        parsed = parse_iso_message('DE090 : asc<020000000110021200000000000000000000000000>', 'OPN01', 'request', '')
        self.assertEqual(parsed.values['original_stan'], '000001')
        self.assertEqual(parsed.values['original_mti'], '0200')
        self.assertEqual(parsed.values['original_time'], '1002120000')

    def test_ambiguous_original_not_guessed(self):
        original = message('request', rrn='same')
        reversal = message('request', mti='0400', rrn='same')
        result = check_original_transactions([('a', [original], False), ('b', [original], False), ('c', [reversal], True)])
        self.assertEqual(result['c'], ([], ['ambiguous original transaction']))

    def test_row_color_priority(self):
        self.assertEqual(problem_row_tag('', 'Approved(000)', 'Approved(00)'), 'approved')
        self.assertEqual(problem_row_tag('', '', 'Declined(05)'), '')
        self.assertEqual(problem_row_tag('warning: missing response code', 'Approved(000)', 'Approved(00)'), 'warning')
        self.assertEqual(problem_row_tag('currency mismatch; warning: missing response code', '', ''), 'problem')


if __name__ == '__main__':
    unittest.main()
