<script lang="ts">
  // Settings → Appearance: light, dark or like the system, and the menu flat or liquid, for this
  // browser (lib/theme.svelte.ts). Each choice shows a small picture of the UI in it (the system's:
  // half light, half dark).
  import Check from "@lucide/svelte/icons/check";
  import Droplets from "@lucide/svelte/icons/droplets";
  import Square from "@lucide/svelte/icons/square";
  import Monitor from "@lucide/svelte/icons/monitor";
  import Moon from "@lucide/svelte/icons/moon";
  import Sun from "@lucide/svelte/icons/sun";
  import { theme, type MenuLook, type ThemeChoice } from "../lib/theme.svelte";

  const THEMES: { id: ThemeChoice; label: string; hint: string; icon: typeof Sun }[] = [
    { id: "system", label: "System", hint: "Light or dark like this computer", icon: Monitor },
    { id: "light", label: "Light", hint: "Always light", icon: Sun },
    { id: "dark", label: "Dark", hint: "Always dark", icon: Moon },
  ];
  const LOOKS: { id: MenuLook; label: string; hint: string; icon: typeof Sun }[] = [
    { id: "liquid", label: "Liquid", hint: "The menu like frosted glass over a soft backdrop", icon: Droplets },
    { id: "flat", label: "Flat", hint: "The menu in one plain colour", icon: Square },
  ];
</script>

<!-- a small picture of the UI in a theme: the sidebar, a title, lines, the accent -->
{#snippet mock(dark: boolean)}
  <div class="flex h-full w-full gap-1.5 p-2 {dark ? 'bg-[#1c1917]' : 'bg-[#f5f5f4]'}">
    <div class="w-1/4 space-y-1 pt-1">
      {#each [0, 1, 2] as i (i)}<div class="h-1 rounded-full {dark ? 'bg-[#44403c]' : 'bg-[#d6d3d1]'}"></div>{/each}
    </div>
    <div class="flex-1 space-y-1.5 rounded-md p-2 {dark ? 'bg-[#292524]' : 'bg-white'}">
      <div class="h-1.5 w-1/2 rounded-full {dark ? 'bg-[#a8a29e]' : 'bg-[#44403c]'}"></div>
      <div class="h-1 w-5/6 rounded-full {dark ? 'bg-[#57534e]' : 'bg-[#d6d3d1]'}"></div>
      <div class="h-1 w-2/3 rounded-full {dark ? 'bg-[#57534e]' : 'bg-[#d6d3d1]'}"></div>
      <div class="h-2 w-1/4 rounded-full bg-[#c2410c]"></div>
    </div>
  </div>
{/snippet}

<!-- a small picture of the menu's look: the menu (flat or over a backdrop), then a session -->
{#snippet menuMock(liquid: boolean)}
  <div class="flex h-full w-full {liquid ? 'bg-[linear-gradient(170deg,#e4e6e6,#efdfcb)]' : 'bg-[#f4f2ee]'}">
    <div class="w-1/3 space-y-1.5 p-2.5 {liquid ? 'bg-white/45' : ''}">
      {#each [0, 1, 2, 3] as i (i)}<div class="h-1 rounded-full bg-[#d6d3d1]"></div>{/each}
      <div class="mt-3 h-4 rounded bg-white shadow-sm"></div>
    </div>
    <div class="flex-1 space-y-1.5 bg-[#11100e] p-2.5">
      <div class="h-1 w-2/3 rounded-full bg-[#57534e]"></div>
      <div class="h-1 w-1/2 rounded-full bg-[#57534e]"></div>
      <div class="mt-4 h-2.5 rounded border border-[#f26b21]"></div>
    </div>
  </div>
{/snippet}

{#snippet choice(on: boolean, label: string, hint: string, Icon: typeof Sun, picture: import("svelte").Snippet, pick: () => void, testid: string)}
  <button
    type="button"
    role="radio"
    aria-checked={on}
    class="group flex flex-col overflow-hidden rounded-[10px] border bg-card text-left shadow-panel transition-[border-color,box-shadow] {on
      ? 'border-primary ring-2 ring-primary/30'
      : 'hover:border-foreground/25'}"
    onclick={pick}
    data-testid={testid}
  >
    <div class="relative aspect-[16/9] overflow-hidden border-b">{@render picture()}</div>
    <div class="flex items-start gap-2.5 p-3.5">
      <Icon class="mt-0.5 size-4 shrink-0 {on ? 'text-primary' : 'text-muted-foreground'}" />
      <span class="min-w-0 flex-1">
        <span class="block text-sm font-medium">{label}</span>
        <span class="block text-xs text-muted-foreground">{hint}</span>
      </span>
      {#if on}<span class="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground"><Check class="size-3" /></span>{/if}
    </div>
  </button>
{/snippet}

<section class="space-y-4" data-testid="appearance">
  <p class="max-w-2xl text-sm text-muted-foreground">The theme of this web UI, kept in this browser. The chat stays dark, like a terminal.</p>
  <div class="grid max-w-3xl gap-4 sm:grid-cols-3" role="radiogroup" aria-label="theme" data-testid="theme-switch">
    {#each THEMES as t (t.id)}
      {#snippet picture()}
        {#if t.id === "system"}
          <div class="absolute inset-0">{@render mock(false)}</div>
          <div class="absolute inset-0 [clip-path:polygon(100%_0,100%_100%,0_100%)]">{@render mock(true)}</div>
        {:else}
          {@render mock(t.id === "dark")}
        {/if}
      {/snippet}
      {@render choice(theme.choice === t.id, t.label, t.hint, t.icon, picture, () => theme.set(t.id), `theme-${t.id}`)}
    {/each}
  </div>
</section>

<section class="mt-10 space-y-4" data-testid="menu-look">
  <h2 class="text-sm font-semibold">Menu</h2>
  <p class="max-w-2xl text-sm text-muted-foreground">How the menu on the left looks, in this browser.</p>
  <div class="grid max-w-3xl gap-4 sm:grid-cols-3" role="radiogroup" aria-label="menu look" data-testid="menu-look-switch">
    {#each LOOKS as l (l.id)}
      {#snippet picture()}{@render menuMock(l.id === "liquid")}{/snippet}
      {@render choice(theme.menu === l.id, l.label, l.hint, l.icon, picture, () => theme.setMenu(l.id), `menu-${l.id}`)}
    {/each}
  </div>
</section>
