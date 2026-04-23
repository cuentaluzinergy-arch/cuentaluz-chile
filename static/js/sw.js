/* Service Worker – CuentaLuz Chile */

const CACHE = 'cuentaluz-v2';
const STATIC = [
  '/',
  '/comunas',
  '/offline',
  '/static/css/app.css',
  '/static/css/custom.css',
  '/static/js/main.js',
  '/static/manifest.json',
  '/static/icons/icon-192.svg',
  '/static/icons/icon-512.svg',
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(STATIC)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('push', e => {
  const data = e.data ? e.data.json() : {};
  e.waitUntil(
    self.registration.showNotification(data.title || 'CuentaLuz Chile', {
      body:  data.body  || '',
      icon:  data.icon  || '/static/icons/icon-192.svg',
      badge: data.badge || '/static/icons/icon-192.svg',
      data:  { url: data.url || '/' },
      vibrate: [100, 50, 100],
    })
  );
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
      const target = e.notification.data?.url || '/';
      for (const client of list) {
        if (client.url.includes(self.location.origin) && 'focus' in client) {
          client.navigate(target);
          return client.focus();
        }
      }
      return clients.openWindow(target);
    })
  );
});

self.addEventListener('fetch', e => {
  const { request } = e;

  // No interceptar POST ni chrome-extension ni otros esquemas
  if (request.method !== 'GET' || !request.url.startsWith('http')) return;

  const url = new URL(request.url);

  // API interna → network-first, sin cache
  if (url.pathname.startsWith('/api/') || url.pathname === '/calcular') {
    e.respondWith(
      fetch(request).catch(() => new Response(JSON.stringify({ error: 'Sin conexión' }), {
        headers: { 'Content-Type': 'application/json' }
      }))
    );
    return;
  }

  // Páginas HTML → network-first, cache como respaldo
  if (request.headers.get('Accept')?.includes('text/html')) {
    e.respondWith(
      fetch(request)
        .then(res => {
          const clone = res.clone();
          caches.open(CACHE).then(c => c.put(request, clone));
          return res;
        })
        .catch(() => caches.match(request).then(cached => cached || caches.match('/offline')))
    );
    return;
  }

  // Assets estáticos → cache-first
  e.respondWith(
    caches.match(request).then(cached => {
      if (cached) return cached;
      return fetch(request).then(res => {
        if (res.ok) {
          const clone = res.clone();
          caches.open(CACHE).then(c => c.put(request, clone));
        }
        return res;
      });
    })
  );
});
