const CACHE_NAME = 'petorlandia-cache-v1';
// Pages like the home page change based on login state, so we avoid
// pre-caching them. Only static assets are cached up-front.
const urlsToCache = [
  '/static/logo_pet.png',
  '/static/favicon.png'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(urlsToCache))
  );
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
