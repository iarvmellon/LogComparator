const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {Diff2HtmlUI} = require('../logcomparator_ui/assets/diff2html-ui-base.min.js');

(async () => {
  const calls=[];
  const window={open:(url,target)=>{calls.push([url,target]);return calls.length===1 ? {} : null;}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../logcomparator_ui/assets/open_tabs.js'),'utf8'),{window});
  const blocked=window.logComparatorOpenTabs(['/transaction/first','/transaction/second']);
  assert.deepEqual(calls,[['/transaction/first','_blank'],['/transaction/second','_blank']]);
  assert.deepEqual(Array.from(blocked),['/transaction/second']);

  const html=fs.readFileSync(path.join(__dirname,'../logcomparator_ui/assets/comparison.html'),'utf8');
  const script=html.match(/<script>([\s\S]*?)<\/script>/)[1].replace('__COMPARISON_DATA_URL__',JSON.stringify('/comparison-data/test'));
  async function render(data,ok=true) {
    const left={addEventListener(){}};
    const right={addEventListener(){}};
    const wrapper={querySelectorAll:()=>[left,right]};
    const elements={};
    for (const id of ['names','actions','loading','error','download','previous','next']) elements[id]={hidden:id==='actions',textContent:''};
    elements['diff2html-comparison']={innerHTML:'',querySelectorAll:()=>[wrapper],querySelector:()=>null};
    await vm.runInNewContext(script,{
      document:{getElementById:id=>elements[id]},
      window:{Diff2HtmlUI:{Diff2HtmlUI},addEventListener(){}},
      fetch:async url=>{assert.equal(url,'/comparison-data/test');return {ok,json:async()=>data};},
      URL:{createObjectURL:()=> 'blob:comparison',revokeObjectURL(){}},Blob,
    });
    return elements;
  }
  const diff='--- left.log\n+++ right.log\n@@ -1 +1 @@\n-<script>alert(1)</script>\n+Approved(00)\n';
  const ready=await render({left:'left.log',right:'right.log',diff});
  assert(ready['diff2html-comparison'].innerHTML.includes('d2h-file-side-diff'));
  assert(ready['diff2html-comparison'].innerHTML.includes('&lt;script&gt;'));
  assert.equal(ready.actions.hidden,false,ready.error.textContent);
  assert.equal(ready.loading.hidden,true);
  assert.equal(ready.download.href,'blob:comparison');
  assert.equal(typeof ready.next.onclick,'function');
  const identical=await render({left:'left',right:'right',diff:''});
  assert.equal(identical.actions.hidden,true);
  assert.equal(identical['diff2html-comparison'].textContent,'The exported logs are identical.');
  const failed=await render({error:'Export failed'},false);
  assert.equal(failed.loading.hidden,true);
  assert(failed.error.textContent.includes('Export failed'));
  const transactionScript=fs.readFileSync(path.join(__dirname,'../logcomparator_ui/assets/transaction_view.js'),'utf8');
  async function transaction(responses) {
    function node() { return {children:[],value:'',hidden:false, set textContent(v){this.value=v;this.children=[];},get textContent(){return this.value+this.children.map(c=>c.textContent).join('');},appendChild(child){if(child.fragment){for(const c of [...child.children])this.appendChild(c);}else{this.children.push(child);child.parent=this;}},remove(){this.parent.children=this.parent.children.filter(c=>c!==this);}}; }
    const elements={};
    for (const id of ['log','error','log-status','more','all','download','loading']) elements[id]=Object.assign(node(),{hidden:['error','more','all','download'].includes(id)});
    const calls=[];
    const context={window:{},setTimeout,
      document:{getElementById:id=>elements[id],createElement:()=>node(),createDocumentFragment:()=>Object.assign(node(),{fragment:true})},
      fetch:async url=>{calls.push(url);const data=responses[url];assert(data,`Unexpected request: ${url}`);return {ok:!data.error,json:async()=>data};},
    };
    vm.runInNewContext(transactionScript,context);
    assert.equal(context.window.logComparatorLogLineClass('transUId : 123'), 'log-blue');
    assert.equal(context.window.logComparatorLogLineClass('responseCode=051'), 'log-red');
    assert.equal(context.window.logComparatorLogLineClass('responseCode=000'), 'log-blue');
    assert.equal(context.window.logComparatorLogLineClass('plain <script>'), '');
    await context.window.logComparatorShowTransaction('/initial');
    return {elements,calls};
  }
  const preview=await transaction({
    '/initial':{text:'first',next_offset:5,total_bytes:9,has_more:true,chunk_url:'/chunk',download_url:'/full'},
    '/chunk?offset=5':{text:'last',next_offset:9,total_bytes:9,has_more:false},
  });
  assert.equal(preview.elements.log.textContent,'first');
  assert.equal(preview.elements.more.hidden,false);
  assert.equal(preview.elements.loading.hidden,true);
  assert.equal(preview.elements.download.href,'/full');
  assert(preview.elements['log-status'].textContent.includes('Download log contains the full file'));
  assert.deepEqual(preview.calls,['/initial']);
  await preview.elements.more.onclick();
  assert.equal(preview.elements.log.textContent,'firstlast');
  assert.equal(preview.elements.more.hidden,true);
  const full=await transaction({
    '/initial':{text:'A',next_offset:1,total_bytes:3,has_more:true,chunk_url:'/chunk',download_url:'/full'},
    '/chunk?offset=1':{text:'B',next_offset:2,total_bytes:3,has_more:true},
    '/chunk?offset=2':{text:'C',next_offset:3,total_bytes:3,has_more:false},
  });
  await full.elements.all.onclick();
  assert.equal(full.elements.log.textContent,'ABC');
  assert.equal(full.elements.all.hidden,true);
  const broken=await transaction({
    '/initial':{text:'visible',next_offset:7,total_bytes:20,has_more:true,chunk_url:'/chunk',download_url:'/full'},
    '/chunk?offset=7':{error:'Read failed'},
  });
  await broken.elements.more.onclick();
  assert.equal(broken.elements.log.textContent,'visible');
  assert(broken.elements.error.textContent.includes('Read failed'));
  assert.equal(broken.elements.more.disabled,false);
  console.log('Direct tabs, comparison viewer and progressive transaction preview passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
