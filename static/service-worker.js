// Bump the cache name to force old caches to be cleared after updates
const CACHE_NAME = 'petorlandia-cache-v5';
// Pages like the home page change based on login state, so we avoid
// pre-caching them. Only static assets are cached up-front.
const urlsToCache = [
  '/static/pastorgato.png'
  ,'/static/offline.js'
  ,'/static/bootstrap.min.css'
  ,'/static/bootstrap.bundle.min.js'
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
  // AJAX requests (listing panels, autocomplete, etc.) — vai direto à rede,
  // sem tocar no cache. Evita retornar HTML cacheado no lugar de JSON.
  const isAjax = event.request.headers.get('X-Requested-With') === 'XMLHttpRequest'
    || event.request.headers.get('Accept') === 'application/json';
  if (isAjax) {
    event.respondWith(fetch(event.request));
    return;
  }

  // Requisições de navegação (visitar uma página) — rede primeiro, sem
  // cachear a resposta (páginas são dinâmicas e dependem de autenticação).
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).catch(() => caches.match(event.request))
    );
    return;
  }

  // Assets estáticos — cache primeiro, rede como fallback.
  event.respondWith(
    caches.match(event.request).then(response => response || fetch(event.request))
  );
});
