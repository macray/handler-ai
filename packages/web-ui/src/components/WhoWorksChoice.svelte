<script lang="ts">
  // Who works on a session, a run or an agent (E2, D.1, D.19): one frame in three linked parts,
  // account or provider ▾ · program · model ▾ (lib/whoworks: what each part offers, and why not).
  // The account menu: the person's accounts and providers, one row each, grouped, each saying
  // which programs it works with; what cannot run here folded with its count and why; Connect
  // another… last: a Connect dialog over the page (lib/connect), the one made there chosen. The
  // program: text when the row has one, a menu when several. The model: its own menu, "default
  // model" until changed. Two or more and none chosen: "Choose an account", outlined, nothing
  // picked for the person. Same words in a form (light) and a console (dark).
  // `value`: the model as a request names it; undefined: the agent's own. Another one is for this
  // session only (a dot, a footer, and `ondefault` making it the agent's own). `own`: the agent
  // form, choosing the agent's own model: each pick is `onchange`'s, no dot, no footer; with
  // `onalone` the program menu swaps the model alone and an agent program. `unattended`: the agent
  // runs on its own (a job's run, an automation): on a subscription, one line recommends an API
  // key, with a switch to one (vendors' terms). `limits`: what an app's job asks of who does it
  // (H.2): the choices that cannot do it greyed with why (lib/whoworks `Limits`).
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import Check from "@lucide/svelte/icons/check";
  import Info from "@lucide/svelte/icons/info";
  import Plus from "@lucide/svelte/icons/plus";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import { untrack } from "svelte";
  import { Button } from "$lib/components/ui/button";
  import { sameModel } from "../lib/access";
  import { api } from "../lib/api";
  import { connect, type ConnectKind } from "../lib/connect.svelte";
  import type { AccountInfo, Agent, ModelAccess, ProviderInfo } from "../lib/contracts.gen";
  import { harnesses } from "../lib/harnesses.svelte";
  import { agentLabel } from "../lib/projects.svelte";
  import { href } from "../lib/router.svelte";
  import * as ww from "../lib/whoworks";
  import Popover from "./Popover.svelte";

  let {
    agent,
    value = $bindable(),
    ondefault,
    own = false,
    onchange,
    onalone,
    unattended = false,
    limits,
  }: {
    agent: Pick<Agent, "id" | "name" | "model" | "area" | "modelAlone">;
    value?: ModelAccess;
    ondefault?: (model: ModelAccess) => Promise<void>; // make the one chosen the agent's own
    own?: boolean;
    onchange?: (model: ModelAccess) => void; // own: the model picked
    onalone?: (alone: boolean) => void; // own: the model alone, or back to an agent program
    unattended?: boolean; // it runs on its own: a subscription is recommended an API key
    limits?: ww.Limits; // an app's job: what cannot do it, greyed with why
  } = $props();

  let accounts = $state<AccountInfo[]>([]);
  let providers = $state<ProviderInfo[]>([]);
  let loaded = $state(false);
  const load = () =>
    Promise.all([api.accounts(), api.providers()]).then(
      ([a, p]) => ((accounts = a), (providers = p), (loaded = true)),
      () => {}, // only the agent's own model then
    );
  void load();
  void harnesses.load();

  const place = $derived<ww.Place>({
    agent: { name: agentLabel(agent), model: agent.model, area: agent.area, modelAlone: agent.modelAlone },
    accounts,
    providers,
    harnesses: harnesses.list,
    loaded,
    form: own,
    switchKind: own && !!onalone,
    limits,
  });
  const rows = $derived(ww.rowsOf(place));
  const folds = $derived(ww.foldsOf(place));
  let choice = $state<ww.Choice | null>(null);
  const status = $derived(ww.stateOf(rows, choice));
  const row = $derived(choice ? rows.find((r) => r.key === choice?.key) : undefined);
  const groups = $derived(
    [
      { name: "Subscriptions", rows: rows.filter((r) => r.group === "subscriptions") },
      { name: "API keys and local models", rows: rows.filter((r) => r.group === "keys") },
    ]
      .filter((g) => g.rows.length)
      .sort((a, b) => Number(b.rows.some((r) => r.own)) - Number(a.rows.some((r) => r.own))),
  );
  const note = $derived(own ? null : ww.sessionNote(place, rows, choice));
  const line = $derived(ww.unattendedLine(place, rows, choice, unattended));
  const name = $derived(agentLabel(agent));
  const hasModel = $derived(!!(agent.model.account || agent.model.provider));

  let accountOpen = $state(false);
  let programOpen = $state(false);
  let modelOpen = $state(false);
  let saving = $state(false);
  let error = $state<string | null>(null);

  function reset(): void {
    value = undefined;
    choice = ww.initial(place, rows);
    const picked = ww.accessOfChoice(rows, choice);
    if (own && picked && sameModel(picked, agent.model)) return; // its own again: nothing changed
    update(); // the one ready, chosen by itself; or not the agent's own (its own not offered here)
  }
  // own: a model given from outside (a new agent's, the kind switched): chosen
  $effect(() => {
    const m = agent.model;
    untrack(() => {
      const picked = ww.accessOfChoice(rows, choice);
      if (own && hasModel && !(picked && sameModel(picked, m))) reset();
    });
  });
  // the lists loaded, or the chosen one no longer offered: the first choice again
  $effect(() => {
    const list = rows;
    untrack(() => {
      if (!choice || !list.some((r) => r.key === choice?.key)) reset();
    });
  });

  function update(): void {
    const picked = ww.accessOfChoice(rows, choice);
    if (!picked) return;
    if (own) return onchange?.(picked);
    value = ww.sessionValue(place, rows, choice);
  }

  function pickRow(key: string): void {
    choice = ww.pickRow(place, rows, choice, key);
    update();
  }

  function pickProgram(harness: string): void {
    if (!choice) return;
    const alone = harness === "";
    if (own && onalone && alone !== agent.modelAlone) {
      choice = { ...choice, harness };
      onalone(alone); // the form swaps the agent's kind, then takes the pick
      return update();
    }
    choice = ww.pickProgram(rows, choice, harness);
    update();
  }

  function pickModel(model: string): void {
    if (!choice) return;
    choice = ww.pickModel(choice, model);
    update();
  }

  /** A Connect over the page (E1): the one made there is chosen, if it can run this agent. */
  function connectAnother(kind: ConnectKind): void {
    accountOpen = false;
    connect.open(kind, async (made) => {
      await load();
      const r = rows.find((x) => (made.kind === "account" ? x.account : x.provider) === made.name);
      if (r && !r.why) pickRow(r.key);
    });
  }

  async function makeDefault(): Promise<void> {
    if (!value || !ondefault) return;
    saving = true;
    error = null;
    try {
      await ondefault(value);
      value = undefined; // it is the agent's now
    } catch (e) {
      error = (e as Error).message;
    } finally {
      saving = false;
    }
  }

  const PART = "part inline-flex min-w-0 cursor-pointer items-center gap-1.5 px-2 hover:bg-secondary aria-expanded:bg-secondary";
</script>

{#snippet dot()}
  <span class="size-1.5 shrink-0 rounded-full bg-primary" title="Changed for this session only" data-testid="model-choice-changed"></span>
{/snippet}

{#snippet letter(text: string)}
  <span class="grid size-5 shrink-0 place-items-center rounded-[5px] bg-muted text-[10.5px] font-semibold text-muted-foreground" aria-hidden="true">{text.charAt(0).toUpperCase()}</span>
{/snippet}

{#snippet footer()}
  {#if note}
    <div class="menu-foot" data-testid="model-choice-session-only">
      <span class="flex min-w-0 items-center gap-1.5"><Info class="size-3.5 shrink-0" />{note.text}</span>
      {#if ondefault}
        <Button size="sm" variant="outline" disabled={saving} onclick={makeDefault} data-testid="model-choice-make-default">{note.makeDefault}</Button>
      {/if}
    </div>
    {#if error}<p class="px-2.5 pb-1.5 text-xs text-danger">{error}</p>{/if}
  {/if}
{/snippet}

{#snippet fold(f: ww.Fold, testid: string, open: boolean)}
  <details class="fold" {open} data-testid={testid}>
    <summary class="flex cursor-pointer list-none items-center gap-2 px-2.5 py-2 text-[13px] text-muted-foreground">
      <ChevronRight class="chev size-3.5 shrink-0" /><span class="shrink-0 whitespace-nowrap">{f.label}: {f.count}</span>
      {#if !open}<span class="min-w-0 truncate opacity-70">· {f.rows.map((x) => `${x.name} ${x.why.charAt(0).toLowerCase()}${x.why.slice(1)}`).join(", ")}</span>{/if}
    </summary>
    {#each f.rows as x (x.name)}
      <p class="pr-2.5 pb-1.5 pl-8 text-xs text-muted-foreground" data-testid="who-works-folded">
        <span class="font-mono">{x.name}</span> · {x.why}{#if x.anyway}. Starting it here anyway is CLI only: <code class="rounded bg-muted px-1">{x.anyway}</code>{/if}
        {#if x.action}<a class="text-link no-underline hover:underline" href={href({ view: "settings", section: "models" })} onclick={() => (accountOpen = false)}>{x.action}</a>{/if}
      </p>
    {/each}
    {#if testid === "model-choice-hidden" && folds.areaHint}<p class="pr-2.5 pb-1.5 pl-8 text-xs text-muted-foreground">{folds.areaHint}</p>{/if}
  </details>
{/snippet}

<div class="flex max-w-full flex-col items-start gap-1" data-testid="model-choice">
  {#if status === "none" && !(folds.area || folds.notReady)}
    <button type="button" class="who none inline-flex cursor-pointer items-center gap-1.5 px-2.5" onclick={() => connectAnother("both")} data-testid="model-choice-none"><Plus class="size-3.5" />Connect a model to start</button>
  {:else}
    <div class="who" class:ask={status === "ask"} class:none={status === "none"} data-state={status}>
      <Popover bind:open={accountOpen} label="Account" width="25rem" testid="model-choice-runs-on">
        {#snippet trigger(props)}
          <button type="button" class="{PART} pl-1.5" {...props} aria-label="Who works: account" data-testid="model-choice-access">
            {#if row}
              {@render letter(row.name)}
              <span class="truncate font-medium">{row.name}</span>
            {:else}
              <span class="font-medium" class:text-warn={status === "none"}>{status === "none" ? "Nothing ready here" : "Choose an account"}</span>
            {/if}
            <ChevronDown class="size-3.5 shrink-0 opacity-60" />
          </button>
        {/snippet}
        {#snippet children(close)}
          {#each groups as g (g.name)}
            <p class="menu-group">{g.name}</p>
            {#each g.rows as r (r.key)}
              {@const selected = r.key === choice?.key}
              <button
                type="button"
                class="menu-row"
                class:selected
                class:off={!!r.why}
                aria-pressed={selected}
                disabled={!!r.why}
                onclick={() => (pickRow(r.key), close())}
                data-testid={r.why ? "model-choice-elsewhere" : "model-choice-access-row"}
              >
                {@render letter(r.name)}
                <span class="min-w-0 flex-1">
                  <span class="block truncate"><span>{r.name}</span>{#if r.own && !own}<span class="ml-1.5 text-[11px] text-muted-foreground">{name}'s</span>{/if}</span>
                  <span class="block truncate text-xs text-muted-foreground"
                    >{r.why ?? r.worksWith} · {r.kindWords}{#if r.problem}{" · cannot start now"}{/if}</span
                  >
                </span>
                {#if selected}<Check class="size-4 shrink-0 text-primary" />{/if}
              </button>
            {/each}
          {/each}
          {#if folds.area}{@render fold(folds.area, "model-choice-hidden", !rows.length)}{/if}
          {#if folds.notReady}{@render fold(folds.notReady, "model-choice-not-ready", false)}{/if}
          <button type="button" class="menu-foot connect w-full cursor-pointer" onclick={() => (close(), connectAnother("both"))} data-testid="who-works-connect"><Plus class="size-3.5" />Connect another…</button>
          {@render footer()}
        {/snippet}
      </Popover>
      {#if !row}
        <span class="part off px-2.5">program</span>
        <span class="part off px-2.5">model</span>
      {:else}
        {@const program = row.programs.find((p) => p.harness === choice?.harness)}
        {#if ww.programPart(row) === "text"}
          <span class="part set truncate px-2.5" data-testid="model-choice-harness">{program?.label ?? row.programs[0]?.label}</span>
        {:else}
          <Popover bind:open={programOpen} label="Program" width="18rem" testid="model-choice-programs">
            {#snippet trigger(props)}
              <button type="button" class={PART} {...props} aria-label="program" data-testid="model-choice-harness">
                <span class="truncate">{program?.label ?? "Choose a program"}</span>
                <ChevronDown class="size-3.5 shrink-0 opacity-60" />
              </button>
            {/snippet}
            {#snippet children(close)}
              <p class="menu-group">Program on {row.name}</p>
              {#each row.programs as p (p.harness)}
                {@const on = p.harness === choice?.harness}
                <button
                  type="button"
                  class="menu-row"
                  class:selected={on}
                  class:off={!p.offered}
                  aria-pressed={on}
                  disabled={!p.offered}
                  onclick={() => (pickProgram(p.harness), close())}
                  data-testid={p.harness ? "model-choice-program" : "model-choice-program-alone"}
                >
                  <span class="w-4 shrink-0">{#if on}<Check class="size-4 text-primary" />{/if}</span>
                  <span class="min-w-0 flex-1">{p.label}</span>
                  <span class="text-xs text-muted-foreground">{p.why ?? (p.harness ? "" : "one call: no files, no tools")}</span>
                </button>
              {/each}
            {/snippet}
          </Popover>
        {/if}
        <Popover bind:open={modelOpen} label="Model" width="18rem" testid="who-works-models">
          {#snippet trigger(props)}
            <button type="button" class="{PART} text-muted-foreground" {...props} aria-label="model" data-testid="who-works-model">
              <span class="truncate" data-testid="model-choice-model-name">{ww.modelLabel(choice)}</span>
              {#if value}{@render dot()}{/if}
              <ChevronDown class="size-3.5 shrink-0 opacity-60" />
            </button>
          {/snippet}
          {#snippet children(close)}
            <p class="menu-group">Model on {row.name}</p>
            {#each row.models as m (m.value)}
              {@const on = m.value === choice?.model}
              <button
                type="button"
                class="menu-row"
                class:selected={on}
                aria-pressed={on}
                disabled={!!m.problem}
                title={m.problem ? `Cannot start now: ${m.problem}` : undefined}
                onclick={() => (pickModel(m.value), close())}
                data-testid="model-choice-model"
              >
                <span class="w-4 shrink-0">{#if on}<Check class="size-4 text-primary" />{/if}</span>
                <span class="min-w-0 flex-1 truncate">{m.label}{#if m.own && !own}<span class="ml-1.5 text-[11px] text-muted-foreground">{name}'s</span>{/if}</span>
                {#if m.detail}<span class="text-xs text-muted-foreground">{m.detail}</span>{/if}
              </button>
            {/each}
            {@render footer()}
          {/snippet}
        </Popover>
      {/if}
    </div>
    {#if line}
      <p class="flex flex-wrap items-center gap-1.5 text-xs text-warn" data-testid="who-works-unattended">
        <TriangleAlert class="size-3.5 shrink-0" />{line.text}
        {#if line.terms}<a class="text-link no-underline hover:underline" href={line.terms} target="_blank" rel="noreferrer">Its terms</a>{/if}
        {#if line.switchTo}
          <button type="button" class="text-link cursor-pointer hover:underline" onclick={() => line.switchTo && ((choice = line.switchTo), update())} data-testid="who-works-unattended-switch"
            >Use {line.switchName}</button
          >
        {:else}
          <button type="button" class="text-link cursor-pointer hover:underline" onclick={() => connectAnother("provider")} data-testid="who-works-unattended-connect">Connect an API key</button>
        {/if}
      </p>
    {/if}
  {/if}
</div>

<style>
  /* one frame, three parts: in a form (light) and a console (dark), by the page's tokens */
  .who {
    display: inline-flex;
    max-width: 100%;
    height: 1.875rem;
    align-items: stretch;
    overflow: hidden;
    border: 1px solid var(--border);
    border-radius: 0.5rem;
    font-size: 0.8125rem;
    white-space: nowrap;
  }
  .who.ask {
    border-color: var(--primary);
    box-shadow: 0 0 0 3px color-mix(in oklab, var(--primary) 15%, transparent);
  }
  .who.none {
    border-style: dashed;
    color: var(--primary);
  }
  button.who.none {
    height: 1.875rem;
    background: transparent;
  }
  /* each part keeps its width: a narrow row wraps the frame whole, never one part over another */
  .who > :global(*) {
    flex-shrink: 0;
  }
  .who :global(.part) {
    border-left: 1px solid var(--border);
    background: transparent;
    color: inherit;
  }
  .who > :global(:first-child),
  .who > :global(:first-child .part) {
    border-left: 0;
  }
  .part.set,
  .part.off {
    display: inline-flex;
    align-items: center;
    color: var(--muted-foreground);
  }
  .part.off {
    opacity: 0.6;
  }
  .menu-group {
    padding: 8px 10px 4px;
    color: var(--muted-foreground);
    font-size: 11.5px;
    font-weight: 600;
  }
  .menu-row {
    display: flex;
    width: 100%;
    align-items: center;
    gap: 9px;
    padding: 7px 10px;
    border-radius: 7px;
    color: inherit;
    text-align: left;
    cursor: pointer;
  }
  .menu-row:hover:not(:disabled),
  .menu-row.selected {
    background: var(--muted);
  }
  .menu-row:disabled {
    cursor: default;
    opacity: 0.5;
  }
  .fold {
    margin-top: 4px;
    border-top: 1px solid var(--border);
  }
  .fold + .fold {
    margin-top: 0;
  }
  .fold[open] :global(.chev) {
    transform: rotate(90deg);
  }
  .menu-foot {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-top: 4px;
    padding: 8px 10px 4px;
    border-top: 1px solid var(--border);
    color: var(--muted-foreground);
    font-size: 12.5px;
  }
  .menu-foot.connect {
    justify-content: flex-start;
    color: var(--primary);
    font-weight: 550;
  }
</style>
