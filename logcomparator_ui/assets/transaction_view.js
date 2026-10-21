// Built-in log highlighting; red response/result matches take precedence.
const logComparatorLexerRules = {"blue": ["^[ \\t]*responseCode[ \\t:'\">=].*$", ".*[ \\t.'\"/]responseCode[ \\t:'\">=].*", ".*\\bresultCode\\b.*", ".*\\bretrievRefNumber\\b.*", "^[ \\t]*RRN[ \\t]*:.*$", ".*\\bMTI\\b.*", "^.*transU[Ii][Dd].*$"], "red": ["^[ \\t]*Result Code[ \\t]*:[ \\t]*(?:[1-9]\\d*|0\\d+)[ \\t]*$", "^[ \\t]*Response Code[ \\t]*:[ \\t]*(?:[1-9]\\d{2}|0[1-9]\\d|00[1-9])[ \\t]*$", "^[ \\t]*Network RC[ \\t]*:[ \\t]*(?:[1-9]\\d|0[1-9])(?:[ \\t]|\\().*$", "^\\[ISO\\].*\\((?!00\\)[ \\t]*$)\\d{2}\\)[ \\t]*$", "^\\[SPDH\\].*\\((?!000\\)[ \\t]*$)\\d{3}\\)[ \\t]*$", "^[ \\t]*responseCode=(?:050|051|052|053|054|055|056|057|059|060|061|062|063|064|065|066|067|068|069|070|071|072|073|074|075|076|077|078|079|080|081|082|083|084|085|086|087|088|089|090|091|092|093|094|095|096|097|098|099|100|101|102|103|104|105|106|107|108|109|110|111|112|113|114|120|121|122|130|131|132|133|134|200|201|202|203|204|205|206|251|400|401|402|403|404|405|406|407|408|500|501|800|811|878|888|889|899|900|901|902|903|904|905|906|907|908|909|910|911|912|950|951|952|954|955|956|957|958|960|961|962|01|03|04|05|12|13|14|30|41|43|51|54|55|56|57|58|61|62|65|68|75|78|86|91|94|96)\\b.*$", ".*[ \\t.'\"/]responseCode=(?:050|051|052|053|054|055|056|057|059|060|061|062|063|064|065|066|067|068|069|070|071|072|073|074|075|076|077|078|079|080|081|082|083|084|085|086|087|088|089|090|091|092|093|094|095|096|097|098|099|100|101|102|103|104|105|106|107|108|109|110|111|112|113|114|120|121|122|130|131|132|133|134|200|201|202|203|204|205|206|251|400|401|402|403|404|405|406|407|408|500|501|800|811|878|888|889|899|900|901|902|903|904|905|906|907|908|909|910|911|912|950|951|952|954|955|956|957|958|960|961|962|01|03|04|05|12|13|14|30|41|43|51|54|55|56|57|58|61|62|65|68|75|78|86|91|94|96)\\b", ".*[ \\t.'\"/]responseCode\\s*:\\s*asc<(?:050|051|052|053|054|055|056|057|059|060|061|062|063|064|065|066|067|068|069|070|071|072|073|074|075|076|077|078|079|080|081|082|083|084|085|086|087|088|089|090|091|092|093|094|095|096|097|098|099|100|101|102|103|104|105|106|107|108|109|110|111|112|113|114|120|121|122|130|131|132|133|134|200|201|202|203|204|205|206|251|400|401|402|403|404|405|406|407|408|500|501|800|811|878|888|889|899|900|901|902|903|904|905|906|907|908|909|910|911|912|950|951|952|954|955|956|957|958|960|961|962|01|03|04|05|12|13|14|30|41|43|51|54|55|56|57|58|61|62|65|68|75|78|86|91|94|96)>.*", ".*\\bresultCode=3919\\b.*", ".*\\bresultCode=3090\\b.*", "^.*\\bresponseCode[ \\t]*(?:=[ \\t]*990\\b|:[ \\t]*asc<990>).*$"]};
for (const color of ['red', 'blue']) logComparatorLexerRules[color] = logComparatorLexerRules[color].map(pattern => new RegExp(pattern));
window.logComparatorLogLineClass = function (line) {
  for (const color of ['red', 'blue']) {
    if (logComparatorLexerRules[color].some(pattern => pattern.test(line))) return 'log-' + color;
  }
  return '';
};
// Keep the initial preview small. Download always returns the original full file.
window.logComparatorShowTransaction = async function (dataUrl) {
  const log = document.getElementById('log');
  const error = document.getElementById('error');
  const status = document.getElementById('log-status');
  const more = document.getElementById('more');
  const all = document.getElementById('all');
  let current, reading = false;
  let tail = '', tailNode = null;
  function appendLog(text) {
    if (tailNode) tailNode.remove();
    const lines = (tail + text).split('\n');
    tail = lines.pop();
    const fragment = document.createDocumentFragment();
    for (const line of lines) {
      const node = document.createElement('span');
      node.className = window.logComparatorLogLineClass(line);
      node.textContent = line + '\n';
      fragment.appendChild(node);
    }
    tailNode = document.createElement('span');
    tailNode.className = window.logComparatorLogLineClass(tail);
    tailNode.textContent = tail;
    fragment.appendChild(tailNode);
    log.appendChild(fragment);
  }
  const showError = message => { error.textContent = message; error.hidden = false; };
  async function request(url) {
    const response = await fetch(url, {cache:'no-store'});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not load transaction');
    return data;
  }
  function update() {
    const remaining = Boolean(current.has_more);
    more.hidden = all.hidden = !remaining;
    more.disabled = all.disabled = reading;
    status.textContent = remaining
      ? `Showing ${current.next_offset.toLocaleString()} of ${current.total_bytes.toLocaleString()} bytes. Download log contains the full file.`
      : '';
  }
  async function loadMore(full) {
    if (reading) return;
    reading = true;
    update();
    try {
      do {
        const data = await request(current.chunk_url + '?offset=' + current.next_offset);
        appendLog(data.text);
        current = {...current,...data};
        update();
        // Give the browser an opportunity to render between chunks.
        await new Promise(resolve => setTimeout(resolve, 0));
      } while (full && current.has_more);
    } catch (failure) { showError('Could not load more log text: ' + failure.message); }
    finally { reading = false; update(); }
  }
  more.onclick = () => loadMore(false);
  all.onclick = () => loadMore(true);
  try {
    current = await request(dataUrl);
    appendLog(current.text);
    const download = document.getElementById('download');
    download.href = current.download_url;
    download.hidden = false;
    update();
    if (current.save_url) request(current.save_url).catch(failure => {
      showError('Log opened, but saving the output copy failed: ' + failure.message);
    });
  } catch (failure) { showError('Could not open transaction: ' + failure.message); }
  finally { document.getElementById('loading').hidden = true; }
};
