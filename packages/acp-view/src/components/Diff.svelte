<script lang="ts">
  // A file's change, unified: a line number, + or −, the line (its changed words marked), the
  // unchanged runs folded around each change (opened by a click). `path`: a header naming the file
  // (relative to `root`, which `onopen` shows) with what changed; none when the page names it.
  import { counts, lines, rows, type Line } from "../lib/diff";
  import { relative } from "../lib/tools";

  let {
    path,
    oldText,
    newText,
    root,
    onopen,
    scroll = true,
  }: {
    path?: string;
    oldText?: string | null;
    newText: string;
    root?: string | null;
    onopen?: (path: string) => void;
    scroll?: boolean; // in a box of its own height (in the conversation); false: the page scrolls
  } = $props();

  const all = $derived(lines(oldText, newText));
  const shown = $derived(rows(all));
  const n = $derived(counts(all));
  const digits = $derived(String(Math.max(1, ...all.map((l) => l.n))).length);
  let opened = $state(new Set<number>());
</script>

{#snippet line(l: Line)}
  <div class="row {l.kind}">
    <span class="num" aria-hidden="true">{l.n}</span>
    <span class="sign" aria-hidden="true">{l.kind === "add" ? "+" : l.kind === "del" ? "−" : ""}</span>
    <span class="code"
      >{#if l.kind !== "same"}<span class="sr-only">{l.kind === "add" ? "added: " : "removed: "}</span>{/if}{#if l.words}{#each l.words as w, i (i)}{#if w.changed}<mark
            >{w.text}</mark
          >{:else}{w.text}{/if}{/each}{:else}{l.text || " "}{/if}</span
    >
  </div>
{/snippet}

<div class="diff" data-testid="diff">
  {#if path}
    <div class="path">
      {#if oldText == null}<span class="tag">new file</span>{/if}
      {#if onopen && root && path.startsWith(root)}
        <button type="button" onclick={() => onopen(relative(path, root))} title="Show in the files pane">{relative(path, root)}</button>
      {:else}
        <span>{relative(path, root)}</span>
      {/if}
      <span class="counts tabular-nums"><span class="added">+{n.added}</span> <span class="removed">−{n.removed}</span></span>
    </div>
  {/if}
  <div class="lines" class:scroll style:--digits="{digits}ch">
    {#each shown as row, i (i)}
      {#if row.kind !== "fold"}
        {@render line(row)}
      {:else if opened.has(row.id)}
        {#each row.lines as l (l.n)}{@render line(l)}{/each}
      {:else}
        <button type="button" class="fold" onclick={() => (opened = new Set([...opened, row.id]))}>
          ⋯ {row.lines.length} unchanged line{row.lines.length === 1 ? "" : "s"}
        </button>
      {/if}
    {/each}
  </div>
</div>

<style>
  .diff {
    font-family: var(--mono);
    min-width: 0;
  }
  .path {
    display: flex;
    align-items: baseline;
    gap: 1ch;
    font-size: 0.85em;
    color: var(--muted-foreground);
    margin-bottom: 0.25rem;
    min-width: 0;
  }
  .path button {
    font: inherit;
    color: inherit;
    padding: 0;
    border: none;
    background: none;
    overflow-wrap: anywhere;
    text-align: left;
  }
  .path button:hover {
    color: var(--foreground);
    text-decoration: underline;
  }
  .tag {
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 0 0.4em;
    flex: none;
  }
  .counts {
    margin-left: auto;
    flex: none;
  }
  .added {
    color: var(--ok);
  }
  .removed {
    color: var(--danger);
  }
  .lines {
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--code-bg);
    padding: 0.25rem 0;
    overflow-x: auto;
  }
  .lines.scroll {
    max-height: 24rem;
    overflow-y: auto;
  }
  .row {
    display: grid;
    grid-template-columns: calc(var(--digits) + 1.2ch) 2ch minmax(0, 1fr);
    line-height: 1.5;
  }
  .num {
    text-align: right;
    padding-right: 1ch;
    color: var(--muted-foreground);
    opacity: 0.7;
    user-select: none;
  }
  .sign {
    text-align: center;
    user-select: none;
  }
  .code {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    padding-right: 0.75ch;
  }
  .add {
    background: var(--diff-add);
  }
  .add .sign {
    color: var(--ok);
  }
  .del {
    background: var(--diff-del);
  }
  .del .sign {
    color: var(--danger);
  }
  mark {
    color: inherit;
    border-radius: 2px;
  }
  .add mark {
    background: color-mix(in srgb, var(--ok) 30%, transparent);
  }
  .del mark {
    background: color-mix(in srgb, var(--danger) 30%, transparent);
  }
  .fold {
    display: block;
    width: 100%;
    text-align: left;
    padding: 0.1rem 0 0.1rem calc(var(--digits) + 3.2ch);
    border: none;
    border-radius: 0;
    background: color-mix(in srgb, var(--muted-foreground) 8%, transparent);
    color: var(--muted-foreground);
    font: inherit;
  }
  .fold:hover {
    color: var(--foreground);
  }
</style>
