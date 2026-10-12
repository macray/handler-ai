import { mount } from "svelte";
import App from "./App.svelte";
import "./app.css";
import { app } from "./lib/app.svelte";

// Dark or light like the OS (the theme tokens key off `.dark`); the chat is always dark.
const dark = matchMedia("(prefers-color-scheme: dark)");
const applyTheme = () => document.documentElement.classList.toggle("dark", dark.matches);
applyTheme();
dark.addEventListener("change", applyTheme);

void app.init();

const target = document.getElementById("app");
if (!target) throw new Error("#app missing");
export default mount(App, { target });
