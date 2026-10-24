// Light, dark, or like the OS: the user's choice (kept in this browser), applied as the `.dark`
// class Tailwind's `dark:` variant and the theme tokens key off. And the menu's look: "liquid" (the
// default, the `.liquid` class: translucent over a calm backdrop, app.css) or one flat colour.

export type ThemeChoice = "system" | "light" | "dark";
export type MenuLook = "flat" | "liquid";

const KEY = "handler.theme";
const MENU_KEY = "handler.menu";
const os = matchMedia("(prefers-color-scheme: dark)");

function stored(): ThemeChoice {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

function storedMenu(): MenuLook {
  try {
    return localStorage.getItem(MENU_KEY) === "flat" ? "flat" : "liquid";
  } catch {
    return "liquid";
  }
}

class Theme {
  choice = $state<ThemeChoice>(stored());
  menu = $state<MenuLook>(storedMenu());

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
      // storage refused: the choice lasts until the tab is closed
    }
    this.apply();
  }

  setMenu(look: MenuLook): void {
    this.menu = look;
    try {
      if (look === "liquid") localStorage.removeItem(MENU_KEY);
      else localStorage.setItem(MENU_KEY, look);
    } catch {
      // storage refused: the choice lasts until the tab is closed
    }
    this.apply();
  }

  private apply(): void {
    const dark = this.choice === "dark" || (this.choice === "system" && os.matches);
    document.documentElement.classList.toggle("dark", dark);
    document.documentElement.classList.toggle("liquid", this.menu === "liquid");
  }
}

export const theme = new Theme();
