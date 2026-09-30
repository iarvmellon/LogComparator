import unittest

from log_core import Transaction, parse_block, parse_block_for_list, select_iso_mti, select_transaction_type


class TransactionTypeTests(unittest.TestCase):
    def test_protocol_phases_are_independent(self):
        for parser in (parse_block, parse_block_for_list):
            transaction = Transaction("test", 0)
            for process, flow, expected in (
                ("PTMS01", "request", "SPDHreq"),
                ("OPN01", "response", "SPDHreq-ISOresp"),
                ("PTMS01", "response", "SPDHreq-ISOresp-SPDHresp"),
                ("OPN01", "request", "SPDHreq-ISOresp-SPDHresp-ISOreq"),
                ("INTERNAL01", "response", "SPDHreq-ISOresp-SPDHresp-ISOreq"),
                ("PTMS01", "request", "SPDHreq-ISOresp-SPDHresp-ISOreq"),
            ):
                transaction.add(parser(
                    f"Process name : {process}\nFlow type : {flow}\n"
                    "Message type : MTI = 4530\n", 0))
                self.assertEqual(select_transaction_type(transaction), "Purchase (" + expected + ")")

    def classify(self, description, processing_code="", extra_mti=""):
        for parser in (parse_block, parse_block_for_list):
            for acquirer in ("050", "065"):
                text = f"""RP date time : 2026-09-28 11:13:57
Process name : OPNBISOBKT01
Flow type : request
Message type : {description}
transUId : test-uid
msgId : asc<0800>
processingCode : asc<{processing_code}>
acqId : asc<{acquirer}>
"""
                transaction = Transaction("test-uid", 0)
                transaction.add(parser(text, 0))
                if extra_mti:
                    transaction.mtis.append(extra_mti)
                yield transaction

    def test_dcc_business_mti_over_iso_network_mti(self):
        for transaction in self.classify("non financial request, MTI = 4820 - DCC Inquiry", "910000"):
            self.assertEqual(select_iso_mti(transaction), "4820")
            self.assertEqual(select_transaction_type(transaction), "DCC Inquiry (ISOreq)")

    def test_processing_code_alone_does_not_identify_dcc(self):
        for transaction in self.classify("request", "910000"):
            self.assertEqual(select_transaction_type(transaction), "Network_Management (ISOreq)")

    def test_explicit_network_operation(self):
        for description, expected in (("Logon request", "LOGON (ISOreq)"), ("Echo request", "ECHO (ISOreq)")):
            for transaction in self.classify(description, "910000"):
                self.assertEqual(select_transaction_type(transaction), expected)

    def test_generic_0800_is_not_logon(self):
        for transaction in self.classify("network management request"):
            self.assertEqual(select_transaction_type(transaction), "Network_Management (ISOreq)")

    def test_echo_mti_over_generic_network_mti(self):
        for transaction in self.classify("request", "910000", extra_mti="7080"):
            self.assertEqual(select_transaction_type(transaction), "ECHO (ISOreq)")

    def test_observed_request_and_response_labels(self):
        for description, expected in (("Logon request", "LOGON"), ("Echo request", "ECHO"), ("MTI = 4820 - DCC Inquiry", "DCC Inquiry")):
            for transaction in self.classify(description):
                response = parse_block("Process name : OPNBISOBKT01\nFlow type : response, ref: 123\n", 1)
                transaction.add(response)
                self.assertEqual(select_transaction_type(transaction), expected + " (ISOreq-ISOresp)")
                transaction.operation_flows = {"ISO:response": transaction.operation_flows["ISO:response"]}
                self.assertEqual(select_transaction_type(transaction), expected + " (ISOresp)")

    def test_internal_response_does_not_complete_operation(self):
        for transaction in self.classify("Logon request"):
            transaction.add(parse_block("Process name : INTERNAL01\nFlow type : response\n", 1))
            self.assertEqual(select_transaction_type(transaction), "LOGON (ISOreq)")

    def test_business_and_iso_types_show_observed_phases(self):
        cases = (("4530", "Purchase"), ("4534", "Refund"), ("4554", "Purchase_Void"),
                 ("4546", "Purchase_Reversal"), ("4013", "Pre-auth"),
                 ("0200", "Financial"), ("0210", "Financial"))
        for parser in (parse_block, parse_block_for_list):
            for mti, label in cases:
                for flows in (("request",), ("response",), ("request", "response")):
                    with self.subTest(parser=parser.__name__, mti=mti, flows=flows):
                        transaction = Transaction("test", 0)
                        for i, flow in enumerate(flows):
                            transaction.add(parser(
                                f"Process name : OPNBISOBKT01\nFlow type : {flow}, ref: 123\n"
                                f"Message type : MTI = {mti}\n", i))
                        expected = label + " (" + "-".join(({"request": "ISOreq", "response": "ISOresp"}[flow]) for flow in flows) + ")"
                        self.assertEqual(select_transaction_type(transaction), expected)

    def test_de070_distinguishes_logon_echo_in_both_parsers(self):
        formats = ('70. networkManagementCode : asc<{code}>',
                   '70. arbitraryHostFieldName : int<{code}>',
                   'DE070 : asc<{code}>', 'DE070 : {code}',
                   '<field name="DE070">{code}</field>',
                   '<field name="networkManagementInformationCode">{code}</field>')
        for parser in (parse_block, parse_block_for_list):
            for code, label in (("001", "LOGON"), ("1", "LOGON"), ("301", "ECHO")):
                for template in formats:
                    for acquirer in ("050", "065"):
                        transaction = Transaction("test", 0)
                        for i, (mti, flow) in enumerate((("0800", "request"), ("0810", "response"))):
                            text = (f"Process name : OPNBISOBKT01\nFlow type : {flow}\n"
                                    "Message type : non financial request, MTI = 4820\n"
                                    f"msgId : asc<{mti}>\nacqId : asc<{acquirer}>\n"
                                    + template.format(code=code))
                            transaction.add(parser(text, i))
                            suffix = " (ISOreq)" if i == 0 else " (ISOreq-ISOresp)"
                            with self.subTest(parser=parser.__name__, code=code, template=template):
                                self.assertEqual(select_transaction_type(transaction), label + suffix)

    def test_de070_is_scoped_to_opn_network_messages(self):
        for parser in (parse_block, parse_block_for_list):
            for process, mti in (("PTMS01", "0800"), ("OPNBISOBKT01", "0200")):
                transaction = Transaction("test", 0)
                transaction.add(parser(f"Process name : {process}\nmsgId : asc<{mti}>\nDE070 : asc<301>\n", 0))
                self.assertEqual(transaction.network_management_codes, set())

    def test_unknown_de070_does_not_imply_logon_or_echo(self):
        for parser in (parse_block, parse_block_for_list):
            transaction = Transaction("test", 0)
            transaction.add(parser("Process name : OPNBISOBKT01\nFlow type : response\nmsgId : asc<0810>\nDE070 : asc<999>\n", 0))
            self.assertEqual(select_transaction_type(transaction), "Network_Management (ISOresp)")

    def test_purchase_with_dcc_data_stays_purchase(self):
        for transaction in self.classify("DCC Inquiry", "910000", "4530"):
            self.assertEqual(select_transaction_type(transaction), "Purchase (ISOreq)")


if __name__ == "__main__":
    unittest.main()
