<script lang="ts">
  // The agent waits for your answer: what it asks to do (the tool call's own title, the files it
  // touches and its diff; on the phone also where it runs, the session's project and folder; a plan it asks to start from is shown whole, as the agent wrote it), why in the
  // agent's own words when the harness gives them, then Reject and Allow side by side, the same
  // size and style (no default for the risky answer; the harness's names), and under them any
  // other answer it offers (a remembered one says so), kept in view under a long diff. The same
  // card in One, a Grid tile and on the phone. On a keyboard the first answer (Reject) takes the
  // focus (unless you are typing), the arrow keys move between answers and Enter picks one. On a
  // touch screen they are large buttons that take no tap for a moment after they appear or the
  // screen comes back on.
  import type { PermissionOption } from "@agentclientprotocol/sdk";
  import type { PendingPermission } from "../lib/connection.svelte";
  import { markdown } from "../lib/render";
  import { blockText } from "../lib/session.svelte";
  import { SETTLE, settled, touch } from "../lib/touch.svelte";
  import { homeFolder, permissionAnswers, permissionWhy, relative } from "../lib/tools";
  import Diff from "./Diff.svelte";

  // root: the session's folder. On the phone, where the screen does not say it: `agent`, the
  // agent's name (it asks), and `place`, where it runs (the session's project and folder)
  let {
    pending,
    root,
    agent = null,
    place = null,
  }: {
    pending: PendingPermission;
    root?: string | null;
    agent?: string | null;
    place?: { project?: string | null; folder: string } | null;
  } = $props();
  const settle = settled();

  const tool = $derived(pending.request.toolCall);
  const options = $derived(pending.request.options);
  const answers = $derived(permissionAnswers(options));
  const why = $derived(permissionWhy(tool));
  const VERB: Record<string, string> = {
    execute: "run a command",
    edit: "change a file",
    delete: "delete a file",
    move: "move a file",
    fetch: "reach the network",
    read: "read a file",
  };
  const who = $derived(agent || "The agent");
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

  /** The arrow keys move between the answers (Enter or Space picks the one focused, as any button). */
  function move(event: KeyboardEvent): void {
    const step = event.key === "ArrowDown" || event.key === "ArrowRight" ? 1 : event.key === "ArrowUp" || event.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    const buttons = [...(event.currentTarget as HTMLElement).querySelectorAll("button")];
    const at = buttons.indexOf(document.activeElement as HTMLButtonElement);
    const next = buttons[(at + step + buttons.length) % buttons.length];
    event.preventDefault();
    next?.focus();
  }
</script>

<div class="permission" class:plan role="alertdialog" aria-label="permission request" aria-live="assertive" data-testid="permission-request">
  <div class="head">
    <span class="badge">Needs you</span>
    {#if plan}
      <span>{who} asks to start working from its plan:</span>
    {:else if file}
      <span>{who} asks to change this file:</span>
    {:else}
      <span>{who} asks {asks}:</span>
    {/if}
  </div>
  {#if why}<p class="why" data-testid="permission-why">“{why}”</p>{/if}
  {#if plan}
    <div class="planbox md" data-testid="permission-plan">{@html markdown(plan)}</div>
  {:else if !file}<pre class="what" data-testid="permission-what">{title}</pre>{/if}
  {#if paths.length}<p class="paths" data-testid="permission-touches">Touches {paths.join(" · ")}</p>{/if}
  {#if place}
    <p class="where" data-testid="permission-where" title={place.folder}>
      In {[place.project, homeFolder(place.folder)].filter(Boolean).join(" · ")}
    </p>
  {/if}
  {#each diffs as d, i (i)}
    {#if d.type === "diff"}<Diff path={d.path} oldText={d.oldText} newText={d.newText} {root} />{/if}
  {/each}
  <div class="answers" role="toolbar" aria-label="answers" tabindex="-1" onkeydown={move} {@attach focusFirst}>
    {#snippet answer(option: PermissionOption, wide: boolean)}
      {@const always = option.kind.endsWith("always")}
      <button
        type="button"
        class={[option.kind.startsWith("allow") ? "allow" : "reject", wide && "wide"]}
        class:settling={!settle.ready}
        style:--settle="{SETTLE}ms"
        disabled={!settle.ready}
        onclick={() => choose(option)}
        title={always ? "Remembered: the agent does not ask again for the same thing" : "This time only"}
        data-testid="permission-answer"
        data-kind={option.kind}
      >
        {option.name}{#if always}<span class="sub">remembered</span>{/if}
      </button>
    {/snippet}
    <div class="pair">
      {#each answers.pair as option (option.optionId)}{@render answer(option, answers.pair.length === 1)}{/each}
    </div>
    {#each answers.more as option (option.optionId)}{@render answer(option, true)}{/each}
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
  .paths,
  .where {
    margin: 0;
    color: var(--muted-foreground);
    overflow-wrap: anywhere;
  }
  .why {
    margin: 0;
    color: var(--muted-foreground);
    overflow-wrap: anywhere;
  }
  /* Reject | Allow: two equal buttons, then the other answers, each a row of its own */
  .answers {
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    position: sticky; /* under a long diff, the answers stay in view */
    bottom: 0;
    margin: 0 -0.9rem -0.7rem;
    padding: 0.3rem 0.9rem 0.7rem;
    background: var(--user-line, var(--card));
    border-radius: 0 0 5px 0;
  }
  .pair {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.5rem;
  }
  button {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 1ch;
    min-height: 1.9rem;
    padding: 0.2rem 0.75rem;
    border: 1px solid color-mix(in oklab, var(--foreground) 22%, transparent);
    border-radius: 7px;
    background: var(--background);
    color: var(--foreground);
    font-size: 1em;
    font-weight: 600;
    text-align: center;
    overflow-wrap: anywhere;
  }
  button.wide {
    grid-column: 1 / -1;
  }
  button:hover,
  button:focus-visible {
    border-color: var(--foreground);
    background: var(--muted);
    outline: none;
  }
  .sub {
    font-size: 0.85em;
    font-weight: 400;
    color: var(--muted-foreground);
  }
  button:disabled {
    opacity: 0.6;
  }
  /* a touch screen: large buttons, still equal */
  @media (pointer: coarse) {
    .answers {
      padding-top: 0.5rem;
    }
    button {
      min-height: 2.75rem;
      border-radius: 10px;
    }
  }
</style>
