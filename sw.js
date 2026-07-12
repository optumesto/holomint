const CACHE = 'holomint-v57';        // app shell, replaced on every release
const MEDIA = 'holomint-media';      // card images / cross-origin — persists across releases
const SHELL = ['./', './index.html', './manifest.json', './icon-192.png', './icon-512.png', './leaf-splash.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  // Drop old shell caches, but keep the current shell and the persistent media cache.
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE && k !== MEDIA).map(k => caches.delete(k)))
  ).then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  const url = new URL(e.request.url);

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

  // Same-origin data files (prices.json, products.json, etc.): network-first so daily
  // updates land; fall back to cache when offline at a show.
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
    data: { url: d.url || './' },
    actions: [{ action: 'open', title: 'Open listing' }]
  };
  e.waitUntil(self.registration.showNotification(title, opts));
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  const target = (e.notification.data && e.notification.data.url) || './';
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
