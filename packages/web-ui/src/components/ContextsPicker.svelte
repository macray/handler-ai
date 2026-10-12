<script lang="ts">
  // Which project contexts an account or a provider is made for (D.19): some of them, or any (a
  // local model). None: only projects without a context. Shown once there are contexts.
  import { ANY, contexts } from "../lib/contexts.svelte";

  let { value = $bindable([]) }: { value: string[] } = $props();

  void contexts.load();

  function toggle(name: string): void {
    if (name === ANY) value = value.includes(ANY) ? [] : [ANY];
    else value = value.includes(name) ? value.filter((v) => v !== name) : [...value.filter((v) => v !== ANY), name];
  }

  const chip = "rounded-full border px-2 py-0.5 text-xs transition-colors";
</script>

{#if contexts.list.length}
  <div class="flex flex-wrap items-center gap-1.5 text-xs" role="group" aria-label="made for" data-testid="contexts-picker">
    <span class="text-muted-foreground">For</span>
    {#each [...contexts.list.map((c) => c.name), ANY] as name (name)}
      {@const on = value.includes(name)}
      <button
        type="button"
        aria-pressed={on}
        class="{chip} {on ? `ctx-tag ${contexts.colorClass(name)} border-transparent font-semibold` : 'text-muted-foreground hover:border-foreground/30'}"
        onclick={() => toggle(name)}
        data-testid="contexts-picker-option">{name === ANY ? "any context" : name}</button
      >
    {/each}
    {#if !value.length}<span class="text-muted-foreground">· only projects without a context</span>{/if}
  </div>
{/if}
