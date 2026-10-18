const CACHE = 'rms-shell-v9';
const SHELL = ['./', './index.html', './manifest.json', './rms-icon.svg'];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)));
  self.skipWaiting();
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('rms-shell-') && key !== CACHE).map(key => caches.delete(key)))));
  self.clients.claim();
});
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET' || new URL(event.request.url).origin !== self.location.origin) return;
  if (new URL(event.request.url).pathname.includes('/api/')) return;
  if (event.request.mode === 'navigate') {
    const path = new URL(event.request.url).pathname;
    event.respondWith(fetch(event.request).then(response => {
      if (response.ok && (path === '/' || path.endsWith('/index.html'))) {
        caches.open(CACHE).then(cache => cache.put('./index.html', response.clone()));
      }
      return response;
    }).catch(() => caches.match('./index.html')));
    return;
  }
  event.respondWith(caches.match(event.request).then(cached => cached || fetch(event.request).then(response => {
    if (response.ok) caches.open(CACHE).then(cache => cache.put(event.request, response.clone()));
    return response;
  }).catch(() => caches.match('./index.html'))));
});
