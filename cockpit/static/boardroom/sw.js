// Boardroom service worker (plan 0019): makes the ops cockpit installable as an app and
// gives it an offline screen. It caches only static assets. Pages and /api/ responses are
// never cached: they are your fund's live data and sit behind the login.
const V = 'boardroom-v1';
const SHELL = ['/static/boardroom/offline.html', '/static/boardroom/icon-192.png', '/static/cockpit.css', '/static/cockpit.js'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(V).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== V).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  const r = e.request;
  if (r.method !== 'GET') return;
  const u = new URL(r.url);
  if (u.origin !== location.origin || u.pathname.startsWith('/api/')) return;   // CDN, live data, chat stream
  if (r.mode === 'navigate') {                                                  // a page: network, else the offline screen
    e.respondWith(fetch(r).catch(() => caches.match('/static/boardroom/offline.html')));
    return;
  }
  if (u.pathname.startsWith('/static/')) {                                      // assets: cached copy now, refresh behind
    e.respondWith(caches.open(V).then(c => c.match(r).then(hit => {
      const net = fetch(r).then(res => { if (res.ok) c.put(r, res.clone()); return res; }).catch(() => hit);
      return hit || net;
    })));
  }
});
