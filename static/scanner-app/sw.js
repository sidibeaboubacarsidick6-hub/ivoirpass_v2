/**
 * IvoirPass V2 — Service Worker Scanner PWA
 * ==========================================
 * Responsabilités :
 *   1. Pré-cacher l'app shell (HTML, JS lib, icône) au 1er chargement.
 *   2. Servir en "cache-first" les ressources statiques → l'app
 *      s'ouvre en mode avion.
 *   3. Servir en "network-only" (jamais caché) les appels API :
 *      - /api/scanner/*  → toujours frais pour éviter les scans fantômes
 *   4. Fallback : si offline et ressource non cachée → renvoyer l'app shell.
 *
 * Le cache offline des BILLETS (IndexedDB) est géré côté page, pas ici.
 *
 * Version : si on change le nom du cache, tous les anciens caches sont
 * purgés à l'activation (voir event 'activate').
 */

const CACHE_NAME = 'ivoirpass-scanner-v2';

// Ressources pré-cachées à l'installation (chemin relatifs à /scanner/app/)
const PRECACHE_URLS = [
  '/scanner/app/',
  '/static/scanner-app/html5-qrcode.min.js',
  '/static/scanner-app/icon-192.svg',
  '/static/scanner-app/icon-512.svg',
];


// ── Installation : pré-cache l'app shell ─────────────────────────
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS))
  );
  // Prend le contrôle immédiatement sans attendre le reload
  self.skipWaiting();
});


// ── Activation : purge les anciens caches ────────────────────────
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    )
  );
  // Contrôle les pages ouvertes sans reload
  self.clients.claim();
});


// ── Fetch : stratégie selon le type de requête ────────────────────
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // 1) Les appels API : jamais cachés (online-only).
  //    En offline, ces appels échoueront → c'est la page qui gère
  //    la queue locale (IndexedDB), pas le SW.
  if (url.pathname.startsWith('/api/scanner/')) {
    return; // laisse passer la requête réseau telle quelle
  }

  // 2) Les ressources statiques : cache-first
  if (
    url.pathname.startsWith('/static/') ||
    url.pathname.endsWith('.js') ||
    url.pathname.endsWith('.css') ||
    url.pathname.endsWith('.png') ||
    url.pathname.endsWith('.svg')
  ) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        if (cached) return cached;
        return fetch(event.request).then((response) => {
          // On met en cache uniquement les 200 OK
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          }
          return response;
        });
      })
    );
    return;
  }

  // 3) Le HTML de l'app : network-first, fallback cache (offline)
  if (url.pathname === '/scanner/app/' || url.pathname === '/scanner/app') {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          return response;
        })
        .catch(() => caches.match('/scanner/app/'))
    );
    return;
  }

  // 4) Tout le reste : réseau par défaut, pas de cache
});