const CACHE_NAME = 'petorlandia-cache-v1';
const urlsToCache = [
  '/',
  '/static/logo_pet.png',
  '/static/favicon.png'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(urlsToCache))
  );
});

self.addEventListener('fetch', event => {
  event.respondWith(
    caches.match(event.request).then(response => {
      return response || fetch(event.request);
    })
  );
});
