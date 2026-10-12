<script lang="ts">
  // Settings, one page per section (lib/settings.ts, picked in the settings nav of the sidebar):
  // model access (accounts D.9 and providers D.12, ModelAccess); project contexts (D.19); addons and their configurations (G, D.15: bindings);
  // the secrets they all use and how agents get them (D.14, E3);
  // the work folders (D.13); the caches (D.8); remote control (D.7); images (D.4). Projects have
  // their own pages.
  import AddonsSettings from "../components/AddonsSettings.svelte";
  import CachesSettings from "../components/CachesSettings.svelte";
  import ContextsSettings from "../components/ContextsSettings.svelte";
  import FoldersSettings from "../components/FoldersSettings.svelte";
  import HarnessImages from "../components/HarnessImages.svelte";
  import ModelAccess from "../components/ModelAccess.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import AppearanceSettings from "../components/AppearanceSettings.svelte";
  import PageTitle from "../components/PageTitle.svelte";
  import RemoteSettings from "../components/RemoteSettings.svelte";
  import SecretsSettings from "../components/SecretsSettings.svelte";
  import { href } from "../lib/router.svelte";
  import { SETTINGS_SECTIONS, type SettingsSection } from "../lib/settings";

  let { section }: { section: SettingsSection } = $props();

  const label = $derived(SETTINGS_SECTIONS.find((s) => s.id === section)?.label ?? "");
</script>

<PageHeader titled title={label} parent={{ label: "Settings", href: href({ view: "settings", section: "models" }) }} />
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-4xl space-y-5 px-8 py-10">
    <PageTitle title={label} />
    <div class="space-y-12" data-testid="settings-{section}">
      {#if section === "models"}
        <ModelAccess />
      {:else if section === "contexts"}
        <ContextsSettings />
      {:else if section === "folders"}
        <FoldersSettings />
      {:else if section === "caches"}
        <CachesSettings />
      {:else if section === "addons"}
        <AddonsSettings />
      {:else if section === "secrets"}
        <SecretsSettings />
      {:else if section === "remote"}
        <RemoteSettings />
      {:else if section === "images"}
        <HarnessImages />
      {:else if section === "appearance"}
        <AppearanceSettings />
      {/if}
    </div>
  </div>
</div>
