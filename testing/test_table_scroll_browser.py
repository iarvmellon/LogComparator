"""Regression for CSS collapsing Quasar virtual-scroll spacer cells."""
import ast
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import subprocess
import tempfile
from threading import Thread
import nicegui
import pytest


@pytest.mark.parametrize('row_count', [2, 25, 87, 99, 100, 10000])
def test_virtual_scroll_keeps_spacer_heights_and_last_transactions(row_count):
    edge = Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
    if not edge.is_file():
        pytest.skip('Microsoft Edge is not installed')
    tree = ast.parse(Path('web_app.py').read_text(encoding='utf-8'))
    css = next(node.value.value for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'CSS' for t in node.targets))
    slot = next(node.args[1].value for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'add_slot' and len(node.args) > 1
                and isinstance(node.args[0], ast.Constant) and node.args[0].value == 'body')
    from web_services import COLUMNS
    package = Path(nicegui.__file__).parent
    class Handler(SimpleHTTPRequestHandler):
        fixture = b''
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(package), **kwargs)
        def do_GET(self):
            if self.path == '/table_sizing.js':
                self.send_response(200)
                self.send_header('Content-Type', 'text/javascript')
                self.end_headers()
                self.wfile.write(Path('logcomparator_ui/assets/table_sizing.js').read_bytes())
            elif self.path == '/fixture':
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
import {installColumnSizing} from '/table_sizing.js';
window.Vue = Vue;
try {
  const tag = document.createElement('script'); tag.src='/static/quasar.umd.prod.js';
  const loaded = new Promise((resolve,reject)=>{tag.onload=resolve;tag.onerror=reject;});
  document.head.appendChild(tag); await loaded;
  const rows = Array.from({length:__ROW_COUNT__}, (_,i)=>Object.fromEntries(__COLUMNS__.map(([key])=>[key,key==='transuid'?'TRX-'+String(i+1).padStart(5,'0'):'value'])));
  for(const row of rows){row.transuid_display=row.transuid;row.preview_url='#'+row.transuid;row.severity='approved';}
  const Slot = {props:{props:Object},template:__SLOT__};
  const table = Vue.ref();
  const app = Vue.createApp({setup(){return ()=>Vue.h(Table, {ref:table, class:'log-table', style:'flex:1;min-height:0', columns:__COLUMNS__.map(([name,label])=>({name,label,field:name==='transuid'?'transuid_display':name,align:'left',sortable:true})), rows, rowKey:'transuid', dense:true, virtualScroll:__ROW_COUNT__>100, selection:'multiple',selected:[], pagination:{rowsPerPage:__PAGE_SIZE__}}, {body:props=>Vue.h(Slot,{props})});}});
  app.use(window.Quasar); app.mount('#app');
  const pause = ()=>new Promise(resolve=>setTimeout(resolve,200));
  await pause();
  installColumnSizing(table.value);
  await pause();
  const middle = document.querySelector('.q-table__middle');
  for (let step=1;step<=20;step++) {middle.scrollTop=(middle.scrollHeight-middle.clientHeight)*step/20; middle.dispatchEvent(new Event('scroll')); await pause();}
  middle.scrollTop=middle.scrollHeight; middle.dispatchEvent(new Event('scroll')); await pause();
  const spacers = [...document.querySelectorAll('.q-virtual-scroll__padding td')];
  for (const cell of spacers) {
    const expected = parseFloat(cell.style.height);
    const actual = parseFloat(getComputedStyle(cell).height);
    if (Math.abs(expected-actual)>2) throw Error('Spacer height '+actual+' differs from '+expected);
  }
  const visible = ()=>middle.querySelector('table').textContent;
  if (__ROW_COUNT__<=100 && spacers.length) throw Error('Short page must use normal scrolling');
  if (__ROW_COUNT__<=100) {
    const dataRows = [...middle.querySelectorAll('tbody tr')];
    if (dataRows.length !== __ROW_COUNT__) throw Error('Unexpected empty/padded rows: '+dataRows.length);
    if (dataRows.some(row=>!row.textContent.trim())) throw Error('Empty transaction row');
  }
  if (!visible().includes('TRX-__LAST_UID__')) throw Error('Last transaction missing: '+visible());
  const lastRow = [...middle.querySelectorAll('tbody tr')].find(row=>row.textContent.includes('TRX-__LAST_UID__'));
  if (!lastRow || lastRow.getBoundingClientRect().top >= middle.getBoundingClientRect().bottom) throw Error('Last transaction is outside viewport');
  const lastTop = middle.scrollTop;
  middle.scrollTop += 1000; middle.dispatchEvent(new Event('scroll'));
  await pause(); await pause();
  if (!visible().includes('TRX-__LAST_UID__') || Math.abs(middle.scrollTop-lastTop)>2) throw Error('Scroll position jumped after reaching the end');
  document.querySelector('#result').textContent='SCROLL_PASS';
} catch(error) {document.querySelector('#result').textContent='SCROLL_FAIL: '+error;}
"""
    script = script.replace('__SLOT__', json.dumps(slot)).replace('__COLUMNS__', json.dumps(COLUMNS)).replace('__PAGE_SIZE__','0' if row_count > 100 else '100').replace('__ROW_COUNT__',str(row_count)).replace('__LAST_UID__',f'{row_count:05}')
    Handler.fixture = ('<!doctype html><html><head><link rel="stylesheet" href="/static/quasar.important.prod.css"><style>'+css+'</style></head><body><div class="workspace column nicegui-content" style="height:700px"><div style="height:180px">Controls</div><div id="app" class="column" style="flex:1;min-height:0"></div><footer style="height:28px">Status</footer></div><pre id="result">WAITING</pre><script type="module">'+script+'</script></body></html>').encode()
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix='logcomparator-scroll-test-') as folder:
            result = subprocess.run([str(edge),'--headless=new','--no-first-run','--disable-gpu','--disable-extensions','--user-data-dir='+folder,'--virtual-time-budget=16000','--dump-dom',base+'/fixture'], capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
            status = re.findall(r'<pre id="result">(.*?)</pre>',result.stdout)
            assert status == ['SCROLL_PASS'], str(status)+result.stderr[-300:]
    finally:
        server.shutdown()
        server.server_close()
