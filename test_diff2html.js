// Tests the actual vendored renderer and synchronized scrolling without a browser.
const assert = require('node:assert/strict');
const {Diff2HtmlUI} = require('./logcomparator_ui/assets/diff2html-ui-base.min.js');
const left = {scrollTop: 0, scrollLeft: 0, addEventListener(type, fn) { this[type] = fn; }};
const right = {scrollTop: 0, scrollLeft: 0, addEventListener(type, fn) { this[type] = fn; }};
const wrapper = {querySelectorAll() { return [left, right]; }};
const target = {innerHTML: '', querySelectorAll() { return [wrapper]; }};
const diff = '--- first.log\n+++ second.log\n@@ -1 +1 @@\n-<script>alert(1)</script>\n+Approved(00)\n';
new Diff2HtmlUI(target, diff, {
  outputFormat: 'side-by-side', drawFileList: false, highlight: false,
  synchronisedScroll: true, fileListToggle: false,
  fileContentToggle: false, stickyFileHeaders: false,
}).draw();
assert(target.innerHTML.includes('d2h-file-side-diff'));
assert(target.innerHTML.includes('d2h-ins'));
assert(target.innerHTML.includes('d2h-del'));
assert(target.innerHTML.includes('&lt;script&gt;'));
assert(!target.innerHTML.includes('<script>'));
left.scrollTop = 120;
left.scrollLeft = 40;
left.scroll({target: left});
assert.equal(right.scrollTop, 120);
assert.equal(right.scrollLeft, 40);
console.log('diff2html renders two safe panes with synchronized scrolling');
