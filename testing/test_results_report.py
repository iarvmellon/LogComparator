from html.parser import HTMLParser
from web_services import render_results_report


class ReportParser(HTMLParser):
    def __init__(self, document):
        super().__init__()
        self.tags = []
        self.text = []
        self.feed(document)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, value):
        self.text.append(value)


def test_report_preserves_order_columns_selections_colors_and_escapes_text():
    problem = '<script>alert("unsafe")</script>' + 'x' * 120
    rows = [
        dict(transuid='second', severity='problem', responsecodeiso='Declined(05)', responsecodeiso_alert=True, possibleproblem=problem, hidden='secret'),
        dict(transuid='first', severity='approved', responsecodeiso='Approved(00)', possibleproblem=''),
    ]
    columns = [('transuid', 'TransUID'), ('responsecodeiso', 'RC_ISO'), ('possibleproblem', 'Possible problem')]
    document = render_results_report(rows, columns, [('Bank/Acquirer', 'A&B'), ('Active filters', '<test>')], ['second'])
    report = ReportParser(document)
    assert document.index('second') < document.index('first')
    assert '<script>' not in document
    assert 'secret' not in document
    assert '&#9745;' in document and '&#9744;' in document
    assert [text for tag, text in report.tags if tag == 'tr'][1:] == [{'style': 'background:#ff9999'}, {'style': 'background:#c8f7c5'}]
    assert any(attrs.get('title') == problem for tag, attrs in report.tags if tag == 'td')
    assert problem[:97] + '...' in report.text
    assert 'A&B' in report.text and '<test>' in report.text
    assert sum('color:#b00020' in attrs.get('style', '') for _, attrs in report.tags) == 1
    assert 'Transactions: 2' in ''.join(report.text)


def test_empty_report_retains_settings_and_headers():
    document = render_results_report([], [('transuid', 'TransUID')], [('Consistency viewer', 'None')])
    assert 'Transactions: 0' in document
    assert '<th>TransUID</th>' in document
    assert '<dt>Consistency viewer</dt><dd>None</dd>' in document
