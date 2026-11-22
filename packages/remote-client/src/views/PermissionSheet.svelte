<script lang="ts">
  // A permission ask on the phone, in the session's sheet (the desktop keeps acp-view's
  // PermissionPrompt): what is asked (its kind as a question, the agent, the command or file, the
  // agent's own why, where it runs), then the answers. A safe ask gets two buttons, Reject and
  // Allow (filled), and the other answers as small links under them. A risky one (lib/risk.ts:
  // as the computer says, risky when it does not) says why in an amber line; its scope is picked first (the request's own allow answers: once,
  // or remembered), then a slide confirms it; Reject stays a tap. "Always" is never a quicker tap
  // than "once". Its top line says where it acts when the computer says so ("in the folder").
  // On a touch screen the buttons take no tap for a moment after they appear.
  import type { PermissionOption } from "@agentclientprotocol/sdk";
  import type { SessionAsk } from "../lib/remote.gen";
  import Diff from "@handler/acp-view/components/Diff.svelte";
  import type { PendingPermission } from "@handler/acp-view/lib/connection.svelte";
  import { markdown } from "@handler/acp-view/lib/render";
  import { blockText } from "@handler/acp-view/lib/session.svelte";
  import { SETTLE, settled } from "@handler/acp-view/lib/touch.svelte";
  import { homeFolder, permissionAnswers, permissionWhy, relative } from "@handler/acp-view/lib/tools";
  import { reachOf, riskOf } from "../lib/risk";
  import Slide from "./Slide.svelte";

  let {
    pending,
    root = null,
    agent = null,
    place = null,
    ask = null,
  }: {
    pending: PendingPermission;
    root?: string | null;
    agent?: string | null;
    place?: { project?: string | null; folder: string } | null;
    /** the session's first ask as the computer listed it (its risk), if any */
    ask?: SessionAsk | null;
  } = $props();
  const settle = settled();

  const tool = $derived(pending.request.toolCall);
  const options = $derived(pending.request.options);
  const risk = $derived(riskOf(tool, ask));
  const reach = $derived(reachOf(tool, ask));
  const why = $derived(permissionWhy(tool));
  const ASKS: Record<string, [string, string]> = {
    execute: ["Run a command?", "run"],
    edit: ["Change a file?", "change"],
    delete: ["Delete a file?", "delete"],
    move: ["Move a file?", "move"],
    fetch: ["Reach the network?", "fetch"],
    read: ["Read a file?", "read"],
    search: ["Search?", "search"],
    switch_mode: ["Start from its plan?", "start from its plan"],
  };
  const asks = $derived(ASKS[tool.kind ?? ""] ?? ["Allow this?", "do this"]);
  const diffs = $derived((tool.content ?? []).filter((c) => c.type === "diff"));
  const plan = $derived(
    tool.kind === "switch_mode"
      ? (tool.content ?? []).flatMap((c) => (c.type === "content" ? [blockText(c.content)] : [])).join("\n\n")
      : "",
  );
  const file = $derived(diffs.length === 1 && diffs[0]?.type === "diff" ? diffs[0].path : null);
  // a command's title without the backticks some harnesses put around it
  const title = $derived.by(() => {
    const t = tool.title ? (root ? tool.title.replaceAll(`${root.replace(/\/$/, "")}/`, "") : tool.title) : tool.toolCallId;
    return tool.kind === "execute" ? t.replace(/^`([^`]*)`$/s, "$1") : t;
  });
  const paths = $derived(
    (tool.locations ?? []).map((l) => l.path).filter((p) => !diffs.some((d) => d.type === "diff" && d.path === p)).map((p) => relative(p, root)),
  );

  // safe: Reject | Allow, then the rest as links
  const answers = $derived(permissionAnswers(options));
  // risky: the allow answers are the scope (once first), the reject ones taps
  const allows = $derived(
    options.filter((o) => o.kind.startsWith("allow")).sort((a, b) => Number(b.kind === "allow_once") - Number(a.kind === "allow_once")),
  );
  const rejects = $derived(options.filter((o) => o.kind.startsWith("reject")));
  let picked = $state<string | null>(null);
  const scope = $derived(allows.find((o) => o.optionId === picked) ?? allows[0]);

  function choose(option: PermissionOption): void {
    pending.answer({ outcome: "selected", optionId: option.optionId });
  }
</script>

{#snippet answer(option: PermissionOption, look: string)}
  <button
    type="button"
    class={look}
    class:settling={!settle.ready}
    style:--settle="{SETTLE}ms"
    disabled={!settle.ready}
    onclick={() => choose(option)}
    title={option.kind.endsWith("always") ? "Remembered: the agent does not ask again for the same thing" : "This time only"}
    data-testid="permission-answer"
    data-kind={option.kind}
  >{option.name}</button>
{/snippet}

<div class="ask" class:risky={risk} role="alertdialog" aria-label="permission request" aria-live="assertive" data-testid="permission-request">
  <p class="k">{asks[0]}{#if reach}<span data-testid="permission-reach">{reach}</span>{:else if place?.project}<span>{place.project}</span>{/if}</p>
  <h4>{agent || "The agent"} wants to {asks[1]}</h4>
  {#if plan}
    <div class="box md" data-testid="permission-plan">{@html markdown(plan)}</div>
  {:else if !file}
    <pre class="box" data-testid="permission-what">{#if tool.kind === "execute"}<span class="p">$ </span>{/if}{title}</pre>
  {/if}
  {#each diffs as d, i (i)}
    {#if d.type === "diff"}<Diff path={d.path} oldText={d.oldText} newText={d.newText} {root} />{/if}
  {/each}
  {#if why}<p class="why" data-testid="permission-why">“{why}”</p>{/if}
  {#if paths.length}<p class="wh" data-testid="permission-touches">Touches {paths.join(" · ")}</p>{/if}
  {#if place}
    <p class="wh" data-testid="permission-where" title={place.folder}>
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" /></svg>
      {homeFolder(place.folder)}
    </p>
  {/if}

  {#if risk}
    <p class="risk" data-testid="permission-risk">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3M12 9v4M12 17h.01" /></svg>
      <span>{risk}</span>
    </p>
    {#if allows.length > 1}
      <div class="scope" role="radiogroup" aria-label="how long">
        {#each allows as option (option.optionId)}
          <button
            type="button"
            role="radio"
            aria-checked={option === scope}
            onclick={() => (picked = option.optionId)}
            data-testid="permission-scope"
            data-kind={option.kind}
          >{option.name}</button>
        {/each}
      </div>
    {/if}
    {#if scope}
      <div class="slot">
        <Slide
          label="slide to {scope.name.toLowerCase()}"
          question="{scope.name}?"
          disabled={!settle.ready}
          onconfirm={() => choose(scope)}
          testid="permission-slide"
        />
      </div>
    {/if}
    <div class="rejects">
      {#each rejects as option (option.optionId)}{@render answer(option, "reject")}{/each}
    </div>
  {:else}
    <div class="pair" class:one={answers.pair.length === 1}>
      {#each answers.pair as option (option.optionId)}{@render answer(option, option.kind.startsWith("allow") ? "allow" : "plain")}{/each}
    </div>
    {#each answers.more as option (option.optionId)}{@render answer(option, "more")}{/each}
  {/if}
</div>

<style>
  /* in the session's dark sheet (term-surface's tokens), the mockup's dark sheet */
  .ask {
    --slide-knob: #3fb872;
    --slide-on-knob: #0f2a1a;
    display: flex;
    flex-direction: column;
    padding-bottom: 0.9rem;
    font-family: var(--sans);
    font-size: 14px;
    line-height: 1.45;
  }
  .ask + .ask {
    padding-top: 0.9rem;
    border-top: 1px solid var(--border);
  }
  .k {
    display: flex;
    justify-content: space-between;
    gap: 1ch;
    margin: 0;
    font: 600 11px var(--mono);
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--warn);
  }
  .k span {
    text-transform: none;
    letter-spacing: 0;
    font-weight: 400;
    color: var(--muted-foreground);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  h4 {
    margin: 0.25rem 0 0.55rem;
    font: 700 17px/1.3 var(--mono);
    letter-spacing: -0.02em;
    color: var(--foreground);
    overflow-wrap: anywhere;
  }
  .box {
    margin: 0;
    padding: 0.6rem 0.75rem;
    border: 1px solid #34312d;
    border-radius: 10px;
    background: #0d0c0b;
    color: var(--foreground);
    font: 13px/1.5 var(--mono);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    max-height: 12rem;
    overflow-y: auto;
  }
  .box .p {
    color: var(--primary);
  }
  .md :global(:first-child) {
    margin-top: 0;
  }
  .why {
    margin: 0.5rem 0.15rem 0;
    font-size: 12.5px;
    color: var(--muted-foreground);
    overflow-wrap: anywhere;
  }
  .wh {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    margin: 0.5rem 0.15rem 0;
    font: 11.5px var(--mono);
    color: var(--muted-foreground);
    overflow-wrap: anywhere;
  }
  svg {
    flex: none;
    width: 0.9rem;
    height: 0.9rem;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  /* why it is risky: a soft amber line, no stripe */
  .risk {
    display: flex;
    align-items: flex-start;
    gap: 0.5rem;
    margin: 0.6rem 0 0;
    padding: 0.5rem 0.65rem;
    border: 1px solid #4a3a1c;
    border-radius: 10px;
    background: #2e2416;
    color: #f0c89b;
    font: 12px/1.45 var(--mono);
  }
  .risk svg {
    margin-top: 0.1rem;
  }
  .scope {
    display: flex;
    gap: 3px;
    margin-top: 0.75rem;
    padding: 3px;
    border-radius: 11px;
    background: var(--secondary);
  }
  .scope button {
    flex: 1;
    min-height: 2.25rem;
    padding: 0.2rem 0.5rem;
    border-radius: 8px;
    color: var(--muted-foreground);
    font: 600 12.5px var(--mono);
  }
  .scope button[aria-checked="true"] {
    background: #3a3631;
    color: var(--foreground);
    box-shadow: 0 1px 3px rgb(0 0 0 / 0.4);
  }
  .slot {
    margin-top: 0.75rem;
  }
  .pair {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.6rem;
    margin-top: 0.85rem;
  }
  .pair.one {
    grid-template-columns: 1fr;
  }
  .rejects {
    display: flex;
    gap: 0.5rem;
    margin-top: 0.6rem;
  }
  button {
    position: relative;
    overflow: hidden;
  }
  .plain,
  .allow,
  .reject {
    flex: 1;
    min-height: 3rem;
    padding: 0.3rem 0.75rem;
    border-radius: 13px;
    font: 600 15px var(--sans);
    overflow-wrap: anywhere;
  }
  .plain {
    border: 1px solid #3d3a35;
    color: var(--foreground);
  }
  .allow {
    background: var(--primary);
    color: var(--primary-foreground);
  }
  .reject {
    min-height: 2.65rem;
    background: var(--secondary);
    color: var(--danger);
    font-size: 13px;
  }
  .more {
    margin-top: 0.6rem;
    padding: 0.35rem;
    background: none;
    color: var(--muted-foreground);
    font: 12.5px var(--sans);
    text-decoration: underline;
    text-underline-offset: 3px;
  }
  /* a touch screen's buttons take no tap for a moment: a fill sweeps across them */
  button.settling::after {
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
</style>
