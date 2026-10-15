// Multibagger desk (plan 0026): lazy tab bodies, the promote / hold / drop forms and the filters of the Watch tab.

// Fetch a tab's body into `el` (once on first open, again after a change to the book).
function mbLoad(el, key, force) {
    if (!force && el.dataset.state) return;
    el.dataset.state = 'loading';
    el.dataset.mbTab = key;
    fetch('/partial/multibagger/' + key)
        .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.text(); })
        .then(h => { el.innerHTML = h; el.dataset.state = 'done'; mbCounts(el); })
        .catch(e => {
            el.innerHTML = '<div class="pb-empty">Could not load this tab (' + e.message + '). <button type="button" class="pb-clear">Retry</button></div>';
            el.querySelector('button').addEventListener('click', () => { el.removeAttribute('data-state'); mbLoad(el, key); });
            el.removeAttribute('data-state');
        });
}

// A partial carries the list sizes (data-n-book / data-n-held); keep the tab labels in step after a change.
function mbCounts(el) {
    const root = el.querySelector('[data-n-book]');
    if (!root) return;
    document.querySelectorAll('.tab-button').forEach(b => {
        const d = root.dataset;
        if (/^Candidates/.test(b.textContent) && d.nBook && d.maxBook) b.textContent = 'Candidates ' + d.nBook + '/' + d.maxBook;
        if (/^Held/.test(b.textContent) && d.nHeld && d.maxHeld) b.textContent = 'Held ' + d.nHeld + '/' + d.maxHeld;
    });
}

window.addEventListener('mb-book-changed', () => {
    document.querySelectorAll('[data-mb-tab][data-state="done"]').forEach(el => mbLoad(el, el.dataset.mbTab, true));
});

// The inline form behind a Promote / Hold / Drop button (data-action, data-sid on the host). The book's caps and
// rules are enforced by the server (output/mb_book.py); a refusal is shown here as the server words it.
function mbAct() {
    const DONE = { promote: 'Added to candidates.', hold: 'Now held.', drop: 'Dropped.' };
    return {
        open: false, busy: false, err: '', done: '', thesis: '', reason: '', price: '',
        async submit() {
            const d = this.$el.dataset;
            const body = { sid: d.sid, reason: this.reason };
            if (d.action === 'promote') body.thesis_line = this.thesis;
            if (d.action === 'hold') body.entry_price = this.price;
            this.busy = true; this.err = '';
            try {
                const r = await fetch('/api/multibagger/' + d.action, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
                let j = {};
                try { j = await r.json(); } catch (e) { /* not JSON */ }
                if (!r.ok) { this.err = j.error || j.detail || ('The change was refused (HTTP ' + r.status + ').'); return; }
                this.done = DONE[d.action]; this.open = false;
                window.dispatchEvent(new CustomEvent('mb-book-changed'));
            } catch (e) {
                this.err = 'Could not reach the server (' + e.message + ').';
            } finally { this.busy = false; }
        },
    };
}

// Watch tab filters: category and minimum severity, applied to rows carrying data-cat and data-sev (0 low, 1 medium, 2 high).
function mbWatch() {
    return {
        cat: '', sev: '1', shown: 0,
        init() { this.apply(); },
        apply() {
            let n = 0;
            for (const r of this.$root.querySelectorAll('[data-row]')) {
                const ok = (!this.cat || r.dataset.cat === this.cat) && Number(r.dataset.sev) >= Number(this.sev);
                r.hidden = !ok;
                if (ok) n++;
            }
            this.shown = n;
        },
    };
}
