<script lang="ts">
  // The agent waits for your answer: what it asks to do (the tool call's own title, its files and
  // its diff, never the agent's prose about it; a plan it asks to start from is shown whole, as the
  // agent wrote it), then its options numbered as the harness names them, allow first, kept in view
  // under a long diff; one that is remembered says so. On a keyboard the first answer takes the
  // focus (unless you are typing), ↑ ↓ move between answers and Enter picks one. On a touch screen
  // they are large buttons that take no tap for a moment after they appear or the screen comes
  // back on.
  import type { PermissionOption } from "@agentclientprotocol/sdk";
  import type { PendingPermission } from "../lib/connection.svelte";
  import { markdown } from "../lib/render";
  import { blockText } from "../lib/session.svelte";
  import { SETTLE, settled, touch } from "../lib/touch.svelte";
  import { relative } from "../lib/tools";
  import Diff from "./Diff.svelte";

  let { pending, root }: { pending: PendingPermission; root?: string | null } = $props(); // root: the session's folder
  const settle = settled();

  const tool = $derived(pending.request.toolCall);
  const options = $derived(pending.request.options);
  const answers = $derived([...options.filter((o) => o.kind.startsWith("allow")), ...options.filter((o) => o.kind.startsWith("reject"))]);
  const VERB: Record<string, string> = {
    execute: "run a command",
    edit: "change a file",
    delete: "delete a file",
    move: "move a file",
    fetch: "reach the network",
    read: "read a file",
  };
  const asks = $derived(tool.kind && VERB[tool.kind] ? `to ${VERB[tool.kind]}` : "for permission");
  const diffs = $derived((tool.content ?? []).filter((c) => c.type === "diff"));
  // leaving plan mode: the plan it would start from, in the request's own text
  const plan = $derived(
    tool.kind === "switch_mode"
      ? (tool.content ?? []).flatMap((c) => (c.type === "content" ? [blockText(c.content)] : [])).join("\n\n")
      : "",
  );
  // one file changed: its diff names it and says what changes
  const file = $derived(diffs.length === 1 && diffs[0]?.type === "diff" ? diffs[0].path : null);
  const title = $derived(tool.title ? (root ? tool.title.replaceAll(`${root.replace(/\/$/, "")}/`, "") : tool.title) : tool.toolCallId);
  // a diff names its file: not said twice
  const paths = $derived(
    (tool.locations ?? []).map((l) => l.path).filter((p) => !diffs.some((d) => d.type === "diff" && d.path === p)).map((p) => relative(p, root)),
  );

  function choose(option: PermissionOption): void {
    pending.answer({ outcome: "selected", optionId: option.optionId });
  }

  /** The first answer takes the focus when the question appears, unless you are typing. */
  function focusFirst(list: HTMLElement): void {
    if (touch) return;
    const active = document.activeElement;
    const typing = active instanceof HTMLTextAreaElement || active instanceof HTMLInputElement ? active.value.trim() !== "" : active instanceof HTMLElement && active.isContentEditable;
    if (!typing) list.querySelector("button")?.focus({ preventScroll: true });
  }

  /** ↑ ↓ move between the answers (Enter or Space picks the one focused, as any button). */
  function move(event: KeyboardEvent): void {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const buttons = [...(event.currentTarget as HTMLElement).querySelectorAll("button")];
    const at = buttons.indexOf(document.activeElement as HTMLButtonElement);
    const next = buttons[(at + (event.key === "ArrowDown" ? 1 : buttons.length - 1)) % buttons.length];
    event.preventDefault();
    next?.focus();
  }
</script>

<div class="permission" class:plan role="alertdialog" aria-label="permission request" aria-live="assertive" data-testid="permission-request">
  <div class="head">
    <span class="badge">Needs you</span>
    {#if plan}
      <span>The agent asks to start working from its plan:</span>
    {:else if file}
      <span>The agent asks to change this file:</span>
    {:else}
      <span>The agent asks {asks}:</span>
    {/if}
  </div>
  {#if plan}
    <div class="planbox md" data-testid="permission-plan">{@html markdown(plan)}</div>
  {:else if !file}<pre class="what">{title}</pre>{/if}
  {#if paths.length}<p class="paths">{paths.join(" · ")}</p>{/if}
  {#each diffs as d, i (i)}
    {#if d.type === "diff"}<Diff path={d.path} oldText={d.oldText} newText={d.newText} {root} />{/if}
  {/each}
  <div class="answers" role="toolbar" aria-orientation="vertical" aria-label="answers" tabindex="-1" onkeydown={move} {@attach focusFirst}>
    {#each answers as option, n (option.optionId)}
      {@const always = option.kind.endsWith("always")}
      {@const side = option.kind.startsWith("allow") ? "allow" : "reject"}
      <button
        type="button"
        class="{side} {always ? 'always' : 'once'}"
        class:settling={!settle.ready}
        style:--settle="{SETTLE}ms"
        disabled={!settle.ready}
        onclick={() => choose(option)}
        title={always ? "Remembered: the agent does not ask again for the same thing" : "This time only"}
      >
        <span class="pointer" aria-hidden="true">❯</span><span class="n" aria-hidden="true">{n + 1}.</span>
        <span class="name">{option.name}{#if always}<span class="sub">remembered</span>{/if}</span>
      </button>
    {/each}
  </div>
</div>

<style>
  /* a touch screen's buttons take no tap for a moment: a fill sweeps across them, they are live
     when it ends (it starts again when the screen comes back on) */
  .answers button {
    position: relative;
    overflow: hidden;
  }
  .answers button.settling::after {
    content: "";
    position: absolute;
    inset: auto 0 0 0;
    height: 3px;
    background: currentColor;
    transform-origin: left;
    animation: settle var(--settle) linear forwards;
  }
  @keyframes settle {
    from {
      transform: scaleX(0);
    }
  }
  /* it rises into view: the moment the agent stops for you. Square on its coloured edge (amber:
     it waits for you; teal: a plan to start from), rounded on the others */
  .permission {
    --edge: var(--warn);
    animation: rise var(--dur-3) var(--ease) backwards;
    border: 1px solid var(--border);
    border-left: 2px solid var(--edge);
    border-radius: 0 6px 6px 0;
    padding: 0.6rem 0.9rem 0.7rem;
    display: flex;
    flex-direction: column;
    gap: 0.55rem;
    margin: 0.3rem 0;
    background: var(--user-line, var(--card));
  }
  .permission.plan {
    --edge: var(--mode-plan, var(--warn));
  }
  .head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.6rem;
    font-weight: 700;
  }
  .badge {
    color: var(--edge);
    font-weight: 700;
  }
  .what {
    margin: 0;
    padding: 0.45rem 0.7rem;
    border-radius: 6px;
    background: var(--background);
    border: 1px solid var(--border);
    color: var(--foreground);
    font-weight: 600;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .planbox {
    padding: 0.5rem 0.8rem;
    border-radius: 6px;
    background: var(--background);
    border: 1px solid var(--border);
    overflow-wrap: anywhere;
  }
  .planbox :global(h1),
  .planbox :global(h2),
  .planbox :global(h3) {
    font-size: 1em;
    font-weight: 700;
  }
  .planbox :global(:first-child) {
    margin-top: 0;
  }
  .planbox :global(:not(pre) > code) {
    color: var(--code-fg, var(--foreground));
    background: var(--muted);
    border-radius: 3px;
    padding: 0 0.3ch;
  }
  .paths {
    margin: 0;
    color: var(--muted-foreground);
    overflow-wrap: anywhere;
  }
  /* the answers as Claude Code lists them: numbered rows, the one under the pointer or focus
     marked ❯ */
  .answers {
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
    position: sticky; /* under a long diff, the answers stay in view */
    bottom: 0;
    margin: 0 -0.9rem -0.7rem;
    padding: 0.3rem 0.9rem 0.6rem;
    background: var(--user-line, var(--card));
    border-radius: 0 0 5px 0;
  }
  button {
    display: grid;
    grid-template-columns: 2ch 3ch minmax(0, 1fr);
    align-items: baseline;
    text-align: left;
    width: 100%;
    border-radius: 4px;
    padding: 0.1rem 0.4rem;
    font-size: 1em;
    color: var(--muted-foreground);
    background: none;
    border: 1px solid transparent;
  }
  .pointer {
    visibility: hidden;
    color: var(--primary);
  }
  button:hover,
  button:focus-visible {
    background: var(--muted);
    color: var(--foreground);
    outline: none;
  }
  button:hover .pointer,
  button:focus-visible .pointer {
    visibility: visible;
  }
  .allow .name {
    color: var(--foreground);
  }
  .sub {
    margin-left: 1ch;
    font-size: 0.85em;
    color: var(--muted-foreground);
  }
  button:disabled {
    opacity: 0.6;
  }
  /* a touch screen: large buttons, the first answer filled; no pointer, no numbers */
  @media (pointer: coarse) {
    .answers {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 0.5rem;
      padding-top: 0.5rem;
    }
    button {
      display: flex;
      justify-content: center;
      text-align: center;
      min-height: 2.75rem;
      padding: 0.4rem 0.6rem;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--muted);
      color: var(--foreground);
    }
    button:first-child {
      background: var(--primary);
      border-color: var(--primary);
      color: var(--primary-foreground);
      font-weight: 700;
    }
    button:first-child .name,
    button:first-child .sub {
      color: inherit;
    }
    button.reject {
      background: none;
      color: var(--muted-foreground);
    }
    button:last-child:nth-child(odd) {
      grid-column: 1 / -1;
    }
    .pointer,
    .n {
      display: none;
    }
  }
</style>
