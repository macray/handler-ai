<script lang="ts">
  import { imageSrc, markdown } from "../lib/render";
  import { blockText, type ToolEntry } from "../lib/session.svelte";
  import Diff from "./Diff.svelte";

  let { tool }: { tool: ToolEntry } = $props();

  const verbs: Record<string, string> = {
    read: "Read", edit: "Edit", delete: "Delete", move: "Move", search: "Search", execute: "Bash", think: "Think", fetch: "Fetch",
  };
  let open = $state(false);
</script>

<div class="tool {tool.status}">
  <button type="button" class="line head" onclick={() => (open = !open)} aria-expanded={open}>
    <span class="gutter" aria-hidden="true">⏺</span>
    <span class="summary">
      <span class="verb">{verbs[tool.toolKind ?? ""] ?? "Tool"}</span>
      <span class="title">{tool.title}</span>
      {#if tool.status !== "completed"}<span class="status {tool.status}">{tool.status.replaceAll("_", " ")}</span>{/if}
      <span class="chevron" aria-hidden="true">{open ? "▾" : "▸"}</span>
    </span>
  </button>
  {#if open}
    <div class="line body">
      <span class="gutter elbow" aria-hidden="true">⎿</span>
      <div class="content">
        {#each tool.locations as loc (loc.path + (loc.line ?? ""))}
          <div class="loc">{loc.path}{loc.line ? `:${loc.line}` : ""}</div>
        {/each}
        {#each tool.content as item, i (i)}
          {#if item.type === "diff"}
            <Diff path={item.path} oldText={item.oldText} newText={item.newText} />
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
  }
  .status::before {
    content: "";
    width: 0.45em;
    height: 0.45em;
    border-radius: 50%;
    background: var(--warn);
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
    color: var(--warn);
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
  .verb {
    font-weight: 700;
    flex: none;
  }
  .title {
    color: var(--muted-foreground);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }
  .chevron {
    color: var(--muted-foreground);
    margin-left: auto;
    flex: none;
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
