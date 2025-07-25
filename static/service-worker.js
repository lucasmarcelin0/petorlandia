// Bump the cache name to force old caches to be cleared after updates
const CACHE_NAME = 'petorlandia-cache-v3';
// Pages like the home page change based on login state, so we avoid
// pre-caching them. Only static assets are cached up-front.
const urlsToCache = [
  '/static/pastorgato.png'
];

// Install the service worker and take control immediately
self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(urlsToCache))
  );
});

// Remove outdated caches when activating the new service worker
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  // For navigation requests (like visiting "/"), prefer the network so
  // users always see the latest authenticated content. Fall back to cache
  // when offline.
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request)
        .then(response => {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
          return response;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  event.respondWith(
    caches.match(event.request).then(response => response || fetch(event.request))
  );
});
