import tempfile
import unittest
from pathlib import Path

from log_core import Transaction, parse_block, parse_block_for_list
from transaction_checks import is_successful_protocol_only, build_problem_columns
from diagnostic_common import problem_row_tag
from web_services import load_logs


def echo(phase, rc='000', mti=None, process='OPNWAY4B01', code='hex<0301>'):
    mti = mti or ('0800' if phase == 'request' else '0810')
    direction = 'NETWORK-->TANGO' if phase == 'request' else 'TANGO-->NETWORK'
    return ('='*40 + '\nSP date time GMT : 2026-10-12 00:33:55\n'
            f'Process name : {process}\nFlow dir : {direction}\n'
            f'Flow type : {phase}\nMessage type : in echotest\ntransUId : ECHO-TEST\n'
            f'Audit data:\nmsgId : asc<{mti}>\n11. auditNumber : asc<072649>\n'
            f'70. networkManageCode : {code}\n'
            + (f'39. responseCode : asc<{rc}>\n' if phase == 'response' and rc else ''))


class EchoSuccessTests(unittest.TestCase):
    def test_approved_iso_echo_is_green_for_both_parsers(self):
        for parser in (parse_block, parse_block_for_list):
            for rc in ('000', '00'):
                for code in ('hex<0301>', 'asc<301>'):
                    with self.subTest(parser=parser.__name__, rc=rc, code=code):
                        t = Transaction('ECHO-TEST', 0)
                        t.add(parser(echo('request', code=code), 0))
                        t.add(parser(echo('response', rc, code=code), 1))
                        self.assertTrue(is_successful_protocol_only(t))
                        problems = build_problem_columns([t])[t.trans_uid]
                        self.assertEqual(problems, ('', ''))
                        self.assertEqual(problem_row_tag('; '.join(problems), '', '',
                            protocol_only_success=is_successful_protocol_only(t)), 'approved')

    def test_declined_missing_code_unmatched_and_financial_are_not_green(self):
        request = parse_block(echo('request'), 0)
        for response in (echo('response', '05'), echo('response', ''),
                         echo('response', mti='0210'),
                         echo('response', process='OPNOTHER01')):
            t = Transaction('ECHO-TEST', 0)
            t.add(request); t.add(parse_block(response, 1))
            self.assertFalse(is_successful_protocol_only(t))
        t = Transaction('ECHO-TEST', 0)
        t.add(parse_block(echo('request', mti='0200', code='asc<201>'), 0))
        t.add(parse_block(echo('response', mti='0210', code='asc<201>'), 1))
        self.assertFalse(is_successful_protocol_only(t))
        t = Transaction('ECHO-TEST', 0)
        t.add(parse_block(echo('response'), 0))
        self.assertFalse(is_successful_protocol_only(t))

    def test_web_row_is_green_and_diagnostics_keep_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'tango.log.2026-10-12').write_text('')
            (root / 'audit.OPNWAY4B01.2026-10-12').write_text(echo('request')+echo('response'))
            import log_core as core
            bank = next(bank for bank in core.BANK_AUDIT_CODES
                        if core.bank_audit_code_matches(bank, 'OPNWAY4B01'))
            loaded = load_logs(root, bank, '2026-10-12')
            self.assertEqual(len(loaded.rows), 1)
            self.assertEqual(loaded.rows[0]['severity'], 'approved')
            self.assertEqual(loaded.rows[0]['responsecodeiso'], 'Approved(000)')
            self.assertEqual(problem_row_tag('HSM failure', '', '', protocol_only_success=True), 'problem')
            self.assertEqual(problem_row_tag('warning: test', '', '', protocol_only_success=True), 'warning')
