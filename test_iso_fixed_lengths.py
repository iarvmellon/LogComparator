import unittest
from iso_checks import NUMERIC_LENGTHS, TEXT_LENGTHS, parse_iso_message, check_iso_messages
from log_core import parse_block, parse_block_for_list

class FixedLengthTests(unittest.TestCase):
    def parse(self, text):
        return parse_iso_message(text, 'OPN01', 'request', '')

    def test_every_numeric_field_exact_short_long_and_non_numeric(self):
        for field, width in NUMERIC_LENGTHS.items():
            for template in ['DE{field:03} : asc<{value}>', '<field name="DE{field:03}">{value}</field>']:
                with self.subTest(field=field, template=template):
                    good = '1' * width if field != 7 else '1015123045'
                    self.assertFalse(self.parse(template.format(field=field, value=good)).invalid_fields)
                    for value in ['1' * (width - 1), '1' * (width + 1), 'X' * width]:
                        self.assertIn(f'DE{field}', self.parse(template.format(field=field, value=value)).invalid_fields)
                    self.assertFalse(self.parse(f'DE{field:03} : int<1>').invalid_fields)

    def test_text_padding_trimmed_values_and_overlength(self):
        for field, width in TEXT_LENGTHS.items():
            for value in ['A' * width, 'SHORT', 'A' * width + '    ']:
                self.assertFalse(self.parse(f'DE{field} : asc<{value}>').invalid_fields)
            self.assertTrue(self.parse(f'DE{field} : asc<' + 'A' * (width + 1) + '>').invalid_fields)

    def test_pin_hex_bytes_and_masking_without_value_disclosure(self):
        self.assertFalse(self.parse('DE052 : hex<0123456789ABCDEF>').invalid_fields)
        for value in ['01234567', 'G' * 16, '01' * 9]:
            message = self.parse(f'DE052 : hex<{value}>')
            self.assertTrue(message.invalid_fields)
            self.assertNotIn(value, str(check_iso_messages([message])))
            self.assertNotIn(value, str(message.values))
        self.assertFalse(self.parse('DE052 : hex<****************>').invalid_fields)
        self.assertFalse(self.parse('DE052 : asc<not-a-wire-dump>').invalid_fields)

    def test_absent_unidentified_and_masked_values_do_not_error(self):
        self.assertFalse(self.parse('processingCode : asc<1>\nDE014 : asc<****>\nDE003 : asc<>').invalid_fields)

    def test_both_audit_parsers_get_new_field_diagnostics(self):
        for parser in [parse_block, parse_block_for_list]:
            b = parser('Process name : OPN01\nFlow type : request\n'
                       '3. processingCode : asc<123>\n5. settlementAmount : asc<123>\n', 0)
            self.assertEqual(b.iso_message.invalid_fields, {'DE3', 'DE5'})

if __name__ == '__main__': unittest.main()
