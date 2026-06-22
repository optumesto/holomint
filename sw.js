const CACHE = 'holomint-v40';        // app shell — replaced on every release
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
