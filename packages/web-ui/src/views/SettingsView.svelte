<script lang="ts">
  // Settings, one page per section (lib/settings.ts), picked in the page's own list of them, left
  // of the section (a dropdown in a narrow window); the menu stays as on every page. The everyday
  // ones: model access (accounts D.9 and providers D.12, ModelAccess); Handler's helpers (its
  // needs, D.18; one helper's page, `helper`); the work folders (D.13); your phone (D.7);
  // appearance. Then Expert, folded until opened once, a dot on it when something inside needs
  // fixing (this computer's sandboxes, a secret that needs you): areas (D.19); the secrets (D.14,
  // E3); Voice (speaking to Ask, D.25); the caches (D.8); the sandboxes (D.2, D.4); the sources
  // (D.26).
  import CachesSettings from "../components/CachesSettings.svelte";
  import AreasSettings from "../components/AreasSettings.svelte";
  import FoldersSettings from "../components/FoldersSettings.svelte";
  import HelperPage from "../components/HelperPage.svelte";
  import HelpersSettings from "../components/HelpersSettings.svelte";
  import VoiceSettings from "../components/VoiceSettings.svelte";
  import SandboxesSettings from "../components/SandboxesSettings.svelte";
  import ModelAccess from "../components/ModelAccess.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import AppearanceSettings from "../components/AppearanceSettings.svelte";
  import PhoneSettings from "../components/PhoneSettings.svelte";
  import SecretsSettings from "../components/SecretsSettings.svelte";
  import SourcesSettings from "../components/SourcesSettings.svelte";
  import Box from "@lucide/svelte/icons/box";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import Database from "@lucide/svelte/icons/database";
  import Folder from "@lucide/svelte/icons/folder";
  import KeyRound from "@lucide/svelte/icons/key-round";
  import Link from "@lucide/svelte/icons/link";
  import Lock from "@lucide/svelte/icons/lock";
  import Mic from "@lucide/svelte/icons/mic";
  import Smartphone from "@lucide/svelte/icons/smartphone";
  import Sparkle from "@lucide/svelte/icons/sparkle";
  import Sun from "@lucide/svelte/icons/sun";
  import Tag from "@lucide/svelte/icons/tag";
  import { api } from "../lib/api";
  import { needLabel } from "../lib/helpers";
  import { LIGHT_LABEL, lightTone, remote } from "../lib/remote.svelte";
  import { href } from "../lib/router.svelte";
  import { runtime } from "../lib/runtime.svelte";
  import { menuUse } from "../lib/menuuse.svelte";
  import { needsYou } from "../lib/secrets";
  import { expertOpened, openExpert, SETTINGS_EXPERT, SETTINGS_MAIN, SETTINGS_SECTIONS, type SettingsSection } from "../lib/settings";

  const ICONS: Record<SettingsSection, typeof KeyRound> = {
    models: KeyRound,
    helpers: Sparkle,
    folders: Folder,
    phone: Smartphone,
    appearance: Sun,
    areas: Tag,
    secrets: Lock,
    voice: Mic,
    caches: Database,
    sandboxes: Box,
    sources: Link,
  };

  let { section, helper }: { section: SettingsSection; helper?: string } = $props();

  // Voice speaks to Ask: listed once something is offered (its page still opens by its address)
  const expert = $derived(SETTINGS_EXPERT.filter((s) => s.id !== "voice" || menuUse.offers || s.id === section));
  const inExpert = $derived(SETTINGS_EXPERT.some((s) => s.id === section));
  let opened = $state(expertOpened());
  $effect(() => {
    if (inExpert && !opened) open();
  });
  function open(): void {
    opened = true;
    openExpert();
  }
  // what needs fixing inside Expert: this computer cannot run every sandbox (A.8); a secret is
  // missing, or an agent reads one (D.14, E3), checked again on each section opened
  let secretsNeed = $state(false);
  $effect(() => {
    void section;
    api.secrets().then(
      (list) => (secretsNeed = list.some(needsYou)),
      () => {},
    );
  });
  const fix = $derived<Partial<Record<SettingsSection, boolean>>>({ secrets: secretsNeed, sandboxes: !!runtime.last?.items.some((i) => !i.ok) });
  const expertFix = $derived(Object.values(fix).some(Boolean));

  const label = $derived(SETTINGS_SECTIONS.find((s) => s.id === section)?.label ?? "");
  const settingsHref = href({ view: "settings", section: "models" });
  const parent = $derived(helper ? { label: "Helpers", href: href({ view: "settings", section: "helpers" }) } : { label: "Settings", href: settingsHref });
  const title = $derived(helper ? needLabel(helper) : label);
</script>

<PageHeader {title} {parent} />
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto flex w-full max-w-6xl gap-10 px-8 py-10">
    <nav class="sticky top-0 hidden w-48 shrink-0 self-start md:block" aria-label="settings" data-testid="settings-nav">
      {#snippet row(s: { id: SettingsSection; label: string })}
        {@const Icon = ICONS[s.id]}
        {@const on = s.id === section}
        <a
          href={href({ view: "settings", section: s.id })}
          aria-current={on ? "page" : undefined}
          class="flex h-8 items-center gap-2 rounded-md px-2.5 text-sm no-underline {on ? 'bg-muted font-medium text-foreground ring-1 ring-border' : 'text-sidebar-foreground hover:bg-muted/60'}"
          data-testid="settings-nav-{s.id}"
          ><Icon class="size-4 shrink-0 {on ? 'text-primary' : 'text-muted-foreground'}" />{s.label}
          {#if s.id === "phone" && remote.status && remote.status.light !== "off"}
            <span class="ml-auto size-2 rounded-full {lightTone(remote.status.light)}" aria-label={LIGHT_LABEL[remote.status.light]}></span>
          {:else if fix[s.id]}
            <span class="ml-auto size-2 rounded-full bg-warn" aria-label="needs fixing" data-testid="settings-nav-fix"></span>
          {/if}
        </a>
      {/snippet}
      {#each SETTINGS_MAIN as s (s.id)}{@render row(s)}{/each}
      <button
        type="button"
        class="mt-3 flex h-7 w-full items-center gap-1.5 rounded-md px-2.5 text-xs font-medium text-muted-foreground hover:text-foreground"
        aria-expanded={opened}
        onclick={() => (opened ? (opened = false) : open())}
        data-testid="settings-expert"
        ><ChevronRight class="size-3.5 transition-transform {opened ? 'rotate-90' : ''}" />Expert
        {#if expertFix && !opened}<span class="size-2 rounded-full bg-warn" aria-label="something inside needs fixing" data-testid="settings-expert-fix"></span>{/if}
      </button>
      {#if opened}
        {#each expert as s (s.id)}{@render row(s)}{/each}
      {/if}
    </nav>
    <div class="min-w-0 flex-1 space-y-5">
      <!-- a narrow window: the sections in a dropdown above the title -->
      <select
        class="w-full rounded-md border border-input bg-background px-2.5 py-1.5 text-sm md:hidden"
        aria-label="settings section"
        value={section}
        onchange={(e) => (window.location.hash = href({ view: "settings", section: e.currentTarget.value as SettingsSection }))}>
        {#each SETTINGS_MAIN as s (s.id)}<option value={s.id}>{s.label}</option>{/each}
        <optgroup label="Expert">
          {#each expert as s (s.id)}<option value={s.id}>{s.label}</option>{/each}
        </optgroup>
      </select>
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
        {:else if section === "helpers" && helper}
          {#key helper}<HelperPage need={helper} />{/key}
        {:else if section === "helpers"}
          <HelpersSettings />
        {:else if section === "voice"}
          <VoiceSettings />
        {:else if section === "phone"}
          <PhoneSettings />
        {:else if section === "sandboxes"}
          <SandboxesSettings />
        {:else if section === "sources"}
          <SourcesSettings />
        {:else if section === "appearance"}
          <AppearanceSettings />
        {/if}
      </div>
    </div>
  </div>
</div>
