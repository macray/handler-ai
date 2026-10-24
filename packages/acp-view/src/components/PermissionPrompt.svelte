<script lang="ts">
  // The agent waits for your answer: what it asks to do (the tool call's own title, its files and
  // its diff, never the agent's prose about it), then its options, allow and reject apart, kept in
  // view under a long diff; one that is remembered says so. On a touch screen they take no tap for
  // a moment after it appears or the screen comes back on.
  import type { PermissionOption } from "@agentclientprotocol/sdk";
  import type { PendingPermission } from "../lib/connection.svelte";
  import { SETTLE, settled } from "../lib/touch.svelte";
  import { relative } from "../lib/tools";
  import Diff from "./Diff.svelte";

  let { pending, root }: { pending: PendingPermission; root?: string | null } = $props(); // root: the session's folder
  const settle = settled();

  const tool = $derived(pending.request.toolCall);
  const options = $derived(pending.request.options);
  const allows = $derived(options.filter((o) => o.kind.startsWith("allow")));
  const rejects = $derived(options.filter((o) => o.kind.startsWith("reject")));
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
</script>

<div class="permission" role="alertdialog" aria-label="permission request" aria-live="assertive" data-testid="permission-request">
  <div class="head">
    <span class="badge">Needs you</span>
    {#if file}
      <span>The agent asks to change this file:</span>
    {:else}
      <span>The agent asks {asks}:</span>
    {/if}
  </div>
  {#if !file}<pre class="what">{title}</pre>{/if}
  {#if paths.length}<p class="paths">{paths.join(" · ")}</p>{/if}
  {#each diffs as d, i (i)}
    {#if d.type === "diff"}<Diff path={d.path} oldText={d.oldText} newText={d.newText} {root} />{/if}
  {/each}
  <div class="answers">
    {#each allows as option (option.optionId)}
      {@render answer(option, "allow")}
    {/each}
    {#each rejects as option (option.optionId)}
      {@render answer(option, "reject")}
    {/each}
  </div>
</div>

{#snippet answer(option: PermissionOption, side: "allow" | "reject")}
  {@const always = option.kind.endsWith("always")}
  <button
    type="button"
    class="{side} {always ? 'always' : 'once'}"
    class:settling={!settle.ready}
    style:--settle="{SETTLE}ms"
    disabled={!settle.ready}
    onclick={() => choose(option)}
    title={always ? "Remembered: the agent does not ask again for the same thing" : "This time only"}
  >
    {option.name}{#if always}<span class="sub">remembered</span>{/if}
  </button>
{/snippet}

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
  /* it rises into view: the moment the agent stops for you */
  .permission {
    animation: rise var(--dur-3) var(--ease) backwards;
    border: 1px solid var(--warn);
    border-radius: 10px;
    padding: 0.75rem 0.9rem;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
    margin: 0.5rem 0;
    background: color-mix(in srgb, var(--warn) 12%, var(--background));
  }
  .head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.6rem;
    font-weight: 600;
  }
  .badge {
    background: var(--warn);
    color: var(--background);
    border-radius: 4px;
    padding: 0.05rem 0.45rem;
    font-size: 0.85em;
    font-weight: 700;
  }
  .what {
    margin: 0;
    padding: 0.5rem 0.7rem;
    border-radius: 6px;
    background: var(--background);
    border: 1px solid color-mix(in srgb, var(--warn) 50%, transparent);
    color: var(--foreground);
    font-weight: 600;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .paths {
    margin: 0;
    color: var(--muted-foreground);
    overflow-wrap: anywhere;
  }
  .answers {
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
    position: sticky; /* under a long diff, the answers stay in view */
    bottom: 0;
    margin: 0 -0.9rem -0.75rem;
    padding: 0.6rem 0.9rem 0.75rem;
    background: color-mix(in srgb, var(--warn) 12%, var(--background));
    border-radius: 0 0 9px 9px;
  }
  button {
    display: inline-flex;
    align-items: baseline;
    gap: 0.5ch;
    border-radius: 6px;
    padding: 0.35rem 0.9rem;
    font-size: 1em;
    font-weight: 600;
    border: 1px solid transparent;
  }
  .sub {
    font-size: 0.8em;
    font-weight: 400;
    opacity: 0.85;
  }
  .allow.once {
    background: var(--ok);
    color: var(--background);
  }
  .allow.once:hover {
    background: color-mix(in srgb, var(--ok) 85%, var(--foreground));
  }
  .allow.always {
    color: var(--ok);
    border-color: var(--ok);
    background: var(--background);
  }
  .allow.always:hover {
    background: color-mix(in srgb, var(--ok) 12%, var(--background));
  }
  .reject {
    color: var(--danger);
    border-color: var(--danger);
    background: var(--background);
  }
  .reject:hover {
    background: color-mix(in srgb, var(--danger) 12%, var(--background));
  }
  button:disabled {
    background: var(--muted);
    color: var(--muted-foreground);
    border-color: var(--border);
  }
  @media (pointer: coarse) {
    button {
      min-height: 2.75rem;
    }
  }
</style>
