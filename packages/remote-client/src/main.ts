import { mount } from "svelte";
import App from "./App.svelte";
import "./app.css";
import { app } from "./lib/app.svelte";
import { theme } from "./lib/theme.svelte";
import "./lib/update"; // a new client on the gateway: used without the person doing anything

// Light, dark or like the OS: the choice kept in this browser (Settings → Appearance), before the
// first paint of the app; a session stays dark, like a terminal.
theme.start();

void app.init();

// The service worker: the client's files kept, so the app opens without a network (sw.js), and
// notifications. Registered on every launch: a new build's worker replaces the last one.
if ("serviceWorker" in navigator) void navigator.serviceWorker.register("/sw.js").catch(() => undefined);

const target = document.getElementById("app");
if (!target) throw new Error("#app missing");
// index.html's neutral screen, drawn before any script ran, gives its place to the same one, live
target.replaceChildren();
export default mount(App, { target });
