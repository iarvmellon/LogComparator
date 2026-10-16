let resources;
function loadResources() {
  if (!resources) resources = new Promise((resolve, reject) => {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = '/logcomparator-assets/diff2html.min.css';
    document.head.appendChild(link);
    const script = document.createElement('script');
    script.src = '/logcomparator-assets/diff2html-ui-base.min.js';
    script.onload = resolve;
    script.onerror = () => { resources = null; reject(new Error('Could not load the local diff2html library.')); };
    document.head.appendChild(script);
  });
  return resources;
}

export default {
  template: '<div><div v-if="error" role="alert">{{ error }}</div><div ref="target" class="diff2html-view"></div></div>',
  props: {diff: String},
  data() { return {error: '', position: -1}; },
  async mounted() { await this.draw(); },
  watch: {diff() { this.draw(); }},
  methods: {
    async draw() {
      try {
        await loadResources();
        if (!this.$refs.target) return;
        const library = window.Diff2HtmlUI;
        const Constructor = library.Diff2HtmlUI || library;
        const view = new Constructor(this.$refs.target, this.diff, {
          outputFormat: 'side-by-side', drawFileList: false,
          synchronisedScroll: true, highlight: false, matching: 'lines',
          fileContentToggle: false, stickyFileHeaders: false,
        });
        view.draw();
        this.position = -1;
        this.error = '';
      } catch (error) { this.error = error.message; }
    },
    navigate(delta) {
      const lines = this.$refs.target.querySelectorAll('.d2h-del, .d2h-ins');
      if (!lines.length) return;
      this.position = (this.position + delta + lines.length) % lines.length;
      lines[this.position].scrollIntoView({block: 'center', behavior: 'smooth'});
    },
  },
};
