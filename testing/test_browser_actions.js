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
  console.log('Direct multi-tab opening and comparison loading, rendering, download and errors passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
