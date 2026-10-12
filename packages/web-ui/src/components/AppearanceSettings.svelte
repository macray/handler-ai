<script lang="ts">
  // Settings → Appearance: light, dark or like the system, for this browser (lib/theme.svelte.ts).
  import Monitor from "@lucide/svelte/icons/monitor";
  import Moon from "@lucide/svelte/icons/moon";
  import Sun from "@lucide/svelte/icons/sun";
  import { theme, type ThemeChoice } from "../lib/theme.svelte";

  const THEMES: { id: ThemeChoice; label: string; hint: string; icon: typeof Sun }[] = [
    { id: "system", label: "System", hint: "Light or dark like this computer", icon: Monitor },
    { id: "light", label: "Light", hint: "Always light", icon: Sun },
    { id: "dark", label: "Dark", hint: "Always dark", icon: Moon },
  ];
</script>

<section class="space-y-4" data-testid="appearance">
  <p class="max-w-2xl text-sm text-muted-foreground">
    The theme of this web UI, kept in this browser. The chat stays dark, like a terminal.
  </p>
  <div class="grid max-w-2xl gap-3 sm:grid-cols-3" role="radiogroup" aria-label="theme" data-testid="theme-switch">
    {#each THEMES as t (t.id)}
      {@const Icon = t.icon}
      <button
        type="button"
        role="radio"
        aria-checked={theme.choice === t.id}
        class="flex cursor-pointer flex-col items-start gap-2 rounded-lg border bg-card p-4 text-left shadow-xs transition-colors {theme.choice === t.id
          ? 'border-primary ring-1 ring-primary'
          : 'hover:bg-muted'}"
        onclick={() => theme.set(t.id)}
        data-testid={`theme-${t.id}`}
      >
        <Icon class="size-5 {theme.choice === t.id ? 'text-primary' : 'text-muted-foreground'}" />
        <span class="text-sm font-medium">{t.label}</span>
        <span class="text-xs text-muted-foreground">{t.hint}</span>
      </button>
    {/each}
  </div>
</section>
