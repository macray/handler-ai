// Light, dark, or like the OS: the person's choice (Settings → Appearance), kept in this browser,
// applied as the `.dark` class the theme tokens (acp-view's theme.css) key off. The desktop's
// choice, the same three (web-ui's lib/theme.svelte.ts: this client never imports the web UI).
// A session stays dark, like a terminal, in every theme (`term-surface` on its screen only).
//
// Known limit: index.html's neutral screen, painted before any script, follows the OS
// (`prefers-color-scheme`: the page's policy runs no inline script, which could read this choice);
// a phone set to the other theme sees it turn at the app's first paint.

export type ThemeChoice = "system" | "light" | "dark";

const KEY = "handler.theme";
const os = matchMedia("(prefers-color-scheme: dark)");

// the browser's bar and the status bar's colour: the page's (app.css `--page`), the session's bar
const CHROME = { light: "#f8f6f2", dark: "#1a1917", term: "#181715" } as const;

function stored(): ThemeChoice {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

class Theme {
  choice = $state<ThemeChoice>(stored());
  /** A session's screen is shown: the browser's bar takes its dark colour. */
  term = false;

  start(): void {
    this.apply();
    os.addEventListener("change", () => this.apply());
  }

  set(choice: ThemeChoice): void {
    this.choice = choice;
    try {
      if (choice === "system") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, choice);
    } catch {
      // storage refused: the choice lasts until the page is closed
    }
    this.apply();
  }

  /** The session's screen opened or closed. */
  setTerm(on: boolean): void {
    this.term = on;
    this.apply();
  }

  private apply(): void {
    const dark = this.choice === "dark" || (this.choice === "system" && os.matches);
    const root = document.documentElement;
    root.classList.toggle("dark", dark);
    root.style.colorScheme = dark ? "dark" : "light"; // form controls, scroll bars, an app's frame
    const color = this.term ? CHROME.term : dark ? CHROME.dark : CHROME.light;
    for (const meta of document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')) meta.content = color;
  }
}

export const theme = new Theme();
