// Measure all filtered rows, including rows outside the virtual-scroll viewport.
export function measureColumnWidths(columns, rows, context, bodyFont, headerFont) {
  const widths = {};
  const glyphs = new Map();
  const glyphWidth = character => {
    if (!glyphs.has(character)) glyphs.set(character, context.measureText(character).width);
    return glyphs.get(character);
  };
  for (const column of columns) {
    context.font = headerFont;
    const heading = context.measureText(String(column.label ?? column.name)).width;
    context.font = bodyFont;
    let maximum = 0;
    const seen = new Set();
    for (const row of rows) {
      const fullText = String(row[column.field ?? column.name] ?? '');
      const text = column.name === 'possibleproblem' && fullText.length > 100 ? fullText.slice(0,97) + '...' : fullText;
      if (seen.has(text)) continue;
      seen.add(text);
      // Glyph sums avoid expensive full-string canvas measurements for short values.
      let estimate = 0;
      for (const character of text) estimate += glyphWidth(character);
      if (estimate + 4 >= maximum) maximum = Math.max(maximum, context.measureText(text).width);
    }
    widths[column.name] = Math.ceil(Math.max(maximum + 20, heading + 20 + (column.sortable ? 24 : 0)));
  }
  return widths;
}

export function fitColumnWidths(columns, natural, available, selectionWidth=44, minimum={}) {
  const budget = Math.max(0, Math.floor(available - selectionWidth));
  const sum = values => values.reduce((total, value) => total + value, 0);
  const preferred = columns.map(c => natural[c.name]);
  if (sum(preferred) <= budget) return {...natural};
  const minima = columns.map(c => Math.min(natural[c.name], minimum[c.name] ?? 48));
  const minimumTotal = sum(minima);
  const extraTotal = sum(preferred) - minimumTotal;
  const targets = minimumTotal > budget
    ? minima.map(width => width * budget / minimumTotal)
    : preferred.map((width,index) => minima[index] + (width-minima[index]) * (budget-minimumTotal) / extraTotal);
  const fitted = targets.map(Math.floor);
  let remaining = budget - sum(fitted);
  const order = targets.map((width,index) => ({index,fraction:width-fitted[index]}))
    .sort((a,b) => b.fraction-a.fraction);
  for (const {index} of order) {
    if (remaining-- <= 0) break;
    fitted[index]++;
  }
  return Object.fromEntries(columns.map((column,index) => [column.name,fitted[index]]));
}

export function installColumnSizing(component) {
  if (!component) return;
  if (component.__logColumnSizer) { component.__logColumnSizer(); return; }
  const table = component.$refs.qRef;
  const root = component.$el;
  const context = document.createElement('canvas').getContext('2d');
  let frame = null, cacheKey = '', widths = {};
  const manualWidths = new Map();
  const fit = async () => {
    frame = null;
    await component.$nextTick();
    if (!root.isConnected) return;
    const htmlTable = root.querySelector('table');
    if (!htmlTable) return;
    const visible = table.visibleColumns;
    const columns = component.columns.filter(column => !visible || visible.includes(column.name));
    const size = parseFloat(getComputedStyle(root).getPropertyValue('--log-font')) || 10;
    const family = getComputedStyle(root).fontFamily;
    const bodyFont = `400 ${size}px ${family}`;
    const headerFont = `800 ${size + 2}px ${family}`;
    const revision = root.getAttribute('data-column-revision') || '';
    const key = JSON.stringify([revision, bodyFont, headerFont, columns.map(c => [c.name, c.label])]);
    if (key !== cacheKey) {
      widths = measureColumnWidths(columns, table.rows || [], context, bodyFont, headerFont);
      cacheKey = key;
    }
    const middle = root.querySelector('.q-table__middle');
    const available = Math.max(0, (middle?.clientWidth || root.clientWidth) - 2);
    const selectionWidth = table.selection && table.selection !== 'none' ? 44 : 0;
    context.font = headerFont;
    const minimum = Object.fromEntries(columns.map(column => [column.name,
      Math.ceil(context.measureText(String(column.label ?? column.name)).width + 20 + (column.sortable ? 24 : 0))]));
    const fitted = fitColumnWidths(columns, widths, available, selectionWidth, minimum);
    for (const column of columns) {
      if (manualWidths.has(column.name)) fitted[column.name] = manualWidths.get(column.name);
    }
    let total = selectionWidth;
    for (const column of columns) {
      const width = fitted[column.name];
      column.style = `width:${width}px;min-width:${width}px;max-width:${width}px`;
      column.headerStyle = column.style;
      total += width;
    }
    // A colgroup fixes the physical tracks too: custom QTd slots and cell
    // padding must not let the browser expand the last column off screen.
    let colgroup = htmlTable.querySelector('colgroup');
    if (!colgroup) {
      colgroup = document.createElement('colgroup');
      htmlTable.prepend(colgroup);
    }
    const tracks = [...(selectionWidth ? [selectionWidth] : []), ...columns.map(column => fitted[column.name])];
    colgroup.innerHTML = tracks.map(width => `<col style="width:${width}px">`).join('');
    htmlTable.style.maxWidth = manualWidths.size ? 'none' : '100%';
    htmlTable.style.tableLayout = 'fixed';
    htmlTable.style.width = `${total}px`;
    htmlTable.style.minWidth = `${total}px`;
    if (middle && !manualWidths.size) middle.scrollLeft = 0;
    await component.$nextTick();
    const headers = Array.from(htmlTable.querySelectorAll('thead th'));
    columns.forEach((column, index) => {
      const header = headers[index + (selectionWidth ? 1 : 0)];
      if (!header || header.querySelector('.column-resizer')) return;
      const handle = document.createElement('span');
      handle.className = 'column-resizer';
      handle.title = 'Drag to resize; double-click to reset';
      handle.tabIndex = 0;
      handle.setAttribute('role', 'separator');
      handle.setAttribute('aria-orientation', 'vertical');
      handle.setAttribute('aria-label', `Resize ${column.label ?? column.name}`);
      handle.style.cssText = 'position:absolute;right:0;top:0;width:8px;height:100%;cursor:col-resize;touch-action:none;z-index:3';
      handle.addEventListener('click', event => event.stopPropagation());
      handle.addEventListener('dblclick', event => {
        event.preventDefault(); event.stopPropagation();
        manualWidths.delete(column.name); schedule();
      });
      handle.addEventListener('keydown', event => {
        if (!['ArrowLeft', 'ArrowRight', 'Home'].includes(event.key)) return;
        event.preventDefault(); event.stopPropagation();
        if (event.key === 'Home') manualWidths.delete(column.name);
        else manualWidths.set(column.name, Math.max(48, Math.round(header.getBoundingClientRect().width) + (event.key === 'ArrowRight' ? 10 : -10)));
        schedule();
      });
      handle.addEventListener('pointerdown', event => {
        event.preventDefault(); event.stopPropagation();
        const start = event.clientX;
        const width = header.getBoundingClientRect().width;
        const move = next => {
          manualWidths.set(column.name, Math.max(48, Math.round(width + next.clientX - start)));
          schedule();
        };
        const stop = () => {
          window.removeEventListener('pointermove', move);
          window.removeEventListener('pointerup', stop);
          window.removeEventListener('pointercancel', stop);
        };
        window.addEventListener('pointermove', move);
        window.addEventListener('pointerup', stop);
        window.addEventListener('pointercancel', stop);
      });
      header.appendChild(handle);
    });
  };
  const schedule = () => {
    if (frame === null) frame = requestAnimationFrame(fit);
  };
  component.__logColumnSizer = schedule;
  component.$watch(() => [table.rows, component.columns, table.visibleColumns], schedule);
  const observer = new MutationObserver(schedule);
  observer.observe(root, {attributes:true, attributeFilter:['style', 'data-column-revision']});
  const resizeObserver = new ResizeObserver(schedule);
  resizeObserver.observe(root.querySelector('.q-table__middle') || root);
  schedule();
}
