<script lang="ts">
  // Renders a SessionState (live session or replayed transcript) as terminal output: one gutter
  // glyph per entry. Agent text is untrusted: it only reaches the DOM through `markdown()`
  // (sanitized). Meant to sit on a `.term-surface`.
  import { imageSrc, markdown } from "../lib/render";
  import type { Snippet } from "svelte";
  import { modelText, startsTurn, type HostDecision, type SessionState } from "../lib/session.svelte";
  import type { PendingPermission } from "../lib/connection.svelte";
  import { duration, turnChanges, turnSummary } from "../lib/tools";
  import ToolCall from "./ToolCall.svelte";
  import HostCard from "./HostCard.svelte";
  import PermissionPrompt from "./PermissionPrompt.svelte";
  import TurnChanges from "./TurnChanges.svelte";

  // `root`: the session's folder, paths are shown relative to it; `onopen`: shows one of its files.
  // `pinPlan`: the page keeps the current plan in view (Plan.svelte), so its updates here are one
  // line each, opened to see that version. `busy`: a turn is in progress (it has no footer yet).
  // `ondecide`: answers a host the network filter refused (F.9); without it, its card says where to.
  // `providers`: where the person tests the providers (a model that does not answer points there).
  // `permissions`: the requests waiting for an answer, each shown under its step (a page that
  // passes them pins only those whose step is not in the timeline: `askedAtStep`).
  let {
    session,
    root,
    onopen,
    pinPlan = false,
    busy = false,
    asking = [],
    permissions,
    empty,
    first,
    ondecide,
    providers,
  }: {
    session: SessionState;
    root?: string | null;
    onopen?: (path: string) => void;
    pinPlan?: boolean;
    busy?: boolean;
    asking?: string[]; // the steps whose permission requests wait for an answer
    permissions?: PendingPermission[];
    empty?: Snippet; // shown while there is nothing yet (the page's start)
    first?: Snippet; // shown in place of the first user message: what the page started it with
    ondecide?: (host: string, decision: HostDecision) => Promise<void>;
    providers?: string;
  } = $props();
  const firstUser = $derived(first ? session.entries.findIndex((e) => e.kind === "user") : -1);

  // Copy: a message's text, a code block's
  let copied = $state<number | null>(null);
  async function copy(text: string, i: number): Promise<void> {
    await navigator.clipboard.writeText(text);
    copied = i;
    setTimeout(() => copied === i && (copied = null), 1200);
  }

  /** A Copy button on each code block of rendered markdown, again on each re-render (streamed). */
  function codeCopy(text: string) {
    return (el: HTMLElement) => {
      void text;
      for (const pre of el.querySelectorAll("pre")) {
        if (pre.querySelector(":scope > .copy")) continue;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "copy";
        button.textContent = "Copy";
        button.onclick = async () => {
          await navigator.clipboard.writeText(pre.querySelector("code")?.textContent ?? "");
          button.textContent = "Copied";
          setTimeout(() => (button.textContent = "Copy"), 1200);
        };
        pre.append(button);
      }
    };
  }

  // Each turn's footer, at the index of its last entry: what it did and how long it took, and
  // the files it changed (opened under it).
  const footers = $derived.by(() => {
    const said = new Map<number, { text: string; changes: ReturnType<typeof turnChanges> }>();
    const entries = session.entries;
    let start = -1;
    for (let i = 0; i <= entries.length; i++) {
      const e = entries[i];
      if (i < entries.length && !startsTurn(e)) continue;
      if (start >= 0 && i - 1 > start && (i < entries.length || !busy)) {
        const prompt = entries[start];
        const turn = entries.slice(start + 1, i);
        const text = turnSummary(turn, prompt?.kind === "user" || prompt?.kind === "told" ? prompt.ms : undefined);
        if (text) said.set(i - 1, { text, changes: turnChanges(turn) });
      }
      start = i;
    }
    return said;
  });

  let reviewing = $state(new Set<number>()); // the turns whose changes are open

  // where the last turn starts: a refused host before it is an earlier turn's
  const lastTurn = $derived(session.entries.findLastIndex(startsTurn));
  // where the turn in progress starts: a step before it that did not finish never will
  const current = $derived(busy ? session.entries.findLastIndex(startsTurn) : session.entries.length);

  function mark(status: string): string {
    return status === "completed" ? "✓" : status === "in_progress" ? "◐" : "○";
  }

  /** The last turn did not end normally: said at the end, also to who was away (a phone asleep). */
  function stopped(reason: string): string {
    const said: Record<string, string> = {
      cancelled: "Interrupted. Send a message to go on.",
      max_tokens: "Stopped: the answer reached the model's length limit.",
      max_turn_requests: "Stopped: too many steps in one turn.",
      refusal: "The model refused to go on.",
    };
    return said[reason] ?? `The turn ended: ${reason.replaceAll("_", " ")}.`;
  }
</script>

<div class="timeline" data-testid="timeline">
  {#each session.entries as entry, i (i)}
    {#if i === firstUser && first}
      {@render first()}
    {:else if entry.kind === "user"}
      <div class="line user">
        <span class="gutter" aria-hidden="true">&gt;</span>
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
        <span class="gutter" aria-hidden="true">●</span>
        <div class="text md" data-testid="agent-message" {@attach codeCopy(entry.text)}>{@html markdown(entry.text)}</div>
        {#if !(busy && i === session.entries.length - 1)}
          <button type="button" class="copy message-copy" onclick={() => copy(entry.text, i)} title="Copy this message (markdown)">
            {copied === i ? "Copied" : "Copy"}
          </button>
        {/if}
      </div>
    {:else if entry.kind === "thought"}
      <details class="thought">
        <summary class="line"
          ><span class="gutter" aria-hidden="true">✻</span><span
            >{busy && i === session.entries.length - 1
              ? "thinking…"
              : entry.ms !== undefined && entry.ms >= 1000
                ? `thought for ${duration(entry.ms)}`
                : "thought"}</span
          ></summary
        >
        <div class="line"><span class="gutter"></span><div class="text">{entry.text}</div></div>
      </details>
    {:else if entry.kind === "tool"}
      <ToolCall tool={entry} {root} {onopen} asking={asking.includes(entry.id)} ended={i < current} />
      {#each permissions?.filter((p) => p.request.toolCall.toolCallId === entry.id) ?? [] as pending (pending)}
        <div class="asked"><PermissionPrompt {pending} {root} /></div>
      {/each}
    {:else if entry.kind === "plan"}
      {@const done = entry.entries.filter((e) => e.status === "completed").length}
      {#snippet steps()}
        <ul>
          {#each entry.entries as item, j (j)}
            <li class={item.status}><span class="mark" aria-hidden="true">{mark(item.status)}</span><span class="sr-only">{item.status.replaceAll("_", " ")}:</span> {item.content}</li>
          {/each}
        </ul>
      {/snippet}
      {#if pinPlan}
        <details class="plan folded">
          <summary class="line"><span class="gutter" aria-hidden="true">☰</span><span class="label">plan {done < entry.entries.length ? "updated" : "done"} · <span class="tabular-nums">{done}/{entry.entries.length}</span></span></summary>
          <div class="line"><span class="gutter"></span>{@render steps()}</div>
        </details>
      {:else}
        <div class="line plan">
          <span class="gutter" aria-hidden="true">☰</span>
          <div>
            <div class="label">plan</div>
            {@render steps()}
          </div>
        </div>
      {/if}
    {:else if entry.kind === "host"}
      <HostCard {entry} past={i < lastTurn} {ondecide} />
    {:else if entry.kind === "model"}
      <div class="line notice warning" data-testid="model-unreached">
        <span class="gutter" aria-hidden="true">!</span>
        <div class="text">
          <span class="who">Handler:</span> {modelText(entry)}
          {#if providers && entry.provider}<a href={providers} data-testid="model-unreached-test">Test {entry.provider} in Settings → Model access</a>{:else if entry.provider}Test {entry.provider} in Settings → Model access.{/if}
        </div>
      </div>
    {:else if entry.kind === "told"}
      <div class="line told" data-testid="handler-told">
        <span class="gutter" aria-hidden="true">↳</span>
        <div class="text"><span class="who">Handler told the agent:</span> {entry.text.replace(/^Handler: /, "")}</div>
      </div>
    {:else}
      <div class="line notice {entry.severity ?? 'info'}">
        <span class="gutter" aria-hidden="true">{entry.severity === "warning" || entry.severity === "error" ? "!" : "·"}</span>
        <div class="text">{entry.text}</div>
      </div>
    {/if}
    {@const footer = footers.get(i)}
    {#if footer}
      {#if footer.changes.length}
        {@const open = reviewing.has(i)}
        <button
          type="button"
          class="turn-end"
          aria-expanded={open}
          title="What this turn changed, file by file"
          onclick={() => (reviewing = open ? new Set([...reviewing].filter((n) => n !== i)) : new Set([...reviewing, i]))}
          data-testid="turn-summary">{footer.text} {open ? "▾" : "▸"}</button
        >
        {#if open}<TurnChanges changes={footer.changes} {root} {onopen} />{/if}
      {:else}
        <div class="turn-end" data-testid="turn-summary">{footer.text}</div>
      {/if}
    {/if}
  {:else}
    {#if empty}{@render empty()}{:else}<p class="text-muted-foreground">Nothing yet.</p>{/if}
  {/each}
  {#if session.lastStop}
    <div class="line notice warning" data-testid="turn-stopped">
      <span class="gutter" aria-hidden="true">■</span>
      <div class="text">{stopped(session.lastStop)}</div>
    </div>
  {/if}
</div>

<style>
  .timeline {
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }
  /* what the agent adds comes in, not pops in */
  .timeline > :global(*) {
    animation: enter var(--dur-2) var(--ease) backwards;
  }
  /* steps one after the other read as one block; a turn starts with some room */
  .timeline > :global(.tool + .tool) {
    margin-top: -0.3rem;
  }
  .timeline > .user {
    margin-top: 0.9rem;
  }
  .timeline > .user:first-child {
    margin-top: 0;
  }
  /* everything in the terminal's one face, as in Claude Code: weight and the gutter's glyphs
     make the difference between your words, the agent's and its steps */
  .user .text,
  .agent .text {
    line-height: 1.6;
  }
  .agent {
    position: relative;
  }
  .message-copy {
    position: absolute;
    top: -0.2rem;
    right: 0;
    opacity: 0;
  }
  .agent:hover .message-copy,
  .message-copy:focus-visible {
    opacity: 1;
  }
  /* a code block's own Copy is in the same corner: the message's goes below it, or away when
     the message is that block only (the block's Copy gives its code) */
  .agent:has(.md > :global(pre:first-child)) .message-copy {
    top: auto;
    bottom: -0.2rem;
  }
  .agent:has(.md > :global(pre:only-child)) .message-copy {
    display: none;
  }
  .timeline :global(.copy) {
    padding: 0 0.5rem;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--card);
    color: var(--muted-foreground);
    font-family: var(--mono);
    font-size: 12px;
  }
  .timeline :global(.copy:hover) {
    color: var(--foreground);
  }
  .agent :global(pre) {
    position: relative;
  }
  .agent :global(pre > .copy) {
    position: absolute;
    top: 0.4rem;
    right: 0.4rem;
    opacity: 0;
  }
  .agent :global(pre:hover > .copy),
  .agent :global(pre > .copy:focus-visible) {
    opacity: 1;
  }
  @media (pointer: coarse) {
    .message-copy,
    .agent :global(pre > .copy) {
      opacity: 1;
    }
    .message-copy {
      position: static;
      grid-column: 2;
      justify-self: start;
      margin-top: 0.3rem;
      min-height: 2.25rem;
    }
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
    padding: 0.35rem 0.6rem;
    border-radius: 4px;
  }
  .user .gutter {
    color: var(--muted-foreground);
  }
  .user .text {
    white-space: pre-wrap;
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
    font-weight: 700;
    color: var(--foreground);
    margin: 0.8rem 0 0.3rem;
  }
  .agent :global(:not(pre) > code) {
    color: var(--code-fg, var(--foreground));
    background: var(--muted);
    border-radius: 3px;
    padding: 0 0.3ch;
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
    color: var(--muted-foreground);
  }
  .plan ul {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  .plan li.completed {
    color: var(--muted-foreground);
  }
  .plan .mark {
    display: inline-block;
    width: 2ch;
  }
  .plan li.completed .mark {
    color: var(--ok);
  }
  .plan.folded summary {
    cursor: pointer;
    list-style: none;
    color: var(--muted-foreground);
  }
  .plan.folded summary::-webkit-details-marker {
    display: none;
  }
  .plan.folded .label {
    color: var(--muted-foreground);
  }
  .turn-end {
    display: flex;
    align-items: center;
    gap: 1ch;
    color: var(--muted-foreground);
    font-size: 0.9em;
  }
  button.turn-end {
    width: 100%;
    padding: 0;
    border: none;
    background: none;
    font-family: inherit;
    text-align: left;
  }
  button.turn-end:hover {
    color: var(--foreground);
  }
  /* a question under its step: square on its coloured edge (the card's own) */
  .asked {
    margin-left: 2.5ch;
  }
  .turn-end::before,
  .turn-end::after {
    content: "";
    flex: 1;
    border-top: 1px solid var(--border);
  }
  .turn-end::before {
    flex: 0 0 2ch;
  }
  .plan li.in_progress {
    color: var(--foreground);
    font-weight: 700;
  }
  .notice {
    color: var(--muted-foreground);
  }
  .told {
    color: var(--muted-foreground);
  }
  .told .who {
    font-weight: 600;
  }
  .notice.warning,
  .notice.error {
    color: var(--warn);
  }
  .notice .who {
    font-weight: 600;
  }
  .notice a {
    text-decoration: underline;
  }
</style>
