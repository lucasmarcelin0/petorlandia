// Bump the cache name to force old caches to be cleared after updates
const CACHE_NAME = 'petorlandia-cache-v8';
// Pages like the home page change based on login state, so we avoid
// pre-caching them. Only static assets are cached up-front.
const urlsToCache = [
  '/static/pastorgato-96.png'
  ,'/static/pastorgato-192.png'
  ,'/static/logo_pet-320.png'
  ,'/static/offline.js'
  ,'/static/bootstrap.min.css'
  ,'/static/bootstrap.bundle.min.js'
  ,'/static/offline.html'
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
  // Requisições cross-origin (CDNs, S3, Google Fonts) — não interceptar.
  // O fetch() dentro do service worker é limitado pelo CSP do próprio worker
  // (connect-src 'self'), o que bloquearia esses recursos; deixamos o
  // navegador tratá-las diretamente, sob o CSP da página.
  if (new URL(event.request.url).origin !== self.location.origin) {
    return;
  }

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
      fetch(event.request).catch(() => caches.match(event.request).then(cached => cached || caches.match('/static/offline.html')))
    );
    return;
  }

  // Assets estáticos — cache primeiro, rede como fallback.
  event.respondWith(
    caches.match(event.request).then(response => response || fetch(event.request))
  );
});


// ── Web Push ────────────────────────────────────────────────────────────────
self.addEventListener('push', event => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    data = { title: 'PetOrlândia', body: event.data ? event.data.text() : '' };
  }
  const title = data.title || 'PetOrlândia';
  const options = {
    body: data.body || '',
    icon: '/static/pastorgato-192.png',
    badge: '/static/pastorgato-96.png',
    tag: data.tag || 'petorlandia',
    data: { url: data.url || '/' },
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(windowClients => {
      for (const client of windowClients) {
        if (client.url.includes(self.location.origin) && 'focus' in client) {
          client.navigate(url);
          return client.focus();
        }
      }
      return clients.openWindow(url);
    })
  );
});
