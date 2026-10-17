// The macro page's router (plan 0028): one document, views switched by the URL hash; the "As of" select reloads the
// document for that date (?as_of=), keeping the chapter or view you are on. Reading progress stays in this browser.
(function () {
  const M = window.MACRO || { ids: [], latest: null, asOf: null };
  const IDS = M.ids;
  const KEY = 'macro-read-v5';
  const store = {
    get() { try { return JSON.parse(localStorage.getItem(KEY) || '[]'); } catch (e) { return []; } },
    add(n) { try { const s = new Set(this.get()); s.add(n); localStorage.setItem(KEY, JSON.stringify([...s])); } catch (e) {} },
  };
  function paint() {
    const read = new Set(store.get());
    document.querySelectorAll('.toc-i').forEach(a => a.classList.toggle('read', read.has(a.dataset.ch)));
    const bar = document.getElementById('toc-bar');
    if (bar) bar.style.width = (100 * IDS.filter(i => read.has(i)).length / Math.max(1, IDS.length)) + '%';
    const t = document.getElementById('prog-text');
    const n = IDS.filter(i => read.has(i)).length;
    if (t) t.textContent = n ? `· ${n} of ${IDS.length} chapters read` : '';
  }
  function tellParent(h) {
    if (window.parent === window) return;
    try { window.parent.postMessage({ macro: 1, asOf: M.asOf, latest: M.latest, hash: h ? '#' + h : '' }, location.origin); } catch (e) {}
  }
  function route() {
    const h = (location.hash || '#start').slice(1);
    document.querySelectorAll('[data-view]').forEach(v => v.classList.remove('show'));
    let nav = 'start';
    if (IDS.includes(h)) {
      document.querySelector('[data-view="learn-shell"]').classList.add('show');
      document.querySelector(`[data-view="${h}"]`).classList.add('show');
      store.add(h);
      nav = h === 'pro' ? 'start' : (h.startsWith('in-') ? 'india' : h.startsWith('gl-') ? 'global' : 'synthesis');
      document.querySelectorAll('.toc-i').forEach(a => a.classList.toggle('on', a.dataset.ch === h));
      const cur = document.querySelector(`.toc-i[data-ch="${h}"]`), toc = document.querySelector('.toc');
      if (cur && toc) toc.dataset.track = cur.dataset.track;   // phones show only this track's chapters
    } else {
      (document.querySelector(`[data-view="${h}"]`) || document.querySelector('[data-view="start"]')).classList.add('show');
      nav = h.startsWith('deeper') ? 'deeper' : (h === 'today' ? 'today' : (h === 'archive' ? 'archive' : 'start'));
    }
    document.querySelectorAll('#topnav a').forEach(a => a.classList.toggle('on', a.dataset.nav === nav));
    paint();
    markWide();
    window.scrollTo(0, 0);
    tellParent(h);
  }
  // a chart wider than a phone scrolls sideways inside its figure; say so once under it
  function markWide() {
    document.querySelectorAll('[data-view].show .fig').forEach(f => {
      const wide = f.scrollWidth > f.clientWidth + 4;
      f.classList.toggle('scrollx', wide);
      if (wide && !f.querySelector(':scope > .swipe-hint')) {
        const h = document.createElement('div'); h.className = 'swipe-hint'; h.textContent = 'Swipe the chart sideways to see all of it →';
        f.appendChild(h);
      }
    });
  }
  window.addEventListener('resize', markWide);
  window.addEventListener('hashchange', route);
  const sel = document.getElementById('asof');
  if (sel) sel.addEventListener('change', e => {
    const v = e.target.value;
    location.href = (v === M.latest ? location.pathname : location.pathname + '?as_of=' + v) + (location.hash || '#today');
  });
  // the shelf's older links pointed at the v2 lesson numbers; send them to the chapters that replaced them
  const LESSON = { '1': 'pro', '2': 'in-1', '3': 'in-2', '4': 'in-3', '5': 'in-4', '6': 'in-5', '7': 'in-6', '8': 'gl-2', '9': 'in-7', '10': 'sy-1', '11': 'sy-2', '12': 'sy-3' };
  document.querySelectorAll('a[href="#learn"]').forEach(a => a.setAttribute('href', '#deeper-lesson3'));
  document.querySelectorAll('a[href^="#learn-"]').forEach(a => { const m = LESSON[a.getAttribute('href').slice(7)]; if (m) a.setAttribute('href', '#' + m); });
  route();
})();
