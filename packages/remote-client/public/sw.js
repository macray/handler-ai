// handler remote: the service worker, for notifications only (docs/dev/design/miniapps.md §7).
// Pushes carry nothing: the text is fetched through the encrypted channel when the client opens.
self.addEventListener("push", (event) => {
  event.waitUntil(
    self.registration.showNotification("Handler", {
      body: "Something new for you. Open to see it.",
      tag: "handler",
      renotify: true,
    }),
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
