<script lang="ts">
  // Settings → Appearance: light, dark or like the phone, kept in this browser (lib/theme.svelte.ts),
  // the desktop's three choices and words. Each is drawn as a small phone in it (the system's: half
  // light, half dark); a tap applies it. A session stays dark, like a terminal, whichever.
  import { theme, type ThemeChoice } from "../lib/theme.svelte";
  import PageHeader from "./PageHeader.svelte";

  let { onback }: { onback: () => void } = $props();

  const THEMES: { id: ThemeChoice; label: string; hint: string }[] = [
    { id: "system", label: "System", hint: "Light or dark like this phone" },
    { id: "light", label: "Light", hint: "Always light" },
    { id: "dark", label: "Dark", hint: "Always dark" },
  ];
</script>

<!-- a small phone in a theme: a title, two cards, the accent, the tabs' line -->
{#snippet screen(dark: boolean, half = false)}
  <span class="mock" class:dark-mock={dark} class:half aria-hidden="true">
    <i class="t"></i><i></i><i></i>{#if !half}<em></em>{/if}<b></b>
  </span>
{/snippet}

<PageHeader title="Appearance" back="Settings" {onback} />

<main class="page" data-testid="appearance">
  <p class="lede">The theme of Handler on this phone, kept in this browser. Sessions stay dark, like a terminal.</p>
  <div class="choices" role="radiogroup" aria-label="theme" data-testid="theme-switch">
    {#each THEMES as t (t.id)}
      <button
        type="button"
        role="radio"
        class="choice"
        aria-checked={theme.choice === t.id}
        onclick={() => theme.set(t.id)}
        data-testid="theme-{t.id}"
      >
        <span class="phone">
          {#if t.id === "system"}{@render screen(false, true)}{@render screen(true, true)}{:else}{@render screen(t.id === "dark")}{/if}
        </span>
        <span class="label">
          {#if theme.choice === t.id}
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6 9 17l-5-5" /></svg>
          {/if}{t.label}
        </span>
        <span class="hint">{t.hint}</span>
      </button>
    {/each}
  </div>
</main>

<style>
  .page {
    flex: 1;
    overflow-y: auto;
    padding: 0.9rem 0.75rem;
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }
  .lede {
    font-size: 0.85em;
    color: var(--muted-foreground);
    padding: 0 0.25rem;
  }
  .choices {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 0.5rem;
  }
  /* the chosen one: a soft tint behind it and its name in the accent, with a check (no ring) */
  .choice {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.35rem;
    padding: 0.6rem 0.25rem 0.7rem;
    border-radius: 14px;
    font-size: 1em;
    color: inherit;
    transition: background var(--dur-1) var(--ease);
  }
  .choice[aria-checked="true"] {
    background: var(--accent-soft);
  }
  .phone {
    position: relative;
    width: 84px;
    height: 150px;
    border-radius: 16px;
    overflow: hidden;
    border: 1px solid var(--border);
  }
  .label {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    font: 600 0.85rem var(--mono);
  }
  .choice[aria-checked="true"] .label {
    color: var(--primary);
  }
  .label svg {
    width: 14px;
    height: 14px;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .hint {
    font-size: 0.72rem;
    line-height: 1.3;
    text-align: center;
    color: var(--muted-foreground);
  }
  /* the pictures keep their own colours: they show a theme, whichever is on */
  .mock {
    position: absolute;
    inset: 0;
    padding: 14px 8px;
    display: flex;
    flex-direction: column;
    gap: 5px;
    background: #f8f6f2;
  }
  .mock.dark-mock {
    background: #1a1917;
  }
  .mock.half.dark-mock {
    clip-path: polygon(100% 0, 100% 100%, 0 100%);
  }
  .mock i {
    display: block;
    height: 22px;
    border-radius: 5px;
    background: #fff;
    border: 1px solid #e6e1da;
  }
  .dark-mock i {
    background: #262421;
    border-color: #2e2c29;
  }
  .mock i.t {
    height: 6px;
    width: 55%;
    border: 0;
    margin-bottom: 3px;
    background: #1c1a17;
  }
  .dark-mock i.t {
    background: #ece9e4;
  }
  .mock em {
    display: block;
    width: 40%;
    height: 7px;
    border-radius: 4px;
    background: #c2410c;
  }
  .dark-mock em {
    background: #f26b21;
  }
  .mock b {
    display: block;
    height: 12px;
    margin-top: auto;
    border-top: 1px solid #e6e1da;
  }
  .dark-mock b {
    border-color: #2e2c29;
  }
</style>
