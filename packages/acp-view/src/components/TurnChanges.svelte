<script lang="ts">
  // What a turn changed, file by file (from its steps' diffs): a row per file (A: added, M:
  // modified, its lines added and removed), the chosen file's diffs under the list, in the order
  // the steps made them. Opened from the turn's footer.
  import type { turnChanges } from "../lib/tools";
  import { relative } from "../lib/tools";
  import Diff from "./Diff.svelte";

  let {
    changes,
    root,
    onopen,
  }: {
    changes: ReturnType<typeof turnChanges>;
    root?: string | null;
    onopen?: (path: string) => void;
  } = $props();

  let chosen = $state(0);
  const file = $derived(changes[Math.min(chosen, changes.length - 1)]);
</script>

<div class="turn-changes" data-testid="turn-changes">
  <ul class="files">
    {#each changes as c, i (c.path)}
      <li>
        <button type="button" class:on={c === file} aria-pressed={c === file} onclick={() => (chosen = i)}>
          <span class="kind" class:added={c.created} title={c.created ? "added" : "modified"}>{c.created ? "A" : "M"}</span>
          <span class="name">{relative(c.path, root)}</span>
          <span class="n added">+{c.added}</span>
          <span class="n removed">−{c.removed}</span>
        </button>
      </li>
    {/each}
  </ul>
  {#if file}
    {#each file.diffs as d, i (i)}
      <Diff path={i === 0 ? d.path : undefined} oldText={d.oldText} newText={d.newText} {root} {onopen} scroll={false} limit={40} />
    {/each}
  {/if}
</div>

<style>
  .turn-changes {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    margin-left: 2.5ch;
  }
  .files {
    list-style: none;
    margin: 0;
    padding: 0;
    border: 1px solid var(--border);
    border-radius: 6px;
    overflow: hidden;
  }
  .files li + li {
    border-top: 1px solid var(--border);
  }
  .files button {
    display: grid;
    grid-template-columns: 2ch minmax(0, 1fr) auto auto;
    column-gap: 1.2ch;
    width: 100%;
    padding: 0.15rem 0.7rem;
    border: none;
    border-radius: 0;
    background: none;
    font: inherit;
    font-size: 1em;
    text-align: left;
    color: var(--foreground);
  }
  .files button:hover,
  .files button.on {
    background: var(--user-line, var(--muted));
  }
  .name {
    overflow-wrap: anywhere;
  }
  .kind {
    color: var(--muted-foreground);
  }
  .kind.added,
  .n.added {
    color: var(--ok);
  }
  .n.removed {
    color: var(--danger);
  }
</style>
