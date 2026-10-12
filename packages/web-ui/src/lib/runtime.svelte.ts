// Can this computer run agents' sandboxes (A.8): checked once when the UI opens, again on
// demand. A failed check is shown on every page (App), not only in Settings → Images. The last
// result is kept in this browser so the banner is there on the first paint (no page jump), until
// the new check replaces it.

import { api } from "./api";
import type { RuntimeCheck } from "./contracts.gen";

const KEY = "handler.runtime";

function remembered(): RuntimeCheck | null {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "null") as RuntimeCheck | null;
  } catch {
    return null;
  }
}

class RuntimeStore {
  check = $state<RuntimeCheck | null>(null);
  error = $state<string | null>(null);
  last = $state<RuntimeCheck | null>(remembered()); // the latest result, this one's or a previous visit's

  async refresh(): Promise<void> {
    this.check = null;
    this.error = null;
    try {
      this.check = this.last = await api.runtime();
      try {
        localStorage.setItem(KEY, JSON.stringify(this.check));
      } catch {
        // not kept: the banner then waits for the check
      }
    } catch (e) {
      this.error = (e as Error).message;
    }
  }

  /** Agents cannot run here: something required is missing (as last checked). */
  get blocked(): boolean {
    return this.last?.ok === false;
  }
}

export const runtime = new RuntimeStore();
