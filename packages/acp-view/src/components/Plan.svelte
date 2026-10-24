<script lang="ts">
  // The agent's current plan, kept in view above the prompt while it has steps left: folded to
  // its count and the step in progress, opened to every step.
  import type { PlanEntry } from "@agentclientprotocol/sdk";

  let { entries }: { entries: PlanEntry[] } = $props();

  let open = $state(false);
  const done = $derived(entries.filter((e) => e.status === "completed").length);
  const current = $derived(entries.find((e) => e.status === "in_progress") ?? entries.find((e) => e.status === "pending"));
</script>

<div class="plan" data-testid="live-plan">
  <button type="button" class="head" onclick={() => (open = !open)} aria-expanded={open}>
    <span class="glyph" aria-hidden="true">☰</span>
    <span class="label">plan</span>
    <span class="count tabular-nums">{done}/{entries.length}</span>
    {#if current && !open}<span class="current">{current.content}</span>{/if}
    <span class="chevron" aria-hidden="true">{open ? "▾" : "▸"}</span>
  </button>
  {#if open}
    <ul>
      {#each entries as item, i (i)}
        <li class={item.status}>
          <span class="mark" aria-hidden="true">{item.status === "completed" ? "✓" : item.status === "in_progress" ? "◐" : "○"}</span>
          <span class="sr-only">{item.status.replaceAll("_", " ")}:</span>
          {item.content}
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .plan {
    border-top: 1px solid var(--border);
    padding: 0.35rem 1rem;
    background: var(--card);
  }
  .head {
    display: flex;
    align-items: baseline;
    gap: 1ch;
    width: 100%;
    min-width: 0;
    padding: 0;
    border: none;
    background: none;
    font: inherit;
    text-align: left;
  }
  .glyph,
  .label {
    color: var(--muted-foreground);
  }
  .count {
    color: var(--muted-foreground);
    flex: none;
  }
  .current {
    font-weight: 700;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }
  .chevron {
    margin-left: auto;
    color: var(--muted-foreground);
    flex: none;
  }
  ul {
    list-style: none;
    margin: 0.25rem 0 0.15rem;
    padding: 0 0 0 2.5ch;
    max-height: 12lh;
    overflow-y: auto;
  }
  .mark {
    display: inline-block;
    width: 2ch;
    color: var(--muted-foreground);
  }
  li.completed {
    color: var(--muted-foreground);
  }
  li.completed .mark {
    color: var(--ok);
  }
  li.in_progress {
    font-weight: 700;
  }
</style>
