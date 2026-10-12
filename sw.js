// Offline support: precache the app shell, word lists and font; serve from cache first
// and refresh the cache in the background (stale-while-revalidate). Same-origin only.
const CACHE = "bichig-v1";
const ASSETS = [
  "./",
  "index.html",
  "core.js",
  "manifest.webmanifest",
  "icon.svg",
  "fonts/NotoSansMongolian-Regular.woff2",
  "data/words-4.json",
  "data/words-5.json",
  "data/words-6.json",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== self.location.origin) return;
  e.respondWith(
    caches.open(CACHE).then(async (cache) => {
      const cached = await cache.match(e.request, { ignoreSearch: true });
      const network = fetch(e.request)
        .then((res) => {
          if (res.ok) cache.put(e.request, res.clone());
          return res;
        })
        .catch(() => cached);
      if (cached) {
        e.waitUntil(network);
        return cached;
      }
      return network;
    }),
  );
});
