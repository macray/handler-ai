// handler remote: the service worker. It keeps the client's own files so the app opens without
// a network (its last Home, sealed, is the page's: snapshot.ts), and shows notifications (apps
// design §7, H.10).
//
// The client's files: the build writes their list and its version below (vite.config.ts,
// `offlineShell`); `vite dev` leaves it empty, and nothing is kept. They are fetched from the
// gateway first, every time, as without a worker (it has the browser check them on each use, so
// a new client is used at once): the copy kept is used only when the gateway does not answer.
// A new build is a new worker with a cache of its own; the previous one is deleted. The
// gateway's API (`/v1/`) never passes through here, and nothing it answers is ever kept.
const BUILD = { version: "dev", files: [] };
const CACHE = `handler-client-${BUILD.version}`;

self.addEventListener("install", (event) => {
  self.skipWaiting();
  if (BUILD.files.length) event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(BUILD.files)));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) => Promise.all(names.filter((n) => n.startsWith("handler-client-") && n !== CACHE).map((n) => caches.delete(n))))
      .then(() => self.clients.claim()),
  );
});

/** The kept copy of a client's file (the page for any address it opens at), if any. */
async function kept(request) {
  const cache = await caches.open(CACHE);
  return cache.match(request.mode === "navigate" ? "/" : request, { ignoreSearch: true });
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (!BUILD.files.length || request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/v1/")) return; // the API: the network's, always
  event.respondWith(
    fetch(request).then(
      // a gateway behind a proxy that is down answers 502/503: the copy, when there is one
      async (response) => (response.status >= 500 ? ((await kept(request)) ?? response) : response),
      async () => (await kept(request)) ?? Response.error(),
    ),
  );
});

// A push carries one byte, its kind (encrypted, padded: the browser decrypts it): "n" a shared
// session needs you, "a" an app has news. The text is fetched through the encrypted channel when
// the client opens. Firefox for Android needs the body: there is always one.
const KINDS = {
  n: { body: "A session needs you. Open to see it.", tag: "handler-needs-you" },
  a: { body: "Something new for you. Open to see it.", tag: "handler" },
};

self.addEventListener("push", (event) => {
  const kind = KINDS[event.data ? event.data.text() : ""] ?? KINDS.a;
  event.waitUntil(
    self.registration.showNotification("Handler", { body: kind.body, tag: kind.tag, renotify: true }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: "window" }).then((windows) => {
      for (const w of windows) if ("focus" in w) return w.focus();
      return self.clients.openWindow("/");
    }),
  );
});
