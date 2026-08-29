const CACHE = 'holomint-v1.43';        // app shell, replaced on every release
const MEDIA = 'holomint-media';      // card images / cross-origin - persists across releases
const SHELL = ['./', './index.html', './cardfind.js', './manifest.json', './icon-192.png', './icon-512.png', './leaf-splash.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  // Drop old shell caches, but keep the current shell and the persistent media cache.
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE && k !== MEDIA).map(k => caches.delete(k)))
  ).then(async () => {
    // Evict any /api/ responses an older Service Worker cached. Existing installs are
    // carrying a stale pricing and licence answer in the persistent media cache, and the
    // fetch handler's offline fallback would keep serving it. This is what un-sticks a
    // phone that has been told "Subscriptions are not open yet" since before Polar was
    // wired. Runs once per release and is cheap.
    for (const name of [MEDIA, CACHE]) {
      try {
        const c = await caches.open(name);
        const reqs = await c.keys();
        await Promise.all(reqs
          .filter(r => { try { return new URL(r.url).pathname.startsWith('/api/'); } catch (e) { return false; } })
          .map(r => c.delete(r)));
      } catch (e) {}
    }
  }).then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  const url = new URL(e.request.url);

  // The API is LIVE DATA and must never be served cache-first. It lives on
  // api.holomint.app, a different origin from the app, so it used to fall into the
  // cross-origin card-image rule below: cache-first, into a cache that deliberately
  // survives version bumps. The effect was that the FIRST response an install ever saw
  // was replayed forever. A `configured:false` captured while Polar was still being
  // wired kept hiding the Pro purchase link release after release, and no client change
  // could fix it because the Service Worker answers before fetch() ever reaches the
  // network, `cache: no-store` included.
  //
  // Network only, with cache purely as an offline fallback, and nothing new written.
  // The app keeps its own copies of what matters (drops in localStorage, licence state
  // in Premium), so it does not need the Service Worker to hold anything here.
  if (url.pathname.startsWith('/api/')) {
    e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
    return;
  }

  // The perceptual-hash DB (hashes.json) is large and changes rarely. Serve it
  // cache-first from the persistent media cache (survives version bumps, no 5MB
  // re-download each release) and refresh in the background when online.
  if (url.pathname.endsWith('hashes.json') && url.origin === location.origin) {
    e.respondWith(
      caches.match(e.request).then(hit => {
        const net = fetch(e.request).then(res => {
          const copy = res.clone();
          caches.open(MEDIA).then(c => c.put(e.request, copy)).catch(()=>{});
          return res;
        }).catch(() => hit);
        return hit || net;
      })
    );
    return;
  }

  // products.json is ~2.2MB (435KB gzipped) and the product LIST changes a few times
  // a year, not daily.
  // Network-first meant re-downloading it on every cold open, which is brutal on show
  // wifi or mobile data and is the slowest moment in the whole app. Serve it cache-first
  // from the persistent media cache (survives version bumps) and refresh in the
  // background, so the second open is instant and still ends up current.
  if (url.pathname.endsWith('products.json') && url.origin === location.origin) {
    e.respondWith(
      caches.match(e.request).then(hit => {
        const net = fetch(e.request).then(res => {
          const copy = res.clone();
          caches.open(MEDIA).then(c => c.put(e.request, copy)).catch(()=>{});
          return res;
        }).catch(() => hit);
        return hit || net;
      })
    );
    return;
  }

  // Other same-origin data files (prices.json, history.json): network-first so daily
  // price updates land; fall back to cache when offline at a show.
  if (url.pathname.endsWith('.json') && url.origin === location.origin) {
    e.respondWith(
      fetch(e.request).then(res => {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, copy)).catch(()=>{});
        return res;
      }).catch(() => caches.match(e.request))
    );
    return;
  }

  // Cross-origin (card images, external metadata API): cache-first into a persistent
  // media cache. This survives version bumps, so pushing a new release no longer wipes
  // cached images and force-redownloads them as you browse. Browser handles eviction
  // under storage pressure.
  if (url.origin !== location.origin) {
    e.respondWith(
      caches.match(e.request).then(hit => hit || fetch(e.request).then(res => {
        const copy = res.clone();
        caches.open(MEDIA).then(c => c.put(e.request, copy)).catch(()=>{});
        return res;
      }).catch(() => hit))
    );
    return;
  }

  // Same-origin app shell: cache-first for instant offline loads (refreshed each release).
  e.respondWith(
    caches.match(e.request).then(hit => hit || fetch(e.request).then(res => {
      const copy = res.clone();
      caches.open(CACHE).then(c => c.put(e.request, copy)).catch(()=>{});
      return res;
    }).catch(() => hit))
  );
});

/* ---------------------------------------------------------------------------
   Drop alerts (Web Push).
   This is why the service worker matters: these two handlers fire even when the
   app is completely closed. The Worker sends an encrypted payload, the browser
   wakes this SW, and we surface a notification.
   Note: Chrome requires userVisibleOnly, so every push MUST show something.
--------------------------------------------------------------------------- */

const FEED_API = 'https://holomint-feed.mmilliard2516.workers.dev';

self.addEventListener('push', e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) {}

  const title = d.title || 'Holomint';
  const opts = {
    body: d.body || 'A tracked drop just landed.',
    icon: './icon-192.png',
    badge: './icon-192.png',
    tag: d.tag || 'holomint-drop',   // collapses repeats for the same product
    renotify: true,
    timestamp: d.ts || Date.now(),
    data: { url: d.url || './', pid: d.pid || null, pname: d.pname || null },
    actions: (d.act === 'watch' && d.pid)
      ? [{ action: 'open', title: 'Open' }, { action: 'watch', title: 'Watch this' }]
      : [{ action: 'open', title: 'Open listing' }]
  };
  e.waitUntil(self.registration.showNotification(title, opts));
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  const D = e.notification.data || {};

  // "Watch this" from an invite or staged-page alert: add it server-side without ever
  // opening the app. iOS ignores notification actions entirely, so this is progressive
  // enhancement; the in-app watchlist is the iOS path.
  if (e.action === 'watch' && D.pid) {
    e.waitUntil((async () => {
      let ok = false;
      try {
        const sub = await self.registration.pushManager.getSubscription();
        if (sub) {
          const r = await fetch(FEED_API + '/api/watch-add', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ endpoint: sub.endpoint, id: D.pid, name: D.pname || '' }),
          });
          ok = r.ok;
        }
      } catch (err) {}
      await self.registration.showNotification(
        ok ? 'Added to watchlist' : 'Could not add it',
        { body: ok ? (D.pname || '') + ' will alert you the second it goes buyable, whatever the margin.'
                   : 'Open Holomint and add it from the alerts settings.',
          icon: './icon-192.png', badge: './icon-192.png', tag: 'watch-ok' });
    })());
    return;
  }

  const target = D.url || './';
  e.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
      // Prefer an already-open Holomint window over spawning another one.
      for (const c of list) {
        if (c.url.includes(self.location.origin) && 'focus' in c) {
          c.focus();
          c.postMessage({ type: 'drop-open', url: target });
          return;
        }
      }
      return self.clients.openWindow(target);
    })
  );
});

/* If the browser rotates a subscription out from under us, tell the app so it
   can re-register with the Worker instead of silently going dead. */
self.addEventListener('pushsubscriptionchange', e => {
  e.waitUntil(
    self.clients.matchAll({ includeUncontrolled: true })
      .then(list => list.forEach(c => c.postMessage({ type: 'push-resubscribe' })))
  );
});
