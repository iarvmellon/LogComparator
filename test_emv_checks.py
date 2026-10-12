import unittest
from emv_checks import parse_emv, check_emv
from diagnostic_common import AuditMessage
from iso_checks import parse_iso_message, check_iso_messages
from spdh_checks import parse_spdh_message, check_spdh_messages
from log_core import parse_block, parse_block_for_list
from diagnostic_common import problem_row_tag


class EmvTests(unittest.TestCase):
    def test_standard_widths_and_formats(self):
        for tag, good, bad in [('9F26', '01'*8, '01'), ('9F36', '0001', '01'),
                               ('9F37', '01020304', 'Z123'), ('95', '00'*5, '00'),
                               ('9F02', '000000001000', '00000000100A'),
                               ('5F2A', '0978', '1978'), ('9A', '261012', '261332')]:
            with self.subTest(tag=tag):
                m = AuditMessage('OPN01', 'response', emv_tags={tag: good})
                self.assertEqual(check_emv(m)[0], [])
                m.emv_tags[tag] = bad
                self.assertTrue(check_emv(m)[0])

    def test_complete_online_request_and_missing_warning(self):
        tags = {
            '9F26': '01'*8, '9F36': '0001', '9F37': '01020304', '95': '00'*5,
            '9A': '261012', '9C': '00', '9F02': '000000001000',
            '5F2A': '0978', '82': '0000', '9F1A': '0300'}
        m = AuditMessage('OPN01', 'request', {'mti': '0200'}, emv_tags=tags)
        self.assertEqual(check_emv(m), ([], []))
        del tags['9F37']
        self.assertIn('9F37', check_emv(m)[1][0])
        self.assertEqual(check_emv(m)[0], [])
        for phase, mti in [('response', '0210'), ('request', '0420'), ('request', '0800')]:
            m.phase, m.values['mti'] = phase, mti
            self.assertEqual(check_emv(m)[1], [])

    def test_tlv_constructed_long_length_and_truncation(self):
        tags, errors = parse_emv('DE055 : hex<770B9F26080102030405060708>')
        self.assertEqual(tags, {'9F26': '0102030405060708'})
        self.assertEqual(errors, [])
        tags, errors = parse_emv('iccData : hex<9F2681080102030405060708>')
        self.assertEqual(tags['9F26'], '0102030405060708')
        self.assertEqual(errors, [])
        for value in ['9F26080102', '9F2680', '9F', '9F260G', '9F260']:
            self.assertTrue(parse_emv('iccData : hex<' + value + '>')[1])

    def test_duplicate_conflict_and_unknown_tag(self):
        tags, errors = parse_emv('tag9F36 : hex<0001>\ntag9F36 : hex<0002>')
        self.assertIn('conflicting EMV tag 9F36', errors)
        self.assertEqual(parse_emv('tagDF01 : hex<0102>'), ({'DF01': '0102'}, []))

    def test_no_iso_field_or_opaque_spdh_false_positive(self):
        self.assertEqual(parse_emv('DE049 : asc<978>\nDE004 : asc<000000001000>'), ({}, []))
        self.assertEqual(parse_emv('emvRequestData : asc<fixedlayout>'), ({}, []))
        self.assertEqual(parse_emv('iccData :\napplicationCryptogram : asc<TEXT>'), ({}, []))
        m = AuditMessage('OPN01', 'request', {'mti': '0200'})
        self.assertEqual(check_emv(m), ([], []))

    def test_both_parsers_and_protocol_columns(self):
        for process, checker in [('OPN01', check_iso_messages), ('PTMS01', check_spdh_messages)]:
            for parser in [parse_block, parse_block_for_list]:
                block = parser('Process name : ' + process + '\nFlow type : request\n'
                               'msgId : asc<0200>\ntag9F26 : hex<01>\n', 0)
                m = block.iso_message if process.startswith('OPN') else block.spdh_message
                self.assertIn('invalid EMV tag 9F26 length', checker([m])[0][0])

    def test_named_hex_and_xml_tags(self):
        self.assertEqual(parse_emv('iccData :\n4. applicationCryptogram : hex<0102030405060708>')[0],
                         {'9F26': '0102030405060708'})
        self.assertEqual(parse_emv('<field name="tag9F36">0001</field>')[0], {'9F36': '0001'})

    def test_chip_mode_missing_data_and_numeric_checks(self):
        m = parse_iso_message('msgId : asc<0200>\nDE022 : asc<051>', 'OPN01', 'request', '')
        self.assertIn('chip entry mode', check_emv(m)[1][0])
        self.assertIn('DE7 date/time', parse_iso_message('DE007 : asc<1331999999>', 'OPN01', 'request', '').invalid_fields)
        m = parse_spdh_message('amount : asc<-100>\ncurrencyCode : asc<AB>\nstan : asc<1234567>', 'PTMS01', 'request')
        self.assertEqual(m.invalid_fields, {'amount', 'currency', 'stan'})

    def test_amount_currency_mismatch_is_warning(self):
        m = AuditMessage('OPN01', 'response', {'amount': '1000', 'currency': '978'},
                         emv_tags={'9F02': '000000002000', '5F2A': '0840'})
        self.assertEqual(check_emv(m)[0], [])
        self.assertEqual(len(check_emv(m)[1]), 2)

    def test_severity_uses_existing_row_colors(self):
        warning = AuditMessage('OPN01', 'request', {'mti': '0200'},
                               emv_tags={'9F26': '01' * 8})
        errors, warnings = check_emv(warning)
        self.assertFalse(errors)
        text = '; '.join('warning: ' + value for value in warnings)
        self.assertEqual(problem_row_tag(text, 'Approved(000)', 'Approved(00)'), 'warning')
        warning.emv_tags['9F26'] = '01'
        errors, warnings = check_emv(warning)
        text = '; '.join(errors + ['warning: ' + value for value in warnings])
        self.assertEqual(problem_row_tag(text, 'Approved(000)', 'Approved(00)'), 'problem')


if __name__ == '__main__':
    unittest.main()
