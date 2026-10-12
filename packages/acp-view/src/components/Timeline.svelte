<script lang="ts">
  // Renders a SessionState (live session or replayed transcript) as terminal output: one gutter
  // glyph per entry. Agent text is untrusted: it only reaches the DOM through `markdown()`
  // (sanitized). Meant to sit on a `.term-surface`.
  import { imageSrc, markdown } from "../lib/render";
  import type { SessionState } from "../lib/session.svelte";
  import ToolCall from "./ToolCall.svelte";

  let { session }: { session: SessionState } = $props();
</script>

<div class="timeline" data-testid="timeline">
  {#each session.entries as entry, i (i)}
    {#if entry.kind === "user"}
      <div class="line user">
        <span class="gutter" aria-hidden="true">❯</span>
        <div class="text" data-testid="user-message">
          {#if entry.images.length}
            <div class="shots">
              {#each entry.images as image, n (n)}
                {@const src = imageSrc({ type: "image", ...image })}
                {#if src}<img {src} alt="attached image {n + 1}" data-testid="user-image" />{:else}<span class="text-muted-foreground">({image.mimeType})</span>{/if}
              {/each}
            </div>
          {/if}
          {entry.text}
        </div>
      </div>
    {:else if entry.kind === "agent"}
      <div class="line agent">
        <span class="gutter" aria-hidden="true">⏺</span>
        <div class="text md" data-testid="agent-message">{@html markdown(entry.text)}</div>
      </div>
    {:else if entry.kind === "thought"}
      <details class="thought">
        <summary class="line"><span class="gutter" aria-hidden="true">✻</span><span>thinking…</span></summary>
        <div class="line"><span class="gutter"></span><div class="text">{entry.text}</div></div>
      </details>
    {:else if entry.kind === "tool"}
      <ToolCall tool={entry} />
    {:else if entry.kind === "plan"}
      <div class="line plan">
        <span class="gutter" aria-hidden="true">☰</span>
        <div>
          <div class="label">plan</div>
          <ul>
            {#each entry.entries as item, j (j)}
              <li class={item.status}>{item.status === "completed" ? "☑" : item.status === "in_progress" ? "◐" : "☐"} {item.content}</li>
            {/each}
          </ul>
        </div>
      </div>
    {:else}
      <div class="line notice {entry.severity ?? 'info'}">
        <span class="gutter" aria-hidden="true">{entry.severity === "warning" || entry.severity === "error" ? "!" : "·"}</span>
        <div class="text">{entry.text}</div>
      </div>
    {/if}
  {:else}
    <p class="text-muted-foreground">Nothing yet.</p>
  {/each}
</div>

<style>
  .timeline {
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }
  .timeline :global(.line) {
    display: grid;
    grid-template-columns: 2ch minmax(0, 1fr);
    column-gap: 0.5ch;
    align-items: baseline;
  }
  .text {
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .user {
    background: var(--user-line);
    border-left: 2px solid var(--prompt);
    margin: 0.4rem 0 0.1rem;
    padding: 0.35rem 0.6rem 0.35rem calc(0.6rem - 2px);
    border-radius: 0 4px 4px 0;
  }
  .user .gutter {
    color: var(--prompt);
    font-weight: 700;
  }
  .user .text {
    white-space: pre-wrap;
    font-weight: 600;
  }
  .user:has(.shots) {
    align-items: start; /* the glyph at the top, not at the images' baseline */
  }
  .shots {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    margin-bottom: 0.3rem;
  }
  .shots img {
    max-height: 10rem;
    max-width: 100%;
    border: 1px solid var(--border);
    border-radius: 4px;
  }
  .agent .gutter {
    color: var(--foreground);
    font-size: 0.8em;
  }
  .agent :global(p:first-child) {
    margin-top: 0;
  }
  .agent :global(p:last-child) {
    margin-bottom: 0;
  }
  .agent :global(h1),
  .agent :global(h2),
  .agent :global(h3) {
    font-size: 1em;
    color: var(--link);
    margin: 0.8rem 0 0.3rem;
  }
  .agent :global(:not(pre) > code) {
    color: var(--warn);
    background: none;
  }
  .agent :global(pre) {
    border: 1px solid var(--border);
    border-radius: 4px;
  }
  .agent :global(a) {
    color: var(--link);
  }
  .thought {
    color: var(--muted-foreground);
    font-style: italic;
  }
  .thought summary {
    cursor: pointer;
    list-style: none;
  }
  .thought summary::-webkit-details-marker {
    display: none;
  }
  .thought .text {
    white-space: pre-wrap;
    border-left: 1px solid var(--border);
    padding-left: 1ch;
    margin-top: 0.2rem;
  }
  .plan .gutter,
  .plan .label {
    color: var(--link);
  }
  .plan ul {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  .plan li.completed {
    color: var(--muted-foreground);
    text-decoration: line-through;
  }
  .plan li.in_progress {
    color: var(--warn);
  }
  .notice {
    color: var(--muted-foreground);
  }
  .notice.warning,
  .notice.error {
    color: var(--warn);
  }
</style>
