"""Render the real row slot in Vue/Quasar and check it in headless Edge."""
import ast
import json
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from pathlib import Path
import subprocess
import tempfile
import unittest

import nicegui


class ContextMenuBrowserTests(unittest.TestCase):
    def test_context_menu_with_zero_one_two_and_three_selections(self):
        edge = Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
        if not edge.is_file():
            self.skipTest('Microsoft Edge is not installed')
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / 'web_app.py').read_text(encoding='utf-8'))
        slot = next(node.args[1].value for node in ast.walk(tree)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'add_slot' and len(node.args) > 1
                    and isinstance(node.args[0], ast.Constant) and node.args[0].value == 'body')
        package = Path(nicegui.__file__).parent
        class Handler(SimpleHTTPRequestHandler):
            fixture = b''

            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(package), **kwargs)

            def do_GET(self):
                if self.path == '/fixture.html':
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.end_headers()
                    self.wfile.write(self.fixture)
                else:
                    super().do_GET()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        base = f'http://127.0.0.1:{server.server_port}'
        script = r''' 
import * as Vue from __VUE__;
import Table from __TABLE__;
window.Vue = Vue;
const errors = [];
window.addEventListener('error', event => errors.push(event.message));
try {
  const quasar = document.createElement('script');
  quasar.src = __QUASAR__;
  const loaded = new Promise((resolve, reject) => { quasar.onload = resolve; quasar.onerror = reject; });
  document.head.appendChild(quasar);
  await loaded;
  const rows = [1, 2, 3].map(i => ({transuid: 'TRX-' + i, preview_url: '#trx-' + i, severity: ''}));
  const selected = Vue.ref([]);
  const events = [];
  const Slot = {props: {props: Object}, template: __SLOT__};
  const proxyMode = Vue.ref(false);
  const ProxySlot = {props: {props: Object}, components: {Slot}, template: '<Slot :props="props" />'};
  const app = Vue.createApp({setup() {return () => Vue.h(Table, {
    columns: [{name: 'transuid', field: 'transuid', label: 'TransUID'}], rows,
    rowKey: 'transuid', selection: 'multiple', selected: selected.value,
    'onUpdate:selected': value => selected.value = value,
    'onContext-action': event => events.push(event),
  }, {body: props => proxyMode.value ? Vue.h(ProxySlot, {props, selected: selected.value, 'onContext-action': event => events.push(event)}) : Vue.h(Slot, {props})});}});
  app.config.errorHandler = error => errors.push(String(error));
  app.use(window.Quasar);
  app.mount('#app');
  const pause = () => new Promise(resolve => setTimeout(resolve, 300));
  for (const mode of [false, true]) {
   proxyMode.value = mode;
   for (const count of [0, 1, 2, 3, 2, 0]) {
    selected.value = rows.slice(0, count);
    await Vue.nextTick();
    document.querySelector(count % 2 ? 'tbody tr a' : 'tbody tr').dispatchEvent(new MouseEvent('contextmenu', {
      bubbles: true, cancelable: true, button: 2, clientX: 80, clientY: 80,
    }));
    await pause();
    const items = Array.from(document.querySelectorAll('.q-menu .q-item'));
    const names = items.map(item => item.textContent.trim());
    const expected = count === 2 ? ['Open', 'Export', 'Compare'] : ['Open', 'Export'];
    if (JSON.stringify(names) !== JSON.stringify(expected)) throw Error('Proxy ' + mode + ', selection ' + count + ': ' + JSON.stringify(names));
    const previousEvents = events.length;
    const click = new MouseEvent('click', {bubbles: true, cancelable: true});
    items.find(item => item.textContent.trim() === 'Export').dispatchEvent(click);
    if (!click.defaultPrevented) throw Error('Export must not open an empty tab');
    await pause();
    if (events.length !== previousEvents + 1 || events.at(-1)?.action !== 'Export' || events.at(-1)?.uid !== 'TRX-1') throw Error('Export event was not emitted');
  }
  }
  if (errors.length) throw Error(errors.join('; '));
  document.querySelector('#result').textContent = 'CONTEXT_MENU_PASS';
} catch (error) {document.querySelector('#result').textContent = 'CONTEXT_MENU_FAIL: ' + error;}
'''
        for token, value in {
            '__VUE__': base + '/static/vue.esm-browser.prod.js',
            '__TABLE__': base + '/elements/table.js',
            '__QUASAR__': base + '/static/quasar.umd.prod.js',
            '__SLOT__': slot,
        }.items():
            script = script.replace(token, json.dumps(value))
        with tempfile.TemporaryDirectory(prefix='logcomparator-menu-test-') as directory:
            folder = Path(directory)
            html = folder / 'menu.html'
            css = base + '/static/quasar.important.prod.css'
            html.write_text('<!doctype html><html><head><link rel="stylesheet" href="' + css
                            + '"></head><body><div id="app"></div><pre id="result">WAITING</pre>'
                            + '<button data-transaction-opener data-open-urls="[]" data-comparison-url="#compare"></button>'
                            + '<script type="module">' + script + '</script></body></html>', encoding='utf-8')
            Handler.fixture = html.read_bytes()
            Thread(target=server.serve_forever, daemon=True).start()
            result = subprocess.run([
                str(edge), '--headless=new', '--no-first-run', '--no-default-browser-check',
                '--disable-gpu', '--allow-file-access-from-files', '--disable-extensions',
                '--user-data-dir=' + str(folder / 'profile'), '--virtual-time-budget=15000',
                '--dump-dom', base + '/fixture.html',
            ], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW)
            server.shutdown()
            server.server_close()
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            status = re.findall(r'<pre id="result">(.*?)</pre>', result.stdout)
            self.assertEqual(status, ['CONTEXT_MENU_PASS'],
                          str(re.findall(r'<pre id="result">(.*?)</pre>', result.stdout)) + result.stderr[-1000:])
