const CACHE_NAME = "metime-v3-cache";
const OFFLINE_URL = "/static/offline.html";
const CORE_ASSETS = [
    "/static/offline.html",
    "/static/manifest.json",
    "/static/icon-192.png",
    "/static/icon-512.png",
    "/static/apple-touch-icon.png"
];

self.addEventListener("install", event => {
    event.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(CORE_ASSETS)).catch(() => {}));
    self.skipWaiting();
});

self.addEventListener("activate", event => {
    event.waitUntil(caches.keys().then(keys =>
        Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))));
    self.clients.claim();
});

self.addEventListener("fetch", event => {
    const request = event.request;
    if (request.method !== "GET") return;
    if (!request.url.startsWith(self.location.origin)) return;
    const url = new URL(request.url);
    if (request.mode === "navigate") {
        event.respondWith(fetch(request).catch(() => caches.match(OFFLINE_URL)));
        return;
    }
    if (url.pathname.startsWith("/static/")) {
        event.respondWith(
            fetch(request).then(response => {
                const copy = response.clone();
                caches.open(CACHE_NAME).then(c => { if (response.status === 200) c.put(request, copy); });
                return response;
            }).catch(() => caches.match(request))
        );
    }
});
