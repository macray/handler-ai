// The sections of Settings, one page each, grouped as the settings nav shows them: what agents
// run on and are given (model access first: nothing runs without it), then this computer.

export type SettingsSection = "models" | "contexts" | "secrets" | "folders" | "caches" | "addons" | "remote" | "images" | "appearance";

export const SETTINGS_GROUPS: { label: string; sections: { id: SettingsSection; label: string }[] }[] = [
  {
    label: "Agents",
    sections: [
      { id: "models", label: "Model access" },
      { id: "contexts", label: "Contexts" },
      { id: "addons", label: "Addons" },
      { id: "secrets", label: "Secrets" },
    ],
  },
  {
    label: "This computer",
    sections: [
      { id: "folders", label: "Folders" },
      { id: "caches", label: "Caches" },
      { id: "remote", label: "Remote" },
      { id: "images", label: "Images" },
      { id: "appearance", label: "Appearance" },
    ],
  },
];

export const SETTINGS_SECTIONS = SETTINGS_GROUPS.flatMap((g) => g.sections);
