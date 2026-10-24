// The sections of Settings, one page each, grouped as the Settings page lists them: what agents
// run on and are given (model access first: nothing runs without it), then this computer.

export type SettingsSection = "models" | "areas" | "secrets" | "helpers" | "voice" | "folders" | "caches" | "remote" | "images" | "sources" | "appearance";

export const SETTINGS_GROUPS: { label: string; sections: { id: SettingsSection; label: string }[] }[] = [
  {
    label: "Agents",
    sections: [
      { id: "models", label: "Model access" },
      { id: "areas", label: "Areas" },
      { id: "secrets", label: "Secrets" },
      { id: "helpers", label: "Helpers" },
      { id: "voice", label: "Voice" },
    ],
  },
  {
    label: "This computer",
    sections: [
      { id: "folders", label: "Folders" },
      { id: "caches", label: "Caches" },
      { id: "remote", label: "Remote" },
      { id: "images", label: "Images" },
      { id: "sources", label: "Sources" },
      { id: "appearance", label: "Appearance" },
    ],
  },
];

export const SETTINGS_SECTIONS = SETTINGS_GROUPS.flatMap((g) => g.sections);
