import tempfile
import unittest
from pathlib import Path

import log_core as core
from diagnostic_common import problem_row_tag
from web_services import load_logs
from testing.test_echo_success import echo


class ValidationStatusTests(unittest.TestCase):
    def test_business_codes_never_determine_validation_success(self):
        for spdh in ('Approved(000)', 'Declined(050)', 'Unknown', ''):
            for iso in ('Approved(00)', 'Approved(000)', 'Declined(05)', 'Unknown', ''):
                with self.subTest(spdh=spdh, iso=iso):
                    self.assertEqual(problem_row_tag('', spdh, iso), 'approved')
                    self.assertEqual(problem_row_tag('warning: missing response', spdh, iso), 'warning')
                    self.assertEqual(problem_row_tag('different STAN; warning: missing response', spdh, iso), 'problem')
                    self.assertEqual(problem_row_tag('', spdh, iso, checked=False), '')

    def test_real_rows_classify_findings_independently_of_response(self):
        bank = next(bank for bank in core.BANK_AUDIT_CODES
                    if core.bank_audit_code_matches(bank, 'OPNWAY4B01'))
        request = echo('request', mti='0200', code='asc<000>')
        cases = [
            ('declined', request + echo('response', '51', mti='0210', code='asc<000>'), 'approved'),
            ('approved', request + echo('response', '00', mti='0210', code='asc<000>'), 'approved'),
            ('approved_000', request + echo('response', '000', mti='0210', code='asc<000>'), 'approved'),
            ('missing_rc', request + echo('response', '', mti='0210', code='asc<000>'), 'warning'),
            ('invalid_stan', request + echo('response', '00', mti='0210', code='asc<000>').replace('072649', '072650'), 'problem'),
            ('unparsed', request.replace('Flow type : request', 'Flow type : internal'), ''),
        ]
        for label, content, expected in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / 'tango.log.2026-10-12').write_text('')
                (root / 'audit.OPNWAY4B01.2026-10-12').write_text(content)
                loaded = load_logs(root, bank, '2026-10-12')
                self.assertEqual(len(loaded.rows), 1)
                self.assertEqual(loaded.rows[0]['severity'], expected)
                if label == 'approved':
                    self.assertFalse(loaded.rows[0]['responsecodeiso_alert'])
                if label == 'approved_000':
                    self.assertFalse(loaded.rows[0]['responsecodeiso_alert'])
                if label == 'declined':
                    self.assertNotEqual(loaded.rows[0]['responsecodeiso'], 'Approved(00)')
                    self.assertIn('(51)', loaded.rows[0]['responsecodeiso'])
                    self.assertTrue(loaded.rows[0]['responsecodeiso_alert'])
                    self.assertFalse(loaded.rows[0]['responsecodespdh_alert'])

    def test_summary_labels_response_outcome_separately(self):
        t = core.Transaction('validation-test', 0)
        t.iso_response_codes = ['51']
        text = core.format_transaction_summary(t, [])
        self.assertIn('Response status', text)
        self.assertIn('DECLINED', text)
        self.assertEqual(core.transaction_status('000', 'NA'), 'APPROVED')
