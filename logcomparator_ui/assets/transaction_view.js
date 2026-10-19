// Keep the initial preview small. Download always returns the original full file.
window.logComparatorShowTransaction = async function (dataUrl) {
  const log = document.getElementById('log');
  const error = document.getElementById('error');
  const status = document.getElementById('log-status');
  const more = document.getElementById('more');
  const all = document.getElementById('all');
  let current, reading = false;
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
        log.appendChild(document.createTextNode(data.text));
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
    log.textContent = current.text;
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
