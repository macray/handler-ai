<script lang="ts">
  // Settings, one page per section (lib/settings.ts), picked in the page's own list of them, by
  // group, left of the section (a dropdown in a narrow window); the menu stays as on every page:
  // model access (accounts D.9 and providers D.12, ModelAccess); areas (D.19);
  // the secrets they all use (the addons', in the library: AddonsView) and how agents get them (D.14, E3);
  // Handler's helpers (its roles, D.18); Voice (speaking to Ask, D.25);
  // the work folders (D.13); the caches (D.8); remote control (D.7); images (D.4); the sources
  // apps, agents and addons come from (D.26). Projects have their own pages.
  import CachesSettings from "../components/CachesSettings.svelte";
  import AreasSettings from "../components/AreasSettings.svelte";
  import FoldersSettings from "../components/FoldersSettings.svelte";
  import HelpersSettings from "../components/HelpersSettings.svelte";
  import VoiceSettings from "../components/VoiceSettings.svelte";
  import HarnessImages from "../components/HarnessImages.svelte";
  import ModelAccess from "../components/ModelAccess.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import AppearanceSettings from "../components/AppearanceSettings.svelte";
  import PageTitle from "../components/PageTitle.svelte";
  import RemoteSettings from "../components/RemoteSettings.svelte";
  import SecretsSettings from "../components/SecretsSettings.svelte";
  import SourcesSettings from "../components/SourcesSettings.svelte";
  import Bot from "@lucide/svelte/icons/bot";
  import Database from "@lucide/svelte/icons/database";
  import FolderOpen from "@lucide/svelte/icons/folder-open";
  import KeyRound from "@lucide/svelte/icons/key-round";
  import LockKeyhole from "@lucide/svelte/icons/lock-keyhole";
  import Mic from "@lucide/svelte/icons/mic";
  import Package from "@lucide/svelte/icons/package";
  import Palette from "@lucide/svelte/icons/palette";
  import Smartphone from "@lucide/svelte/icons/smartphone";
  import Store from "@lucide/svelte/icons/store";
  import Tags from "@lucide/svelte/icons/tags";
  import { LIGHT_LABEL, lightTone, remote } from "../lib/remote.svelte";
  import { href } from "../lib/router.svelte";
  import { SETTINGS_GROUPS, SETTINGS_SECTIONS, type SettingsSection } from "../lib/settings";

  const ICONS: Record<SettingsSection, typeof KeyRound> = {
    models: KeyRound,
    areas: Tags,
    secrets: LockKeyhole,
    helpers: Bot,
    voice: Mic,
    folders: FolderOpen,
    caches: Database,
    remote: Smartphone,
    images: Package,
    sources: Store,
    appearance: Palette,
  };

  let { section }: { section: SettingsSection } = $props();

  const label = $derived(SETTINGS_SECTIONS.find((s) => s.id === section)?.label ?? "");
</script>

<PageHeader titled title={label} parent={{ label: "Settings", href: href({ view: "settings", section: "models" }) }} />
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto flex w-full max-w-6xl gap-10 px-8 py-10">
    <nav class="sticky top-0 hidden w-48 shrink-0 self-start md:block" aria-label="settings" data-testid="settings-nav">
      {#each SETTINGS_GROUPS as g, i (g.label)}
        <p class="px-2.5 pb-1.5 font-mono text-xs text-muted-foreground lowercase {i ? 'pt-4' : 'pt-1'}">{g.label}</p>
        {#each g.sections as s (s.id)}
          {@const Icon = ICONS[s.id]}
          {@const on = s.id === section}
          <a
            href={href({ view: "settings", section: s.id })}
            aria-current={on ? "page" : undefined}
            class="flex h-8 items-center gap-2 rounded-md px-2.5 text-sm no-underline {on
              ? 'bg-muted font-medium text-foreground ring-1 ring-border'
              : 'text-sidebar-foreground hover:bg-muted/60'}"
            data-testid="settings-nav-{s.id}"
            ><Icon class="size-4 shrink-0 {on ? 'text-primary' : 'text-muted-foreground'}" />{s.label}
            {#if s.id === "remote" && remote.status && remote.status.light !== "off"}
              <span class="ml-auto size-2 rounded-full {lightTone(remote.status.light)}" aria-label={LIGHT_LABEL[remote.status.light]}></span>
            {/if}
          </a>
        {/each}
      {/each}
    </nav>
    <div class="min-w-0 flex-1 space-y-5">
      <!-- a narrow window: the sections in a dropdown above the title -->
      <select
        class="w-full rounded-md border border-input bg-background px-2.5 py-1.5 text-sm md:hidden"
        aria-label="settings section"
        value={section}
        onchange={(e) => (window.location.hash = href({ view: "settings", section: e.currentTarget.value as SettingsSection }))}>
        {#each SETTINGS_GROUPS as g (g.label)}
          <optgroup label={g.label}>
            {#each g.sections as s (s.id)}<option value={s.id}>{s.label}</option>{/each}
          </optgroup>
        {/each}
      </select>
      <PageTitle title={label} />
      <div class="space-y-12" data-testid="settings-{section}">
        {#if section === "models"}
          <ModelAccess />
        {:else if section === "areas"}
          <AreasSettings />
        {:else if section === "folders"}
          <FoldersSettings />
        {:else if section === "caches"}
          <CachesSettings />
        {:else if section === "secrets"}
          <SecretsSettings />
        {:else if section === "helpers"}
          <HelpersSettings />
        {:else if section === "voice"}
          <VoiceSettings />
        {:else if section === "remote"}
          <RemoteSettings />
        {:else if section === "images"}
          <HarnessImages />
        {:else if section === "sources"}
          <SourcesSettings />
        {:else if section === "appearance"}
          <AppearanceSettings />
        {/if}
      </div>
    </div>
  </div>
</div>
