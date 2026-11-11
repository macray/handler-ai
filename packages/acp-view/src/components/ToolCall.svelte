<script lang="ts">
  // One step of the agent, as Claude Code shows it: `● Verb(argument)`, under it (└) what it gave
  // back. An edit shows its diff at once (its first lines, the rest a click away), a command its
  // last lines, a failure its first line; the whole of it when opened. Paths are relative to the
  // session's folder (`root`); `onopen` shows one of its files (the page's files pane), when the
  // page has one.
  import { imageSrc, markdown } from "../lib/render";
  import { blockText, type ToolEntry } from "../lib/session.svelte";
  import { changeLine, headline, relative, summary, tail } from "../lib/tools";
  import Diff from "./Diff.svelte";

  // `asking`: a permission request for this step waits for an answer (shown under it, or under
  // the timeline)
  let {
    tool,
    root,
    onopen,
    asking = false,
    ended = false,
  }: {
    tool: ToolEntry;
    root?: string | null;
    onopen?: (path: string) => void;
    asking?: boolean;
    ended?: boolean; // its turn ended: pending or in progress, it did not finish
  } = $props();
  const unfinished = $derived(ended && (tool.status === "pending" || tool.status === "in_progress"));

  const DIFF_ROWS = 12; // an edit's lines shown before "… +N lines"
  const OUTPUT_LINES = 4; // a command's last lines shown

  let open = $state(false);
  const head = $derived(headline(tool, root));
  const said = $derived(summary(tool));
  const diffs = $derived(tool.content.flatMap((c) => (c.type === "diff" ? [c] : [])));
  const changed = $derived(changeLine(tool, root));
  const output = $derived(
    tool.status === "completed" && (tool.toolKind === "execute" || tool.toolKind === "search") ? tail(tool, OUTPUT_LINES) : null,
  );
  const diffPaths = $derived(new Set(diffs.map((d) => d.path)));
  // a diff names its file: not said twice
  const locations = $derived(tool.locations.filter((l) => !diffPaths.has(l.path)));
</script>

{#snippet path(full: string, line?: number | null)}
  {@const shown = relative(full, root) + (line ? `:${line}` : "")}
  {#if onopen && root && full.startsWith(root)}
    <button type="button" class="path" onclick={() => onopen(relative(full, root))} title="Show in the files pane">{shown}</button>
  {:else}
    <span class="path">{shown}</span>
  {/if}
{/snippet}

<div class="tool {unfinished ? 'unfinished' : tool.status}" class:asking>
  <button type="button" class="line head" onclick={() => (open = !open)} aria-expanded={open}>
    <span class="gutter" aria-hidden="true">●</span>
    <span class="summary">
      <span class="call"><span class="verb">{head.verb}</span>{#if head.title}<span class="title">({head.title})</span>{/if}</span>
      {#if asking}<span class="status asking" data-testid="tool-asking">waiting for you</span>
      {:else if unfinished}<span class="status unfinished">not finished</span>
      {:else if tool.status !== "completed"}<span class="status {tool.status}">{tool.status.replaceAll("_", " ")}</span>{/if}
      <span class="chevron" aria-hidden="true">{open ? "▾" : "▸"}</span>
    </span>
  </button>
  {#if !open && diffs.length && asking}
    <!-- its question (under it) shows the diff -->
  {:else if !open && diffs.length && tool.status !== "failed"}
    <div class="line said" data-testid="tool-summary">
      <span class="gutter elbow" aria-hidden="true">└</span>
      <div class="changes">
        <span class="said-text">{changed}</span>
        {#each diffs as d, i (i)}
          <Diff path={diffPaths.size > 1 ? d.path : undefined} oldText={d.oldText} newText={d.newText} {root} {onopen} scroll={false} limit={DIFF_ROWS} />
        {/each}
      </div>
    </div>
  {:else if !open && output}
    <div class="line said" data-testid="tool-summary">
      <span class="gutter elbow" aria-hidden="true">└</span>
      <div class="output">
        {#if output.more}<button type="button" class="more" onclick={() => (open = true)}>… +{output.more} line{output.more === 1 ? "" : "s"}</button>{/if}
        <pre>{output.lines.join("\n")}</pre>
      </div>
    </div>
  {:else if !open && said}
    <div class="line said" data-testid="tool-summary">
      <span class="gutter elbow" aria-hidden="true">└</span>
      <span class="said-text">{said}</span>
    </div>
  {/if}
  {#if open}
    <div class="line body">
      <span class="gutter elbow" aria-hidden="true">└</span>
      <div class="content">
        {#each locations as loc (loc.path + (loc.line ?? ""))}
          <div class="loc">{@render path(loc.path, loc.line)}</div>
        {/each}
        {#each tool.content as item, i (i)}
          {#if item.type === "diff"}
            <Diff path={item.path} oldText={item.oldText} newText={item.newText} {root} {onopen} scroll={false} />
          {:else if item.type === "content" && imageSrc(item.content)}
            <img class="shot" src={imageSrc(item.content)} alt="tool output" />
          {:else if item.type === "content"}
            <div class="md">{@html markdown(blockText(item.content))}</div>
          {:else}
            <p class="text-muted-foreground">(terminal output is not shown: terminals run inside the sandbox)</p>
          {/if}
        {:else}
          <p class="text-muted-foreground">no output</p>
        {/each}
      </div>
    </div>
  {/if}
</div>

<style>
  .status {
    display: inline-flex;
    align-items: center;
    gap: 0.35em;
    font-size: 0.8em;
    color: var(--muted-foreground);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 0 0.4em;
    flex: none;
  }
  .status::before {
    content: "";
    width: 0.45em;
    height: 0.45em;
    border-radius: 50%;
    background: var(--muted-foreground);
  }
  .status.asking {
    color: var(--warn);
    border-color: color-mix(in srgb, var(--warn) 50%, transparent);
  }
  .status.asking::before {
    background: var(--warn);
  }
  .asking .gutter:not(.elbow) {
    color: var(--warn) !important;
    animation: none !important;
  }
  .status.failed {
    color: var(--danger);
  }
  .status.failed::before {
    background: var(--danger);
  }
  .head {
    width: 100%;
    text-align: left;
    border: none;
    border-radius: 0;
    padding: 0;
    font: inherit;
  }
  .head:hover .title,
  .head:focus-visible .title {
    color: var(--foreground);
  }
  .gutter {
    font-size: 0.8em;
    color: var(--muted-foreground);
  }
  .completed .gutter:not(.elbow) {
    color: var(--ok);
  }
  .in_progress .gutter:not(.elbow),
  .pending .gutter:not(.elbow) {
    color: var(--foreground);
    animation: blink 1s steps(2, start) infinite;
  }
  .failed .gutter:not(.elbow) {
    color: var(--danger);
  }
  .summary {
    display: flex;
    gap: 1ch;
    align-items: baseline;
    min-width: 0;
  }
  /* Verb(argument): the argument wraps (a command is read whole), up to three lines */
  .call {
    min-width: 0;
    overflow: hidden;
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    overflow-wrap: anywhere;
  }
  .verb {
    font-weight: 700;
  }
  .title {
    color: var(--muted-foreground);
  }
  .chevron {
    color: var(--muted-foreground);
    margin-left: auto;
    flex: none;
  }
  .said {
    color: var(--muted-foreground);
  }
  .said-text {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }
  .changes {
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
    min-width: 0;
  }
  .changes .said-text {
    white-space: normal;
    overflow-wrap: anywhere;
  }
  .output {
    min-width: 0;
  }
  .output pre {
    margin: 0;
    font: inherit;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .more {
    font: inherit;
    padding: 0;
    border: none;
    background: none;
    color: var(--muted-foreground);
    opacity: 0.8;
  }
  .more:hover {
    color: var(--foreground);
  }
  .failed .said {
    color: var(--danger);
  }
  .body {
    margin-top: 0.2rem;
  }
  .elbow {
    text-align: right;
  }
  .shot {
    max-width: 100%;
    max-height: 32rem;
    border: 1px solid var(--border);
    border-radius: 0.25rem;
  }
  .content {
    min-width: 0;
  }
  .content p {
    margin: 0;
  }
  .loc {
    color: var(--muted-foreground);
    font-size: 0.9em;
  }
  .path {
    font: inherit;
    color: inherit;
    padding: 0;
    border: none;
    background: none;
    text-align: left;
    overflow-wrap: anywhere;
  }
  button.path:hover {
    color: var(--foreground);
    text-decoration: underline;
  }
  .md :global(pre) {
    max-height: 20rem;
    overflow: auto;
  }
  @keyframes blink {
    to {
      visibility: hidden;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .gutter {
      animation: none !important;
    }
  }
</style>
