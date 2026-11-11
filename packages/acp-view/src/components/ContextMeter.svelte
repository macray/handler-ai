<script lang="ts">
  // How full the agent's context is, as its harness last said (ACP `usage_update`): a chip with a
  // bar, neutral (amber in the session is only for what waits or weakens the sandbox). Nothing
  // when the harness never said (not every one does).
  import { contextFill } from "../lib/session.svelte";

  let { usage }: { usage: { used: number; size: number } | null } = $props();

  const fill = $derived(usage ? contextFill(usage) : null);
</script>

{#if fill}
  <span class="meter" title={fill.full} data-testid="context-meter">
    <span class="name">context</span>
    {#if fill.percent !== null}<span class="bar" aria-hidden="true"><span style:width="{fill.percent}%"></span></span>{/if}
    <span class="value tabular-nums">{fill.short}</span>
  </span>
{/if}

<style>
  .meter {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.15rem 0.6rem;
    border: 1px solid var(--border);
    border-radius: 999px;
    color: var(--muted-foreground);
    white-space: nowrap;
  }
  .value {
    color: var(--foreground);
  }
  .bar {
    width: 3rem;
    height: 0.3rem;
    border-radius: 999px;
    background: var(--border);
    overflow: hidden;
  }
  .bar > span {
    display: block;
    height: 100%;
    background: var(--muted-foreground);
  }
</style>
