/* Alpha Signal Cockpit — JS */

document.addEventListener('DOMContentLoaded', () => {

    // Conviction bar animation on load
    document.querySelectorAll('.conviction-marker').forEach(marker => {
        const target = marker.style.left;
        marker.style.left = '0%';
        marker.style.transition = 'none';
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                marker.style.transition = 'left 0.8s cubic-bezier(0.34, 1.56, 0.64, 1)';
                marker.style.left = target;
            });
        });
    });

    // Signal bar animation
    document.querySelectorAll('[data-fill]').forEach(bar => {
        const target = bar.style.width;
        bar.style.width = '0%';
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                bar.style.transition = 'width 0.6s ease';
                bar.style.width = target;
            });
        });
    });

    // "/" (or Ctrl/Cmd-K) focuses the global stock search on every page; Escape leaves it.
    document.addEventListener('keydown', (e) => {
        const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)
            || document.activeElement.isContentEditable;
        const slash = e.key === '/' && !e.ctrlKey && !e.metaKey && !typing;
        const cmdk = e.key.toLowerCase() === 'k' && (e.ctrlKey || e.metaKey);
        if (slash || cmdk) {
            // the rail box on desktop, the in-page one on phones: whichever is visible
            const box = [...document.querySelectorAll('[data-global-search]')].find(el => el.offsetParent);
            if (box) { e.preventDefault(); box.focus(); box.select(); }
        }
        if (e.key === 'Escape' && document.activeElement.hasAttribute('data-global-search')) {
            document.activeElement.blur();
        }
    });
});

/* ═══════════ Shared helpers (phase-1 foundation) ═══════════
   Vendored libraries are listed in window.VENDOR (set in base.html from the
   `vendor()` Jinja global, cache-busted); see cockpit/static/vendor/README. */

/* loadScript(url) -> Promise. Loads a script once, however many callers ask. */
function loadScript(url) {
    window._scripts = window._scripts || {};
    if (!window._scripts[url]) {
        window._scripts[url] = new Promise((ok, bad) => {
            const el = document.createElement('script');
            el.src = url; el.onload = ok; el.onerror = bad;
            document.head.appendChild(el);
        });
    }
    return window._scripts[url];
}

/* cssVar('--green') -> the token's current value. */
function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/* chartPalette() -> series colours from the tokens, in a fixed order. */
function chartPalette() {
    return ['--accent', '--green', '--amber', '--blue', '--red'].map(cssVar);
}

/* chartTheme() sets Chart.defaults from the CSS variables, so a chart only has to
   say what is specific to it (data, type, per-axis callbacks). Idempotent. */
function chartTheme() {
    if (!window.Chart) return;
    const d = Chart.defaults;
    d.color = cssVar('--text-muted');
    d.borderColor = cssVar('--border');
    d.font.family = "'Inter', sans-serif";
    d.font.size = 11;
    d.plugins.legend.labels.color = cssVar('--text-secondary');
    d.plugins.title.color = cssVar('--text-primary');
    Object.assign(d.plugins.tooltip, {
        backgroundColor: cssVar('--bg-card'), borderColor: cssVar('--border-accent'), borderWidth: 1,
        titleColor: cssVar('--text-primary'), bodyColor: cssVar('--text-secondary'),
    });
}

/* loadChart() -> Promise<Chart>. Loads vendored Chart.js on first use, themed. */
async function loadChart() {
    if (!window.Chart) await loadScript(window.VENDOR.chart);
    chartTheme();
    return window.Chart;
}

/* makeChart(canvasOrId, config) -> Chart. Destroys any chart already on that
   canvas first (re-draw on tab switch / double init: "Canvas is already in use"),
   applies the theme, returns null if the canvas is missing. Chart.js must be loaded
   (<script src="{{ vendor('chart') }}"> or `await loadChart()`). */
function makeChart(canvasOrId, config) {
    const canvas = typeof canvasOrId === 'string' ? document.getElementById(canvasOrId) : canvasOrId;
    if (!canvas || !window.Chart) return null;
    const old = Chart.getChart(canvas);
    if (old) old.destroy();
    chartTheme();
    return new Chart(canvas, config);
}

/* searchApp(base) — Alpine component for the rail stock search (_nav.html).
   `base` is the origin results open on ('' = this cockpit; ops passes the main one). */
function searchApp(base) {
    return {
        base: base || '', query: '', results: [], showResults: false, searched: false, cur: -1,
        async search() {
            if (this.query.length < 2) { this.results = []; this.showResults = false; this.searched = false; return; }
            const q = this.query;
            try {
                const resp = await fetch('/api/search?q=' + encodeURIComponent(q));
                const rows = resp.ok ? await resp.json() : [];
                if (q !== this.query) return;               // a newer keystroke won
                this.results = rows; this.cur = -1;
            } catch (e) { this.results = []; }
            this.searched = true; this.showResults = true;
        },
        href(stock) { return this.base + '/stocks/' + stock.sid; },
        move(step) {
            if (!this.results.length) return;
            this.cur = (this.cur + step + this.results.length) % this.results.length;
        },
        go() {
            const stock = this.results[this.cur >= 0 ? this.cur : 0];
            if (stock) location.href = this.href(stock);
        },
    };
}

/* Preview mode (preview.py): the server refuses writes with a 403 {"error": "preview is read-only ..."}.
   Wrap fetch once so a button that POSTs shows that message instead of failing silently. */
(function () {
    const nativeFetch = window.fetch;
    let toastTimer = null;
    function toast(text) {
        let el = document.getElementById('toast');
        if (!el) { el = document.createElement('div'); el.id = 'toast'; el.className = 'toast'; el.setAttribute('role', 'status'); document.body.appendChild(el); }
        el.textContent = text; el.classList.add('show');
        clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove('show'), 5000);
    }
    window.toast = toast;
    window.fetch = async function () {
        const resp = await nativeFetch.apply(this, arguments);
        if (resp.status === 403 && document.body && document.body.classList.contains('is-preview')) {
            resp.clone().json().then(j => { if (j && /read-only/.test(j.error || '')) toast(j.error); }).catch(() => {});
        }
        return resp;
    };
    /* The banner's live link follows the open tab (#hash), since the server never sees the hash. */
    function syncLiveLink() {
        const b = document.querySelector('.preview-banner'), a = document.getElementById('preview-live-link');
        if (!b || !a) return;
        let tabs = {}; try { tabs = JSON.parse(b.dataset.tabs || '{}'); } catch (e) {}
        /* "?k=v" keys are toggles kept in the URL query (preview.py COMPARE); they win over the hash */
        const q = Object.keys(tabs).find(k => k[0] === '?' && new URLSearchParams(location.search).get(k.slice(1).split('=')[0]) === k.split('=')[1]);
        a.href = tabs[q] || tabs[location.hash] || a.dataset.default;
    }
    /* tab_bar changes the hash with history.pushState, which fires no event: a light poll catches it. */
    document.addEventListener('DOMContentLoaded', () => { if (document.querySelector('.preview-banner')) { syncLiveLink(); setInterval(syncLiveLink, 500); } });
})();


// Keep every info popover on screen. `.tooltip-popover` is centred on its icon by CSS; near the
// left or right edge (any phone, the right-hand rail on desktop) that pushes it off screen.
// After a popover opens (hover, tap, focus), shift it sideways just enough to sit 8px inside the
// viewport. Fixed-position popovers (`.pop-fixed`) place themselves and are skipped.
(function () {
    function clamp(p) {
        p.style.marginLeft = '';
        const r = p.getBoundingClientRect();
        if (!r.width) return;
        let shift = 0;
        if (r.left < 8) shift = 8 - r.left;
        else if (r.right > window.innerWidth - 8) shift = (window.innerWidth - 8) - r.right;
        if (shift) p.style.marginLeft = shift + 'px';
    }
    function settle(e) {
        const host = e.target && e.target.closest && e.target.closest('.tooltip-wrap, .hover-tip, .tooltip-host');
        if (!host) return;
        // Alpine toggles x-show after this handler; measure on the next frames.
        requestAnimationFrame(() => requestAnimationFrame(() =>
            host.querySelectorAll('.tooltip-popover:not(.pop-fixed)').forEach(clamp)));
    }
    ['mouseover', 'click', 'focusin', 'touchend'].forEach(t => document.addEventListener(t, settle, true));
})();
