"""Regression for CSS collapsing Quasar virtual-scroll spacer cells."""
import ast
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import subprocess
import tempfile
from threading import Thread
import nicegui
import pytest


def test_virtual_scroll_keeps_spacer_heights_and_last_transactions():
    edge = Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
    if not edge.is_file():
        pytest.skip('Microsoft Edge is not installed')
    tree = ast.parse(Path('web_app.py').read_text(encoding='utf-8'))
    css = next(node.value.value for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'CSS' for t in node.targets))
    package = Path(nicegui.__file__).parent
    class Handler(SimpleHTTPRequestHandler):
        fixture = b''
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(package), **kwargs)
        def do_GET(self):
            if self.path == '/fixture':
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
    script = r"""
import * as Vue from '/static/vue.esm-browser.prod.js';
import Table from '/elements/table.js';
window.Vue = Vue;
try {
  const tag = document.createElement('script'); tag.src='/static/quasar.umd.prod.js';
  const loaded = new Promise((resolve,reject)=>{tag.onload=resolve;tag.onerror=reject;});
  document.head.appendChild(tag); await loaded;
  const rows = Array.from({length:100}, (_,i)=>({transuid:'TRX-'+String(i+1).padStart(4,'0')}));
  const table = Vue.ref();
  const app = Vue.createApp({setup(){return ()=>Vue.h(Table, {ref:table, class:'log-table', style:'height:400px', columns:[{name:'transuid',field:'transuid',label:'TransUID'}], rows, rowKey:'transuid', dense:true, virtualScroll:true, pagination:{rowsPerPage:100}});}});
  app.use(window.Quasar); app.mount('#app');
  const pause = ()=>new Promise(resolve=>setTimeout(resolve,200));
  await pause();
  const middle = document.querySelector('.q-table__middle');
  for (let step=0;step<5;step++) {middle.scrollTop=middle.scrollHeight; middle.dispatchEvent(new Event('scroll')); await pause();}
  const spacers = [...document.querySelectorAll('.q-virtual-scroll__padding td')];
  for (const cell of spacers) {
    const expected = parseFloat(cell.style.height);
    const actual = parseFloat(getComputedStyle(cell).height);
    if (Math.abs(expected-actual)>2) throw Error('Spacer height '+actual+' differs from '+expected);
  }
  const visible = ()=>document.querySelector('.q-virtual-scroll__content').textContent;
  if (!visible().includes('TRX-0100')) throw Error('Last transaction missing: '+visible());
  const lastTop = middle.scrollTop;
  await pause(); await pause();
  if (!visible().includes('TRX-0100') || Math.abs(middle.scrollTop-lastTop)>2) throw Error('Scroll position jumped after reaching the end');
  document.querySelector('#result').textContent='SCROLL_PASS';
} catch(error) {document.querySelector('#result').textContent='SCROLL_FAIL: '+error;}
"""
    Handler.fixture = ('<!doctype html><html><head><link rel="stylesheet" href="/static/quasar.important.prod.css"><style>'+css+'</style></head><body><div id="app"></div><pre id="result">WAITING</pre><script type="module">'+script+'</script></body></html>').encode()
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix='logcomparator-scroll-test-') as folder:
            result = subprocess.run([str(edge),'--headless=new','--no-first-run','--disable-gpu','--disable-extensions','--user-data-dir='+folder,'--virtual-time-budget=8000','--dump-dom',base+'/fixture'], capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
            status = re.findall(r'<pre id="result">(.*?)</pre>',result.stdout)
            assert status == ['SCROLL_PASS'], str(status)+result.stderr[-300:]
    finally:
        server.shutdown()
        server.server_close()
