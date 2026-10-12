import { mount } from "svelte";
import App from "./App.svelte";
import "./app.css";
import { captureToken } from "./lib/auth";
import { startRouter } from "./lib/router.svelte";
import { remote } from "./lib/remote.svelte";
import { sessions } from "./lib/sessions.svelte";
import { theme } from "./lib/theme.svelte";

theme.start(); // light, dark or like the OS (Settings → Appearance)
captureToken();
startRouter();
void sessions.restore(); // the daemon's sessions of this sidebar, re-attached if running
remote.start(); // the remote connector's light (sidebar, session view)

const target = document.getElementById("app");
if (!target) throw new Error("#app missing");
export default mount(App, { target });
