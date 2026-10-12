// Light, dark, or like the OS: the user's choice (kept in this browser), applied as the `.dark`
// class Tailwind's `dark:` variant and the theme tokens key off.

export type ThemeChoice = "system" | "light" | "dark";

const KEY = "handler.theme";
const os = matchMedia("(prefers-color-scheme: dark)");

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

  private apply(): void {
    const dark = this.choice === "dark" || (this.choice === "system" && os.matches);
    document.documentElement.classList.toggle("dark", dark);
  }
}

export const theme = new Theme();
