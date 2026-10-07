import gzip
import tempfile
import unittest
from pathlib import Path

from diagnostic_common import AuditMessage, problem_row_tag
from log_core import Transaction, parse_block, parse_block_for_list
from spdh_checks import parse_spdh_message, check_spdh_messages
from tango_checks import diagnostic, scan_tango_diagnostics
from transaction_checks import build_problem_columns


def spdh(phase, **values):
    defaults = dict(transmission='01', sequence='0010010010', tid='TERM1', mid='MERCHANT',
                    amount='1000', currency='978', transaction_code='00', message_class='F', message_subclass='O')
    if phase == 'response':
        defaults['rc'] = '000'
    defaults.update(values)
    return AuditMessage('PTMS01', phase, defaults)


class SpdhTests(unittest.TestCase):
    def test_echo_checks_and_declines(self):
        self.assertEqual(check_spdh_messages([spdh('request'), spdh('response', rc='005')]), ([], []))
        for key, expected in (('transmission', 'transmission number mismatch'),
                              ('tid', 'terminal or merchant mismatch'), ('currency', 'currency mismatch'),
                              ('transaction_code', 'transaction code mismatch'),
                              ('message_class', 'message class mismatch'), ('message_subclass', 'message subclass mismatch')):
            with self.subTest(key=key):
                self.assertIn(expected, check_spdh_messages([spdh('request'), spdh('response', **{key: 'OTHER'})])[0])

    def test_resync_amount_and_missing_response_are_warnings(self):
        errors, warnings = check_spdh_messages([spdh('request'), spdh('response', sequence='2', amount='500')])
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 2)
        self.assertIn('missing SPDH response (incomplete log or timeout)', check_spdh_messages([spdh('request')])[1])
        self.assertIn('missing response code', check_spdh_messages([spdh('request'), spdh('response', rc='')])[1])

    def test_conflicting_responses_and_retransmits(self):
        self.assertEqual(check_spdh_messages([spdh('request'), spdh('response'), spdh('response')]), ([], []))
        self.assertIn('conflicting responses', check_spdh_messages([
            spdh('request'), spdh('response'), spdh('response', rc='005')])[0])

    def test_ptms_parsing_in_both_parsers_and_no_iso_de_assumptions(self):
        text = ('Process name : PTMS01\nFlow type : response\n'
                '11. xchgId : int<1>\ntransSeqNo : asc<0010010010>\nrcncltTxnSeqNo : int<1>\n'
                'prtclMsgClass : asc<F>\nprtclMsgSubClass : asc<O>\nprtclTransType : asc<00>\n'
                'responseCode : asc<000>\ntrmId : asc<TERM1>\n'
                '<field name="transactionAmt">1000</field>\n')
        for parser in (parse_block, parse_block_for_list):
            parsed = parser(text, 0)
            self.assertIsNone(parsed.iso_message)
            self.assertEqual(parsed.spdh_message.values['transmission'], '1')
            self.assertEqual(parsed.spdh_message.values['sequence'], '0010010010')
            self.assertEqual(parsed.spdh_message.invalid_fields, set())
        self.assertIsNone(parse_spdh_message(text, 'OPN01', 'response'))

    def test_invalid_spdh_header_format(self):
        parsed = parse_spdh_message('xchgId : asc<abc>\nresponseCode : asc<1234>\n', 'PTMS01', 'response')
        self.assertEqual(parsed.invalid_fields, {'transmission', 'rc'})

    def test_original_sequence_reference(self):
        original = Transaction('original', 0, mtis=['4530'], spdh_messages=[spdh('request')])
        void = Transaction('void', 1, mtis=['4554'], spdh_messages=[
            spdh('request', original_sequence='0010010010', sequence='0010010020', mid='OTHER')])
        columns = build_problem_columns([original, void])
        self.assertIn('original transaction mismatch (MID: current=OTHER, original=MERCHANT)', columns['void'][1])
        self.assertNotIn('original transaction mismatch', columns['void'][0])


class TangoTests(unittest.TestCase):
    def test_missing_field_formats_and_negatives(self):
        for line, expected in (('Missing Mandatory Field:11;/|', '11'),
                               ('Required field "terminalId" is not present', 'terminalId'),
                               ('Missing field in the message', 'name not logged'),
                               ('Tag 9F02 not found', '9F02')):
            self.assertIn(expected, diagnostic(line)[1])
        self.assertIsNone(diagnostic('No missing fields'))
        self.assertIsNone(diagnostic('field 11 is not missing'))
        self.assertIsNone(diagnostic('Approved transaction'))
        self.assertEqual(diagnostic('Optional field foo is missing')[0], 'warning')

    def test_explicit_security_and_network_failures(self):
        self.assertEqual(diagnostic('MAC verification failed'), ('error', 'MAC verification failed'))
        self.assertEqual(diagnostic('HSM unavailable'), ('error', 'HSM failure'))
        self.assertEqual(diagnostic('Host response timeout'), ('warning', 'communication timeout'))
        self.assertIsNone(diagnostic('MAC verification successful'))

    def test_exact_uid_protocol_routing_and_gzip(self):
        lines = (
            '20261002|OPN01|OPN02|0002|0004|ACT|abc|2204|Missing Mandatory Field:11;|\n'
            '20261002|PTMS01|PTMS02|0002|0004|ACT|abc|2204|Field terminalId missing|\n'
            '20261002|AC01|AC02|0002|0004|ACT|abc|3098|Missing field in the message|\n'
            '20261002|OPN01|OPN02|0002|0004|ACT||2204|Missing Mandatory Field:37;|\n'
            'transUId=abc123 ISO Missing field:49\n'
            'transUId=abc ISO MAC verification failed\n'
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'tango.log.gz'
            with gzip.open(path, 'wt') as stream:
                stream.write(lines + lines)
            findings = scan_tango_diagnostics([path], {'abc'})
            self.assertEqual(set(findings), {'abc'})
            self.assertEqual(len(findings['abc']['ISO']), 2)
            self.assertEqual(len(findings['abc']['SPDH']), 1)
            self.assertEqual(len(findings['abc'][None]), 1)
            self.assertNotIn('49', str(findings))
            self.assertNotIn('37', str(findings))

    def test_uncompressed_copy_preferred_and_log_changes_read(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'tango.log'
            compressed = Path(str(path) + '.gz')
            with gzip.open(compressed, 'wt') as stream:
                stream.write('transUId=abc ISO Missing field:49\n')
            path.write_text('transUId=abc ISO Missing field:11\n')
            findings = scan_tango_diagnostics([compressed, path], {'abc'})
            self.assertIn('11', str(findings))
            self.assertNotIn('49', str(findings))
            path.write_text('transUId=abc ISO Missing field:37\n')
            self.assertIn('37', str(scan_tango_diagnostics([path], {'abc'})))


class ColumnTests(unittest.TestCase):
    def test_bcd_original_mti_and_invoice_sequence_reference(self):
        de90 = '0200' + '000001' + '1002090137' + '0' * 22
        for parser in (parse_block, parse_block_for_list):
            with self.subTest(parser=parser.__name__):
                purchase = Transaction('purchase', 0, mtis=['4530'])
                void = Transaction('void', 1, mtis=['4554'])
                for transaction, sequence, stan, request_mti, response_mti in (
                    (purchase, '001275210', '000001', '0100', '0110'),
                    (void, '001275211', '000002', '0420', '0430'),
                ):
                    for phase, mti in (('request', request_mti), ('response', response_mti)):
                        text = (f'Process name : OPN01\nFlow type : {phase}\nmsgId : asc<{mti}>\n'
                                ' 4. transactionAmt : hex<000000000010>\n'
                                f'11. auditNumber : hex<{stan}>\n'
                                '37. retrievRefNumber : asc<123456789012>\n'
                                '49. currencyCode : hex<0978>\n')
                        if transaction is void:
                            text += f'90. originalDataElements : hex<{de90}>\n'
                        if phase == 'response':
                            text += '39. responseCode : asc<00>\n'
                        transaction.add(parser(text, 0))
                        text = (f'Process name : PTMS01\nFlow type : {phase}\n'
                                f'transSeqNo : asc<{sequence}>\ntrmId : asc<TERM1>\n')
                        if transaction is void and phase == 'request':
                            text += 'Invoice_OriginTransSeqNo : asc<001275210>\n'
                        if phase == 'response':
                            text += 'responseCode : asc<000>\n'
                        transaction.add(parser(text, 0))
                columns = build_problem_columns([purchase, void])
                self.assertEqual(columns['purchase'], ('', ''))
                self.assertEqual(columns['void'], (
                    'original transaction mismatch (original_mti: referenced=0200, observed=0100)', ''))
                self.assertEqual(void.iso_messages[0].values['amount'], '000000000010')
                self.assertEqual(void.iso_messages[0].values['currency'], '978')

    def test_ptms_rrn_mismatch_and_duplicates_are_ignored(self):
        from transaction_checks import transactions_with_shared_rrns
        first = Transaction('a', 0, rrns=['shared'], rrns_by_flow={
            'PTMS01': {'request': {'shared'}, 'response': {'different'}}},
            spdh_messages=[spdh('request', rrn='shared'), spdh('response', rrn='different')])
        second = Transaction('b', 1, rrns=['shared'], rrns_by_flow={
            'PTMS01': {'request': {'shared'}, 'response': {'shared'}}})
        iso = Transaction('iso', 2, rrns_by_flow={'OPN01': {'request': {'shared'}, 'response': {'shared'}}})
        self.assertEqual(transactions_with_shared_rrns([first, second, iso]), set())
        self.assertEqual(build_problem_columns([first, second, iso]),
                         {'a': ('', ''), 'b': ('', ''), 'iso': ('', '')})

    def test_spdh_parser_does_not_collect_rrn(self):
        parsed = parse_spdh_message('rrn : asc<123>\noriginalRRN : asc<456>\n', 'PTMS01', 'request')
        self.assertNotIn('rrn', parsed.values)
        self.assertNotIn('original_rrn', parsed.values)

    def test_spdh_original_check_ignores_original_rrn(self):
        original = Transaction('a', 0, mtis=['4530'], spdh_messages=[spdh('request', rrn='R1')])
        void = Transaction('v', 1, mtis=['4554'], spdh_messages=[
            spdh('request', original_sequence='0010010010', original_rrn='R2'), spdh('response')])
        self.assertEqual(build_problem_columns([original, void])['v'], ('', ''))

    def test_rrn_errors_stay_in_their_protocol_and_reversal_exemption(self):
        first = Transaction('a', 0, mtis=['4530'], rrns_by_flow={
            'OPN01': {'request': {'R1'}, 'response': {'R2'}},
            'PTMS01': {'request': {'S1'}, 'response': {'S1'}}})
        second = Transaction('b', 1, mtis=['4530'], rrns_by_flow={'OPN01': {'request': {'R1'}}})
        void = Transaction('v', 2, mtis=['4554'], rrns_by_flow={'PTMS01': {'request': {'S1'}}})
        columns = build_problem_columns([first, second, void])
        self.assertIn('differentRRN on the same transaction', columns['a'][0])
        self.assertIn('RRN identical with other transaction', columns['b'][0])
        self.assertEqual(columns['a'][1], '')
        self.assertEqual(columns['v'][1], '')

    def test_tango_protocol_specific_and_unspecified_messages(self):
        transaction = Transaction('a', 0)
        columns = build_problem_columns([transaction], {'a': {
            'ISO': [('error', 'missing field: 11')], 'SPDH': [('warning', 'communication timeout')],
            None: [('error', 'HSM failure')]}})['a']
        self.assertIn('missing field: 11', columns[0])
        self.assertNotIn('missing field: 11', columns[1])
        self.assertIn('warning: Tango: communication timeout', columns[1])
        for column in columns:
            self.assertIn('Tango (protocol unspecified): HSM failure', column)
        self.assertEqual(problem_row_tag('; '.join(columns), 'Approved(000)', 'Approved(00)'), 'problem')


if __name__ == '__main__':
    unittest.main()
