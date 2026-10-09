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
        href(stock) { return this.base + '/explorer/' + stock.sid; },
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
