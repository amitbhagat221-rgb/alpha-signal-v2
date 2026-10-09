// Lazy tab panels (ops cockpit): a heavy tab ships as a partial and is fetched the first time it opens.
//   <div x-show="tab === 'x'" x-cloak x-data="lazyTab('/system/tab/x')" x-effect="if (tab === 'x') load()">
//     <div x-show="busy" role="status">Loading…</div>
//     <div x-show="err"><span x-text="err"></span> <button type="button" @click="load()">Retry</button></div>
//     <div x-html="html"></div>
//   </div>
// x-html initialises any Alpine inside the partial; sortable tables in it are wired afterwards.
window.lazyTab = function (url) {
  return {
    html: '', err: '', busy: false,
    async load() {
      if (this.html || this.busy) return;
      this.busy = true; this.err = '';
      try {
        const r = await fetch(url);
        if (!r.ok) throw new Error('HTTP ' + r.status);
        this.html = await r.text();
        this.$nextTick(() => { if (window.initSortableTables) window.initSortableTables(this.$el); });
      } catch (e) {
        this.err = 'Could not load this tab (' + e.message + ').';
      } finally {
        this.busy = false;
      }
    },
  };
};
