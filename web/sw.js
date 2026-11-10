// POKRR offline support: the home page, guides and game rules keep working
// without internet once opened (newest copy when online, saved copy when
// offline). The live game itself needs a connection and is never cached here.
const CACHE = "pokrr-guides-v4";
const PRECACHE = ["/", "/games", "/learn/hand-rankings", "/learn/teen-patti-rankings",
                  "/learn/how-to-play", "/learn/add-ons", "/about", "/static/site.css?v=4",
                  "/static/icon-192.png"];

self.addEventListener("install", (ev) => {
  ev.waitUntil(caches.open(CACHE).then(c => c.addAll(PRECACHE)).catch(() => {}));
  self.skipWaiting();
});
self.addEventListener("activate", (ev) => {
  ev.waitUntil(caches.keys().then(keys => Promise.all(
    keys.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (ev) => {
  const url = new URL(ev.request.url);
  if (ev.request.method !== "GET" || url.origin !== location.origin) return;
  const guide = url.pathname === "/" || url.pathname.startsWith("/learn/") ||
                url.pathname.startsWith("/games") || url.pathname === "/about" ||
                url.pathname === "/static/site.css";
  if (!guide || url.search.includes("room=")) return;      // the game: always live
  ev.respondWith(fetch(ev.request).then(res => {
    if (res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(ev.request, copy)); }
    return res;
  }).catch(() => caches.match(ev.request)));
});
