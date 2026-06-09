// Service worker minimal — coquille hors-ligne (PWA).
// Met en cache les ressources statiques pour un démarrage instantané.
const CACHE = "tresorerie-v1";
const ASSETS = [
  "/static/style.css",
  "/static/manifest.webmanifest"
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  // Réseau d'abord pour les pages (données fraîches), cache en secours.
  if (req.method === "GET" && req.headers.get("accept")?.includes("text/html")) {
    e.respondWith(fetch(req).catch(() => caches.match(req)));
    return;
  }
  // Cache d'abord pour les ressources statiques.
  e.respondWith(caches.match(req).then((r) => r || fetch(req)));
});
