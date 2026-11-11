// The sections of Settings, one page each, as the Settings page lists them: the everyday ones
// (model access first: nothing runs without it), then Expert, folded until opened once.

export type SettingsSection = "models" | "helpers" | "folders" | "phone" | "appearance" | "areas" | "secrets" | "voice" | "caches" | "sandboxes" | "sources";

export const SETTINGS_MAIN: { id: SettingsSection; label: string }[] = [
  { id: "models", label: "Model access" },
  { id: "helpers", label: "Helpers" },
  { id: "folders", label: "Folders" },
  { id: "phone", label: "Your phone" },
  { id: "appearance", label: "Appearance" },
];

export const SETTINGS_EXPERT: { id: SettingsSection; label: string }[] = [
  { id: "areas", label: "Areas" },
  { id: "secrets", label: "Secrets" },
  { id: "voice", label: "Voice" },
  { id: "caches", label: "Caches" },
  { id: "sandboxes", label: "Sandboxes" },
  { id: "sources", label: "Sources" },
];

export const SETTINGS_SECTIONS = [...SETTINGS_MAIN, ...SETTINGS_EXPERT];

/** Expert stays open once opened (this browser). */
const EXPERT_KEY = "handler.settings.expert";

export function expertOpened(): boolean {
  try {
    return localStorage.getItem(EXPERT_KEY) === "1";
  } catch {
    return false;
  }
}

export function openExpert(): void {
  try {
    localStorage.setItem(EXPERT_KEY, "1");
  } catch {
    // not kept: folded again next time
  }
}
