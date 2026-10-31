/* Strategy builder for the ops cockpit's options pages (/options/capital, /options/live; plan 0029).
 * OptStrategy.mount(root, opts) renders into the markup of cockpit_ops/templates/_options_builder.html.
 *   opts.get()      → the strategy: {legs: [{cp, K, side (+1 long / −1 short), qty (units), entry, now, iv, label}],
 *                     cost_rs, spot, start, end, now (ISO), r, step, atm_iv, oi: [{K, call, put}], oi_date, underlying}
 *   opts.pctBase()  → ₹ the "Show %" column divides by (capital or margin), or 0
 *   opts.onUpdate(s) → after every redraw, with {S, t, legs: [{pnl, price}], target, expiryAtS, now, maxP, maxL, bes, pop}
 * Pricing is Black-76 on the target index level (sticky strike: each leg keeps its own IV). Nothing is sent anywhere. */
(function () {
  var YEAR = 365 * 86400e3;
  function ncdf(x) {            // Abramowitz–Stegun 7.1.26
    var t = 1 / (1 + 0.3275911 * Math.abs(x) / Math.SQRT2), y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x / 2);
    return x >= 0 ? (1 + y) / 2 : (1 - y) / 2;
  }
  function npdf(x) { return Math.exp(-x * x / 2) / Math.sqrt(2 * Math.PI); }
  function intrinsic(cp, K, S) { return cp === 'C' ? Math.max(S - K, 0) : Math.max(K - S, 0); }
  function b76(cp, F, K, T, s, r) {
    if (!(T > 0) || !(s > 0)) return intrinsic(cp, K, F);
    var v = s * Math.sqrt(T), d1 = (Math.log(F / K) + v * v / 2) / v, d2 = d1 - v, df = Math.exp(-r * T);
    return cp === 'C' ? df * (F * ncdf(d1) - K * ncdf(d2)) : df * (K * ncdf(-d2) - F * ncdf(-d1));
  }
  function greeks(cp, F, K, T, s, r) {
    if (!(T > 0) || !(s > 0)) return {delta: cp === 'C' ? (F > K ? 1 : 0) : (F < K ? -1 : 0), gamma: 0, vega: 0, theta: 0};
    var v = s * Math.sqrt(T), d1 = (Math.log(F / K) + v * v / 2) / v, df = Math.exp(-r * T), dt = Math.min(1 / 365, T);
    return {delta: df * (cp === 'C' ? ncdf(d1) : ncdf(d1) - 1), gamma: df * npdf(d1) / (F * v),
            vega: df * F * npdf(d1) * Math.sqrt(T) / 100, theta: b76(cp, F, K, T - dt, s, r) - b76(cp, F, K, T, s, r)};
  }
  function inr(x) {             // ₹ in K / L / Cr, as formatting.inr_short
    if (x === null || x === undefined || !isFinite(x)) return '—';
    var a = Math.round(Math.abs(x)), s = String(a), u = [[1e7, ' Cr'], [1e5, ' L'], [1e3, ' K']];
    for (var i = 0; i < u.length; i++) if (a >= u[i][0]) { s = parseFloat((a / u[i][0]).toFixed(2)) + u[i][1]; break; }
    return (x < 0 && a ? '−₹' : '₹') + s;
  }
  function signed(x) { return (x > 0.5 ? '+' : '') + inr(x); }
  function num(x, d) { return x.toLocaleString('en-IN', {minimumFractionDigits: d || 0, maximumFractionDigits: d || 0}); }
  function tone(el, x) { el.classList.remove('ob-ok', 'ob-bad'); if (x > 0.5) el.classList.add('ob-ok'); else if (x < -0.5) el.classList.add('ob-bad'); }
  function ist(ms) {
    return new Date(ms).toLocaleString('en-IN', {timeZone: 'Asia/Kolkata', weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false});
  }
  function css(name, fb) { var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim(); return v || fb; }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]; }); }

  // one strategy's numbers: value / P&L at (S, t), the expiry payoff's extremes, breakevens, POP
  function model(st) {
    var t0 = Date.parse(st.start), t1 = Date.parse(st.end), r = st.r || 0, fb = st.atm_iv || 0.15;
    function T(t) { return Math.max(t1 - t, 0) / YEAR; }
    function price(l, S, t) { return b76(l.cp, S, l.K, T(t), l.iv || fb, r); }
    function pnl(S, t) {
      var v = -(st.cost_rs || 0);
      st.legs.forEach(function (l) { v += l.side * l.qty * (price(l, S, t) - l.entry); });
      return v;
    }
    function payoff(S) {
      var v = -(st.cost_rs || 0);
      st.legs.forEach(function (l) { v += l.side * l.qty * (intrinsic(l.cp, l.K, S) - l.entry); });
      return v;
    }
    var Ks = st.legs.map(function (l) { return l.K; }).sort(function (a, b) { return a - b; });
    var pts = [Math.max(1, Ks[0] * 0.3)].concat(Ks, [Ks[Ks.length - 1] * 2]);
    var ys = pts.map(payoff), maxP = Math.max.apply(null, ys), maxL = Math.min.apply(null, ys);
    var up = 0, dn = 0;              // payoff slope above the top strike / below the bottom one
    st.legs.forEach(function (l) { if (l.cp === 'C') up += l.side * l.qty; else dn += l.side * l.qty; });
    var bes = [];
    for (var i = 1; i < pts.length; i++) {
      var a = ys[i - 1], b = ys[i];
      if ((a < 0 && b >= 0) || (a >= 0 && b < 0)) bes.push(pts[i - 1] + (pts[i] - pts[i - 1]) * (0 - a) / (b - a));
    }
    function pop(S, t) {          // lognormal P(payoff at expiry > 0), at the ATM IV
      var tau = T(t), v = fb * Math.sqrt(tau);
      function above(X) { return v > 0 ? ncdf((Math.log(S / X) - v * v / 2) / v) : (S > X ? 1 : 0); }
      var edges = [0].concat(bes, [Infinity]), p = 0;
      for (var k = 1; k < edges.length; k++) {
        var lo = edges[k - 1], hi = edges[k], mid = isFinite(hi) ? (lo + hi) / 2 : lo * 1.5 + 1;
        if (payoff(mid) > 0) p += (lo > 0 ? above(lo) : 1) - (isFinite(hi) ? above(hi) : 0);
      }
      return p;
    }
    return {t0: t0, t1: t1, T: T, price: price, pnl: pnl, payoff: payoff, Ks: Ks, bes: bes, pop: pop,
            maxP: up > 0 ? Infinity : maxP, maxL: (up < 0 || dn < 0) ? -Infinity : maxL, fb: fb, r: r};
  }

  function mount(root, opts) {
    var $ = function (k) { return root.querySelector('[data-o="' + k + '"]'); };
    var st, m, S, t, chart, pane = 'chart';
    var sIn = $('target-in'), sRange = $('target-range'), dRange = $('date-range');
    try { pane = localStorage.getItem('os-pane') || 'chart'; } catch (e) {}

    var guides = {        // vertical lines + OI bars, drawn under the curves
      id: 'osGuides',
      beforeDatasetsDraw: function (c) {
        var ctx = c.ctx, a = c.chartArea, x = c.scales.x, oi = st.oi || [], mx = 0;
        oi.forEach(function (o) { mx = Math.max(mx, o.call, o.put); });
        ctx.save();
        if (mx > 0) {
          var w = Math.max(2, Math.abs(x.getPixelForValue(st.step) - x.getPixelForValue(0)) * 0.42);
          oi.forEach(function (o) {
            var px = x.getPixelForValue(o.K);
            if (px < a.left || px > a.right) return;
            [['put', css('--green', '#22c55e'), -w], ['call', css('--red', '#ef4444'), 0]].forEach(function (s) {
              var h = (o[s[0]] / mx) * (a.bottom - a.top) * 0.36;
              ctx.globalAlpha = 0.16; ctx.fillStyle = s[1];
              ctx.fillRect(px + s[2], a.bottom - h, w, h);
            });
          });
          ctx.globalAlpha = 1;
        }
        var sd = st.spot * m.fb * Math.sqrt(m.T(Date.parse(st.now)));
        ctx.font = '11px Inter, sans-serif'; ctx.textAlign = 'center';
        var gap = Math.abs(x.getPixelForValue(st.spot + sd) - x.getPixelForValue(st.spot));
        [-2, -1, 1, 2].forEach(function (k) {
          var px = x.getPixelForValue(st.spot + k * sd);
          if (!(sd > 0) || gap < 26 || px < a.left || px > a.right) return;   // too close to label (expiry day)
          ctx.strokeStyle = css('--border-accent', '#2a2a3e'); ctx.setLineDash([3, 3]); ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(px, a.top); ctx.lineTo(px, a.bottom); ctx.stroke();
          ctx.fillStyle = css('--text-muted', '#888'); ctx.fillText((k > 0 ? '+' : '') + k + 'SD', px, a.top - 4);
        });
        m.bes.forEach(function (b) {
          var px = x.getPixelForValue(b);
          if (px < a.left || px > a.right) return;
          ctx.strokeStyle = css('--amber', '#f59e0b'); ctx.setLineDash([2, 4]);
          ctx.beginPath(); ctx.moveTo(px, a.top); ctx.lineTo(px, a.bottom); ctx.stroke();
        });
        ctx.setLineDash([]);
        [[st.spot, css('--text-secondary', '#aaa'), 'Index ' + num(st.spot)], [S, css('--blue', '#3b82f6'), Math.abs(S - st.spot) > 0.5 ? 'Target ' + num(S) : null]].forEach(function (v) {
          var px = x.getPixelForValue(v[0]);
          if (px < a.left || px > a.right) return;
          ctx.strokeStyle = v[1]; ctx.lineWidth = 1.5;
          ctx.beginPath(); ctx.moveTo(px, a.top); ctx.lineTo(px, a.bottom); ctx.stroke();
          if (v[2]) { ctx.fillStyle = v[1]; ctx.fillText(v[2], px, a.bottom - 6 - (v[0] === S ? 14 : 0)); }
        });
        ctx.restore();
      }
    };

    function range() {
      var sd = st.spot * m.fb * Math.sqrt(Math.max(m.T(Date.parse(st.now)), 1 / 365));
      var far = Math.max.apply(null, st.legs.map(function (l) { return Math.abs(l.K - st.spot); }));
      var span = Math.max(2.6 * sd, far * 1.35, 4 * st.step);
      return [st.spot - span, st.spot + span];
    }
    function drawChart() {
      var cv = $('chart');
      if (!cv || typeof Chart === 'undefined') return;
      var lr = range(), n = 240, xs = [];
      for (var i = 0; i <= n; i++) xs.push(lr[0] + (lr[1] - lr[0]) * i / n);
      m.Ks.forEach(function (k) { if (k > lr[0] && k < lr[1]) xs.push(k); });
      xs.sort(function (a, b) { return a - b; });
      var exp = xs.map(function (x) { return {x: x, y: m.payoff(x)}; });
      var tgt = xs.map(function (x) { return {x: x, y: m.pnl(x, t)}; });
      var G = css('--green', '#22c55e'), Rd = css('--red', '#ef4444'), B = css('--blue', '#3b82f6');
      var data = {datasets: [
        {label: 'On expiry', data: exp, borderWidth: 2, pointRadius: 0, tension: 0,
         segment: {borderColor: function (c) { return (c.p0.parsed.y + c.p1.parsed.y) / 2 >= 0 ? G : Rd; }},
         borderColor: G, fill: {target: 'origin', above: 'rgba(34,197,94,0.10)', below: 'rgba(239,68,68,0.10)'}},
        {label: 'On target date', data: tgt, borderColor: B, borderWidth: 1.5, pointRadius: 0, tension: 0, fill: false}]};
      if (chart) { chart.data = data; chart.options.scales.x.min = lr[0]; chart.options.scales.x.max = lr[1]; chart.update('none'); return; }
      chart = new Chart(cv, {type: 'line', data: data, plugins: [guides], options: {
        animation: false, maintainAspectRatio: false, parsing: false, normalized: true,
        layout: {padding: {top: 18}},
        interaction: {mode: 'index', intersect: false},
        onClick: function (e) { var v = chart.scales.x.getValueForPixel(e.x); if (v) setS(Math.round(v)); },
        plugins: {legend: {display: false},
          tooltip: {callbacks: {title: function (it) { return st.underlying + ' ' + num(it[0].parsed.x); },
                                label: function (it) { return it.dataset.label + ': ' + signed(it.parsed.y); }}}},
        scales: {x: {type: 'linear', min: lr[0], max: lr[1], grid: {color: css('--border', '#1e1e2e')},
                     ticks: {color: css('--text-muted', '#888'), maxTicksLimit: 8, callback: function (v) { return num(v); }}},
                 y: {grid: {color: function (c) { return c.tick.value === 0 ? css('--text-muted', '#888') : css('--border', '#1e1e2e'); }},
                     ticks: {color: css('--text-muted', '#888'), callback: function (v) { return inr(v); }},
                     title: {display: true, text: 'Profit / loss', color: css('--text-muted', '#888')}}}}});
    }
    function drawTable() {
      var iv = parseFloat($('interval').value) || st.step, pct = $('pct').checked, base = opts.pctBase ? opts.pctBase() : 0;
      var c0 = Math.round(S / iv) * iv, rows = [];
      for (var k = -10; k <= 10; k++) rows.push(c0 + k * iv);
      if (rows.indexOf(S) < 0) rows.push(S);
      rows.sort(function (a, b) { return a - b; });
      function cell(v) { var tx = pct && base ? ((v >= 0 ? '+' : '') + (100 * v / base).toFixed(2) + '%') : signed(v); return '<td class="' + (v > 0.5 ? 'ob-ok' : v < -0.5 ? 'ob-bad' : '') + '">' + tx + '</td>'; }
      $('table').innerHTML = '<tr><th>Target</th><th>On target date: ' + esc(ist(t)) + '</th><th>On expiry</th></tr>' + rows.map(function (x) {
        return '<tr class="' + (x === S ? 'os-cur' : '') + '"><td><a href="#" data-s="' + x + '">' + num(x, x % 1 ? 2 : 0) + '</a></td>' + cell(m.pnl(x, t)) + cell(m.payoff(x)) + '</tr>';
      }).join('');
      $('pct-note').textContent = pct ? (base ? 'of ' + inr(base) + ' ' + (opts.pctLabel || '') : '(no base)') : '';
    }
    function drawGreeks() {
      var mult = $('mult').checked, tot = {delta: 0, theta: 0, gamma: 0, vega: 0}, tau = m.T(t);
      var body = st.legs.map(function (l) {
        var g = greeks(l.cp, S, l.K, tau, l.iv || m.fb, m.r), q = l.side * (mult ? l.qty : 1);
        ['delta', 'theta', 'gamma', 'vega'].forEach(function (k) { tot[k] += g[k] * l.side * l.qty; });
        return '<tr><td>' + esc(l.label) + '</td><td>' + (q * g.delta).toFixed(mult ? 1 : 3) + '</td><td>' + (q * g.theta).toFixed(mult ? 0 : 2) + '</td><td>' + (q * g.gamma).toFixed(mult ? 3 : 5) + '</td><td>' + (q * g.vega).toFixed(mult ? 0 : 2) + '</td><td>' + (l.iv ? (100 * l.iv).toFixed(1) + '%' : '—') + '</td></tr>';
      }).join('');
      $('greeks').innerHTML = '<tr><th>Instrument</th><th>Delta</th><th>Theta / day</th><th>Gamma</th><th>Vega / 1 vol pt</th><th>IV</th></tr>' + body +
        '<tr class="os-total"><td>Total (× quantity)</td><td>' + tot.delta.toFixed(1) + '</td><td>' + inr(tot.theta) + '</td><td>' + tot.gamma.toFixed(3) + '</td><td>' + inr(tot.vega) + '</td><td></td></tr>';
    }
    function drawPnl(legs) {
      var tp = 0, tn = 0, haveNow = true;
      var body = st.legs.map(function (l, i) {
        var nowP = l.now === null || l.now === undefined ? null : l.side * l.qty * (l.now - l.entry);
        if (nowP === null) haveNow = false; else tn += nowP;
        tp += legs[i].pnl;
        return '<tr><td>' + esc(l.label) + '</td><td class="' + (legs[i].pnl > 0 ? 'ob-ok' : 'ob-bad') + '">' + signed(legs[i].pnl) + '</td><td>' + legs[i].price.toFixed(2) + '</td><td>' + l.entry.toFixed(2) + '</td><td>' + (l.now === null || l.now === undefined ? '—' : l.now.toFixed(2)) + '</td><td>' + (nowP === null ? '—' : signed(nowP)) + '</td></tr>';
      }).join('');
      var c = st.cost_rs || 0;
      $('pnl').innerHTML = '<tr><th>Instrument</th><th>Target P&amp;L</th><th>Target price</th><th>Entry price</th><th>Last price</th><th>Last P&amp;L</th></tr>' + body +
        '<tr><td class="ob-muted">Charges (entry)</td><td>' + inr(-c) + '</td><td></td><td></td><td></td><td>' + inr(-c) + '</td></tr>' +
        '<tr class="os-total"><td>Total</td><td class="' + (tp - c > 0 ? 'ob-ok' : 'ob-bad') + '">' + signed(tp - c) + '</td><td></td><td></td><td></td><td>' + (haveNow ? signed(tn - c) : '—') + '</td></tr>';
    }
    function setS(v) { S = Math.max(1, v); redraw(); }
    function redraw() {
      sIn.value = Math.round(S * 100) / 100;
      sRange.value = S;
      $('target-pct').textContent = ((S / st.spot - 1) * 100).toFixed(2) + '%';
      dRange.value = t;
      $('date-label').value = ist(t);
      $('und').textContent = st.underlying;
      var left = m.t1 - t, d = Math.floor(left / 86400e3), h = Math.floor((left % 86400e3) / 3600e3), mi = Math.round((left % 3600e3) / 60e3);
      $('dte').textContent = left <= 0 ? 'at expiry' : (d ? d + 'd ' + h + 'h' : (h ? h + 'h ' : '') + mi + 'm') + ' to expiry';
      var legs = st.legs.map(function (l) { var p = m.price(l, S, t); return {price: p, pnl: l.side * l.qty * (p - l.entry)}; });
      var target = m.pnl(S, t), haveNow = st.legs.every(function (l) { return l.now !== null && l.now !== undefined; });
      var now = haveNow ? st.legs.reduce(function (a, l) { return a + l.side * l.qty * (l.now - l.entry); }, -(st.cost_rs || 0)) : null;
      var s = {S: S, t: t, legs: legs, target: target, expiryAtS: m.payoff(S), now: now, maxP: m.maxP, maxL: m.maxL,
               bes: m.bes, pop: m.pop(S, t)};
      $('maxp').textContent = isFinite(m.maxP) ? signed(m.maxP) : 'Unlimited';
      $('maxl').textContent = isFinite(m.maxL) ? inr(m.maxL) : 'Unlimited';
      $('left').textContent = now === null || !isFinite(m.maxP) ? '—' : signed(m.maxP - now);
      $('bes').textContent = m.bes.length ? m.bes.map(function (b) { return num(b) + ' (' + ((b / st.spot - 1) * 100 >= 0 ? '+' : '') + ((b / st.spot - 1) * 100).toFixed(1) + '%)'; }).join(', ') : 'none';
      $('pop').textContent = (100 * s.pop).toFixed(0) + '%';
      $('projected').textContent = signed(target);
      tone($('projected'), target);
      $('projected-at').textContent = num(S) + ' · ' + ist(t);
      $('oi-legend').textContent = st.oi && st.oi.length ? 'OI ' + (st.oi_date || '') + ': call ' + num(st.oi.reduce(function (a, o) { return a + o.call; }, 0)) + ' · put ' + num(st.oi.reduce(function (a, o) { return a + o.put; }, 0)) : 'no OI';
      if (pane === 'chart') drawChart();
      if (pane === 'table') drawTable();
      if (pane === 'greeks') drawGreeks();
      if (pane === 'pnl') drawPnl(legs);
      if (opts.onUpdate) opts.onUpdate(s);
    }
    function showPane(p) {
      pane = p;
      Array.prototype.forEach.call(root.querySelectorAll('[data-pane]'), function (el) { el.hidden = el.dataset.pane !== p; });
      Array.prototype.forEach.call(root.querySelectorAll('[data-tab]'), function (b) { b.classList.toggle('ob-tab-on', b.dataset.tab === p); b.setAttribute('aria-selected', b.dataset.tab === p ? 'true' : 'false'); });
      try { localStorage.setItem('os-pane', p); } catch (e) {}
      redraw();
    }
    function load(keep) {
      st = opts.get();
      m = model(st);
      var nowMs = Math.min(Math.max(Date.parse(st.now), m.t0), m.t1);
      if (!keep || !(S > 0)) { S = Math.round(st.spot * 100) / 100; t = nowMs; }
      t = Math.min(Math.max(t, m.t0), m.t1);
      sRange.min = Math.round(st.spot * 0.9); sRange.max = Math.round(st.spot * 1.1); sRange.step = 1;
      sIn.step = st.step;
      dRange.min = m.t0; dRange.max = m.t1; dRange.step = 15 * 60e3;
      var iv = $('interval'), base = st.step, cur = parseFloat(iv.value);
      iv.innerHTML = [base / 2, base, base * 2.5, base * 5].map(function (v) { return '<option value="' + v + '"' + ((cur || base) === v ? ' selected' : '') + '>' + v + '</option>'; }).join('');
      root._resetS = function () { setS(Math.round(st.spot * 100) / 100); };
      root._resetT = function () { t = nowMs; redraw(); };
      redraw();
    }

    Array.prototype.forEach.call(root.querySelectorAll('[data-tab]'), function (b) { b.addEventListener('click', function () { showPane(b.dataset.tab); }); });
    sRange.addEventListener('input', function () { setS(parseFloat(sRange.value)); });
    sIn.addEventListener('change', function () { var v = parseFloat(sIn.value); if (v > 0) setS(v); });
    $('minus').addEventListener('click', function () { setS(Math.round((S - st.step) / st.step) * st.step); });
    $('plus').addEventListener('click', function () { setS(Math.round((S + st.step) / st.step) * st.step); });
    dRange.addEventListener('input', function () { t = parseFloat(dRange.value); redraw(); });
    $('prev').addEventListener('click', function () { t = Math.max(m.t0, t - 86400e3); redraw(); });
    $('next').addEventListener('click', function () { t = Math.min(m.t1, t + 86400e3); redraw(); });
    $('reset-s').addEventListener('click', function (e) { e.preventDefault(); root._resetS(); });
    $('reset-t').addEventListener('click', function (e) { e.preventDefault(); root._resetT(); });
    ['interval', 'pct', 'mult'].forEach(function (k) { $(k).addEventListener('change', redraw); });
    $('table').addEventListener('click', function (e) { var a = e.target.closest('a[data-s]'); if (a) { e.preventDefault(); setS(parseFloat(a.dataset.s)); } });
    load(false);
    showPane(['chart', 'table', 'greeks', 'pnl'].indexOf(pane) >= 0 ? pane : 'chart');
    return {refresh: function (keep) { load(keep); }};
  }

  window.OptStrategy = {mount: mount, inr: inr, signed: signed, num: num, tone: tone, ist: ist};
})();
