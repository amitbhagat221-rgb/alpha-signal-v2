/* Ask: the assistant panel on every page of both cockpits (base.html; server: ask.py,
   cockpit/_shared.add_ask_routes).

   Open it with the ✦ Ask button, the `a` key, or the "Ask about this" pill that appears when
   text on the page is selected. Each question is sent with the page it was asked on: the
   address, the title, the visible text of <main> and the selected text. The reply streams in
   (server-sent events) and renders as Markdown, with ```chart and ```mermaid blocks drawn as
   figures (same spec as the Boardroom chat).

   The conversation is stored server-side, so it follows you from page to page; a reply still
   being written when you leave a page is saved and shows up on the next one. Plain JS, no
   Alpine: the panel lives outside every page's components. Uses loadScript / loadChart /
   makeChart / chartPalette / cssVar from cockpit.js. */
(function () {
    'use strict';
    const store = {
        get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
        set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private window */ } },
    };
    const S = {
        open: false, loaded: false, conv: null, fresh: false, messages: [], busy: false, pending: false,
        model: store.get('ask.model') || 'sonnet', models: { sonnet: 'Fast', opus: 'Deep' },
        selection: '', status: '', note: '', poll: null,
    };
    const $ = (sel, root) => (root || document).querySelector(sel);
    const esc = (t) => String(t == null ? '' : t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    const wide = () => window.matchMedia('(min-width: 1100px)').matches;

    // ── the DOM ────────────────────────────────────────────────────────────────────
    const fab = document.createElement('button');
    fab.id = 'ask-fab'; fab.type = 'button'; fab.title = 'Ask about this page (a)';
    fab.innerHTML = '<span class="ask-spark" aria-hidden="true">✦</span><span>Ask</span>';

    const pill = document.createElement('button');
    pill.id = 'ask-pill'; pill.type = 'button'; pill.hidden = true;
    pill.innerHTML = '<span aria-hidden="true">✦</span> Ask about this';

    const panel = document.createElement('aside');
    panel.id = 'ask-panel'; panel.hidden = true; panel.setAttribute('aria-label', 'Ask the assistant');
    panel.innerHTML = `
      <header class="ask-head">
        <div class="ask-title"><span class="ask-spark" aria-hidden="true">✦</span> Ask
          <span class="ask-about" title="Questions are sent with this page"></span></div>
        <div class="ask-ctrls">
          <div class="ask-seg" role="group" aria-label="Model"></div>
          <button type="button" class="ask-btn" data-act="history" title="Earlier conversations">History</button>
          <button type="button" class="ask-btn" data-act="new" title="Start a new conversation">New</button>
          <button type="button" class="ask-btn ask-x" data-act="close" title="Close (Esc)" aria-label="Close">×</button>
        </div>
      </header>
      <div class="ask-hist" hidden></div>
      <div class="ask-msgs" aria-live="polite"></div>
      <footer class="ask-foot">
        <div class="ask-sel" hidden><span class="ask-sel-t"></span><button type="button" data-act="unsel" aria-label="Remove the selection">×</button></div>
        <div class="ask-row">
          <textarea rows="1" placeholder="Ask about this page…" aria-label="Your question"></textarea>
          <button type="button" class="ask-send" data-act="send" aria-label="Send">↑</button>
        </div>
        <div class="ask-hint">Reads this page · the database · the code · the web. Read-only. <kbd>Enter</kbd> sends, <kbd>Shift</kbd>+<kbd>Enter</kbd> new line.</div>
      </footer>`;
    document.body.append(fab, pill, panel);
    const box = $('textarea', panel), msgs = $('.ask-msgs', panel), hist = $('.ask-hist', panel);

    // ── the page the question is about ─────────────────────────────────────────────
    function pageCtx() {
        const main = document.getElementById('main');
        return {
            url: location.pathname + location.search + location.hash,
            title: document.title.replace(/\s*·\s*Alpha Signal.*$/, ''),
            text: main ? main.innerText.slice(0, 20000) : '',
            selection: S.selection,
        };
    }

    // ── rendering ─────────────────────────────────────────────────────────────────
    let libs = null;
    function loadLibs() {
        libs = libs || Promise.all([loadScript(window.VENDOR.marked), loadScript(window.VENDOR.purify)]).catch(() => null);
        return libs;
    }
    function toHtml(m, final) {
        m.figs = [];
        let text = (m.text || '').replace(/```(chart|mermaid)[^\n]*\n([\s\S]*?)```/g, (all, kind, body) => {
            m.figs.push({ kind: kind, body: body });
            return '\n\n<div class="ask-fig" data-i="' + (m.figs.length - 1) + '"><span class="ask-wait">' +
                   (kind === 'chart' ? 'chart' : 'diagram') + '…</span></div>\n\n';
        });
        if (!final) text = text.replace(/```(chart|mermaid)[\s\S]*$/, '\n\n*drawing…*');
        if (window.marked && window.DOMPurify) {
            return DOMPurify.sanitize(marked.parse(text, { breaks: true, gfm: true }));
        }
        return '<p style="white-space: pre-wrap;">' + esc(text) + '</p>';
    }
    function when(at) {
        if (!at) return '';
        const d = new Date(at.endsWith('Z') ? at : at + 'Z');
        return isNaN(d) ? '' : d.toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
    }
    function msgNode(m, i) {
        const el = document.createElement('div');
        el.className = 'ask-m ' + (m.who === 'you' ? 'ask-you' : 'ask-ai');
        el.dataset.i = i;
        if (m.who === 'you') {
            const where = m.page && m.page.url
                ? '<a class="ask-on" href="' + esc(m.page.url) + '">on ' + esc(m.page.title || m.page.url) + '</a>' : '';
            el.innerHTML = '<div class="ask-bub">' + esc(m.text).replace(/\n/g, '<br>') + '</div>' + where;
        } else {
            const tools = (m.tools || []).length
                ? '<div class="ask-tools" title="' + esc(m.tools.join(', ')) + '">Looked up: ' +
                  esc([...new Set(m.tools)].slice(0, 6).join(', ')) + (new Set(m.tools).size > 6 ? '…' : '') + '</div>' : '';
            el.innerHTML = tools + (m.text ? '<div class="ask-bub ask-md">' + toHtml(m, m.final !== false) + '</div>' : '') +
                (m.final !== false && m.text ? '<div class="ask-meta">' + esc(when(m.at)) +
                 ' <button type="button" class="ask-link" data-act="copy">Copy</button></div>' : '');
        }
        return el;
    }
    function scroll() { msgs.scrollTop = msgs.scrollHeight; }
    function statusNode() {          // "working" line: shown for as long as a turn runs, with the latest note
        const st = document.createElement('div');
        st.className = 'ask-status';
        st.innerHTML = '<span class="ask-dots"><i></i><i></i><i></i></span><span class="ask-st"></span>';
        $('.ask-st', st).textContent = S.status;
        if (S.note) {
            const n = document.createElement('div');
            n.className = 'ask-note'; n.textContent = S.note.length > 220 ? S.note.slice(0, 220) + '…' : S.note;
            st.appendChild(n);
        }
        return st;
    }
    function render() {
        msgs.innerHTML = '';
        if (!S.messages.length && !S.pending) {
            msgs.appendChild(empty());
        }
        S.messages.forEach((m, i) => msgs.appendChild(msgNode(m, i)));
        if (S.status) msgs.appendChild(statusNode());
        draw(); scroll();
    }
    function empty() {
        const el = document.createElement('div');
        el.className = 'ask-empty';
        const stock = /^\/(stocks|multibagger\/stock)\/[^/]+/.test(location.pathname);
        const starters = S.selection
            ? ['Explain the selected text in plain words', 'Is the selected number right? Check it against the database', 'How is this computed?']
            : stock
            ? ['What is the capex situation in this business?', 'How healthy is the balance sheet and cash flow?',
               'What did management guide on the last earnings call?', 'Why does the model rank it where it does?']
            : ['Explain this page in plain words', 'What should I look at first on this page?',
               'Is anything here stale, odd or contradictory?', 'How is this page computed? Walk me through the code path'];
        el.innerHTML = '<div class="ask-empty-h">Ask anything about this page</div>' +
            '<div class="ask-empty-s">I can see what is on the page, query the database, read the code and docs, and search the web.</div>' +
            starters.map(s => '<button type="button" class="ask-chip" data-q="' + esc(s) + '">' + esc(s) + '</button>').join('');
        return el;
    }
    function draw() {
        msgs.querySelectorAll('.ask-fig:not([data-done])').forEach(node => {
            const line = node.closest('[data-i]'); if (!line) return;
            const m = S.messages[+line.dataset.i]; if (!m || m.final === false) return;
            const fig = (m.figs || [])[+node.dataset.i]; if (!fig) return;
            node.dataset.done = '1';
            (fig.kind === 'chart' ? drawChart(node, fig.body) : drawDiagram(node, fig.body)).catch(() => {
                const pre = document.createElement('pre'); pre.textContent = fig.body;      // could not draw: show the source
                node.innerHTML = ''; node.appendChild(pre);
            });
        });
        msgs.querySelectorAll('.ask-md a[href^="http"]').forEach(a => { a.target = '_blank'; a.rel = 'noopener'; });
    }
    async function drawChart(node, body) {
        const spec = JSON.parse(body);
        const type = ['bar', 'line', 'pie', 'doughnut', 'scatter'].includes(spec.type) ? spec.type : 'bar';
        await loadChart();
        const pal = chartPalette(), round = type === 'pie' || type === 'doughnut';
        const sets = (spec.datasets || []).slice(0, pal.length).map((d, i) => ({
            label: String(d.label || ''), data: (d.data || []).slice(0, 400),
            backgroundColor: round ? pal : pal[i % pal.length] + (type === 'line' ? '33' : 'cc'),
            borderColor: round ? cssVar('--bg-card') : pal[i % pal.length], borderWidth: type === 'line' ? 2 : 1,
            tension: 0.25, pointRadius: type === 'scatter' ? 3 : 1.5, fill: false,
        }));
        const muted = cssVar('--text-muted'), grid = cssVar('--border');
        const axis = t => ({ title: { display: !!t, text: t || '', color: muted }, ticks: { color: muted }, grid: { color: grid } });
        node.innerHTML = '<canvas></canvas>' + (spec.source ? '<div class="ask-src"></div>' : '');
        if (spec.source) $('.ask-src', node).textContent = 'Source: ' + spec.source;
        makeChart($('canvas', node), {
            type: type, data: { labels: (spec.labels || []).slice(0, 400).map(String), datasets: sets },
            options: {
                responsive: true, maintainAspectRatio: true, aspectRatio: round ? 1.4 : 1.5, indexAxis: spec.horizontal ? 'y' : 'x',
                plugins: { title: { display: !!spec.title, text: String(spec.title || ''), color: cssVar('--text-primary') },
                           legend: { display: round || sets.length > 1, labels: { color: muted } } },
                scales: round ? {} : { x: { ...axis(spec.x_label), stacked: !!spec.stacked }, y: { ...axis(spec.y_label), stacked: !!spec.stacked } },
            },
        });
    }
    async function drawDiagram(node, body) {
        await loadScript(window.VENDOR.mermaid);      // 3.3 MB: only when a diagram is drawn
        if (!window._askMermaid) { mermaid.initialize({ startOnLoad: false, theme: 'dark', securityLevel: 'strict' }); window._askMermaid = 1; }
        node.innerHTML = (await mermaid.render('askm' + Math.random().toString(36).slice(2), body)).svg;
    }

    // ── header bits ───────────────────────────────────────────────────────────────
    function head() {
        $('.ask-about', panel).textContent = 'about: ' + pageCtx().title;
        $('.ask-seg', panel).innerHTML = Object.entries(S.models).map(([k, v]) =>
            '<button type="button" data-model="' + esc(k) + '" class="' + (k === S.model ? 'on' : '') + '" title="' +
            (k === 'opus' ? 'Deeper and slower: for research questions' : 'Quicker: for most questions') + '">' + esc(v) + '</button>').join('');
        const sel = $('.ask-sel', panel);
        sel.hidden = !S.selection;
        $('.ask-sel-t', panel).textContent = S.selection ? '“' + S.selection.slice(0, 160) + (S.selection.length > 160 ? '…' : '') + '”' : '';
        box.placeholder = S.selection ? 'Ask about the selected text…' : 'Ask about this page…';
    }

    // ── server ────────────────────────────────────────────────────────────────────
    async function load(conv) {
        try {
            const r = await fetch('/api/ask' + (conv ? '?conv=' + encodeURIComponent(conv) : ''));
            if (!r.ok) throw new Error('HTTP ' + r.status);
            const j = await r.json();
            await loadLibs();
            S.conv = j.conv; S.fresh = false; S.messages = j.messages || []; S.models = j.models || S.models;
            if (!S.models[S.model]) S.model = Object.keys(S.models)[0];
            S.pending = !!j.pending;
            S.status = S.pending ? 'Still answering your last question…' : '';
            S.loaded = true;
            head(); render();
            clearTimeout(S.poll);
            if (S.pending && !S.busy) S.poll = setTimeout(() => S.open && load(S.conv), 3000);
        } catch (e) {
            S.status = ''; msgs.innerHTML = '<div class="ask-err">Could not load the conversation (' + esc(e.message) + ').</div>';
        }
    }
    async function send(text) {
        text = (text || '').trim();
        if (!text || S.busy || S.pending) return;
        await loadLibs();
        const page = pageCtx();
        S.messages.push({ who: 'you', text: text, page: { url: page.url, title: page.title } });
        S.busy = true; S.status = 'Reading the page…';
        box.value = ''; grow(); render();
        let reply = null, last = 0;
        const ensure = () => {
            if (!reply) { reply = { who: 'assistant', text: '', tools: [], final: false }; S.messages.push(reply); }
            return reply;
        };
        const paint = (force) => {                // re-render only the reply bubble while it streams
            if (!force && Date.now() - last < 120) return;
            last = Date.now();
            const i = S.messages.indexOf(reply), old = msgs.querySelector('[data-i="' + i + '"]');
            if (old) old.replaceWith(msgNode(reply, i)); else render();
            const st = $('.ask-status', msgs);
            if (st) st.remove();
            if (S.status) msgs.appendChild(statusNode());
            if (msgs.scrollHeight - msgs.scrollTop - msgs.clientHeight < 160) scroll();
        };
        try {
            const r = await fetch('/api/ask', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: text, page: page, conv: S.fresh ? null : S.conv, new: S.fresh, model: S.model }),
            });
            if (!r.ok || !r.body) {
                let err = 'HTTP ' + r.status;
                try { err = (await r.json()).error || err; } catch (e) { /* not JSON */ }
                throw new Error(err);
            }
            S.fresh = false; S.selection = ''; head();
            S.status = 'Thinking…'; render();
            const reader = r.body.getReader(), dec = new TextDecoder();
            let buf = '';
            for (;;) {
                const { done, value } = await reader.read();
                if (done) break;
                buf += dec.decode(value, { stream: true });
                let cut;
                while ((cut = buf.indexOf('\n\n')) >= 0) {
                    const line = buf.slice(0, cut); buf = buf.slice(cut + 2);
                    if (!line.startsWith('data: ')) continue;
                    const ev = JSON.parse(line.slice(6));
                    if (ev.t === 'start') { S.conv = ev.conv; }
                    else if (ev.t === 'delta') {
                        const m = ensure(); m.text += ev.text;
                        S.status = m.text.trim() ? 'Writing…' : S.status; paint();
                    } else if (ev.t === 'tool') {      // what was written before a lookup was a note, not the answer
                        const m = ensure();
                        if (m.text.trim()) S.note = m.text.trim();
                        m.text = ''; m.tools.push(ev.name);
                        S.status = 'Looking up ' + ev.name + '…'; paint(true);
                    }
                    else if (ev.t === 'error') { const m = ensure(); m.text = m.text || ('*(no reply: ' + ev.error + ')*'); }
                }
            }
        } catch (e) {
            const m = ensure(); m.text = m.text || ('*(no reply: ' + e.message + ')*');
        }
        if (reply) { reply.final = true; reply.at = new Date().toISOString(); }
        S.busy = false; S.status = ''; S.note = '';
        render();
    }

    // ── open / close ──────────────────────────────────────────────────────────────
    function open(withSelection) {
        if (withSelection) S.selection = withSelection;
        S.open = true; panel.hidden = false; fab.hidden = true; pill.hidden = true;
        document.body.classList.add('ask-open');
        store.set('ask.open', '1');
        head();
        if (!S.loaded) { msgs.innerHTML = '<div class="ask-status">Loading…</div>'; load(); } else render();
        setTimeout(() => box.focus(), 30);
    }
    function close() {
        S.open = false; panel.hidden = true; fab.hidden = false; hist.hidden = true;
        document.body.classList.remove('ask-open');
        store.set('ask.open', '0');
        clearTimeout(S.poll);
    }
    async function showHistory() {
        if (!hist.hidden) { hist.hidden = true; return; }
        hist.hidden = false; hist.innerHTML = '<div class="ask-status">Loading…</div>';
        try {
            const r = await fetch('/api/ask/conversations'), list = r.ok ? await r.json() : [];
            hist.innerHTML = list.length ? list.map(c =>
                '<button type="button" class="ask-hrow' + (c.conv === S.conv ? ' on' : '') + '" data-conv="' + esc(c.conv) + '">' +
                '<span class="ask-hq">' + esc(c.first || '(no question)') + '</span>' +
                '<span class="ask-hm">' + esc(when(c.last_at)) + ' · ' + c.n + ' messages' +
                (c.page && c.page.title ? ' · on ' + esc(c.page.title) : '') + '</span></button>').join('')
                : '<div class="ask-status">No conversations yet.</div>';
        } catch (e) { hist.innerHTML = '<div class="ask-err">Could not load the history.</div>'; }
    }
    function grow() { box.style.height = 'auto'; box.style.height = Math.min(box.scrollHeight, 180) + 'px'; }

    // ── events ────────────────────────────────────────────────────────────────────
    fab.addEventListener('click', () => open());
    pill.addEventListener('mousedown', (e) => e.preventDefault());          // keep the selection alive
    pill.addEventListener('click', () => { const t = String(window.getSelection() || '').trim(); open(t.slice(0, 4000)); });
    panel.addEventListener('click', (e) => {
        const b = e.target.closest('button'); if (!b) return;
        const act = b.dataset.act;
        if (b.dataset.q) send(b.dataset.q);
        else if (b.dataset.model) { S.model = b.dataset.model; store.set('ask.model', S.model); head(); }
        else if (b.dataset.conv) { hist.hidden = true; load(b.dataset.conv); }
        else if (act === 'close') close();
        else if (act === 'new') { S.fresh = true; S.conv = null; S.messages = []; S.pending = false; S.status = ''; hist.hidden = true; clearTimeout(S.poll); render(); box.focus(); }
        else if (act === 'history') showHistory();
        else if (act === 'send') send(box.value);
        else if (act === 'unsel') { S.selection = ''; head(); if (!S.messages.length) render(); }
        else if (act === 'copy') {
            const m = S.messages[+b.closest('[data-i]').dataset.i];
            if (m && navigator.clipboard) navigator.clipboard.writeText(m.text).then(() => { b.textContent = 'Copied'; });
        }
    });
    box.addEventListener('input', grow);
    box.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(box.value); }
    });
    document.addEventListener('keydown', (e) => {
        const t = e.target, typing = t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
        if (e.key === 'Escape' && S.open && (!typing || t === box)) { close(); return; }
        if (e.key === 'a' && !typing && !e.ctrlKey && !e.metaKey && !e.altKey && !S.open) {
            e.preventDefault();
            const sel = String(window.getSelection() || '').trim();
            open(sel.length >= 3 ? sel.slice(0, 4000) : '');
        }
    });
    // the "Ask about this" pill: next to text selected inside the page
    function placePill() {
        const sel = window.getSelection(), t = String(sel || '').trim(), main = document.getElementById('main');
        if (!t || t.length < 3 || !sel.rangeCount || !main || !main.contains(sel.anchorNode) || panel.contains(sel.anchorNode)) {
            pill.hidden = true; return;
        }
        const r = sel.getRangeAt(0).getBoundingClientRect();
        if (!r.width && !r.height) { pill.hidden = true; return; }
        pill.hidden = false;
        const top = Math.min(window.innerHeight - 44, r.bottom + 8), left = Math.max(8, Math.min(window.innerWidth - pill.offsetWidth - 8, r.right - pill.offsetWidth));
        pill.style.top = top + 'px'; pill.style.left = left + 'px';
    }
    document.addEventListener('mouseup', () => setTimeout(placePill, 10));
    document.addEventListener('touchend', () => setTimeout(placePill, 250));
    document.addEventListener('scroll', () => { pill.hidden = true; }, { passive: true, capture: true });
    document.addEventListener('selectionchange', () => { if (!String(window.getSelection() || '').trim()) pill.hidden = true; });
    window.addEventListener('hashchange', () => { if (S.open) head(); });

    // reopen on the next page if it was open (desktop only: on a phone it would cover the page)
    if (store.get('ask.open') === '1' && wide()) open();
})();
