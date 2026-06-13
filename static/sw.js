// Service worker — PWA hors-ligne.
// Réseau d'abord avec délai maxi de 4 s : si le réseau ne répond pas à temps
// (hors-ligne, réseau lent, serveur endormi), on sert la dernière version en
// cache pour que l'application reste utilisable.
const CACHE = "tresorerie-v11";

self.addEventListener("install", (e) => {
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

function networkFirst(req, timeoutMs) {
  return new Promise((resolve, reject) => {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    fetch(req, { signal: ctrl.signal })
      .then((res) => {
        clearTimeout(timer);
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy));
        resolve(res);
      })
      .catch(() => {
        clearTimeout(timer);
        caches.match(req).then((cached) => {
          if (cached) resolve(cached);
          else reject(new Error("offline"));
        });
      });
  });
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;            // les POST passent en direct
  const url = new URL(req.url);
  if (url.pathname.startsWith("/api/")) return; // l'API gère son propre échec
  // Pages HTML : 4 s maxi ; ressources statiques : 8 s (elles changent peu).
  const isHTML = (req.headers.get("accept") || "").includes("text/html");
  e.respondWith(networkFirst(req, isHTML ? 4000 : 8000));
});
