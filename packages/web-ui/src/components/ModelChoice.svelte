<script lang="ts">
  // Who works on a session or a run (D.1, D.19), as two chips: [program ▾] then [account or key ·
  // model ▾]. The program's menu lists the programs ready to run (each with how many accounts and
  // keys run it, its version), then one quiet line for those not ready. The second lists what the
  // chosen program runs on (the agent's own first), with the models of the one selected under it
  // (the agent's own first, under its name); what it cannot run on stays listed, greyed with why.
  // The agent's model by default; another is for this session only, never saved to the agent
  // (another model is not another agent): a dot on the chip changed, and the menu's footer says
  // so, with the button that makes it the agent's own (`ondefault`, the agent's model, D.1).
  // Accounts and providers not made for its project's area are not offered, the agent's own
  // included: a line says which, and how to run one anyway (the terminal only, outside the
  // project). `value`: the model as a request names it; undefined: the agent's. An agent on the
  // model alone (D.18) has one chip: the providers handlerd can call, and their models.
  // `own`: the agent form's Who works, choosing the agent's own model (`agent.model`, nothing yet
  // for a new one): each pick is `onchange`'s, no footer, no dot; with two or more to run a
  // program on, the person chooses (never the wrong account by default). Its program menu ends
  // with the model alone, or an agent program when on it (`onalone`; without it, the kind is fixed:
  // a helper's, whose need says which, so the model alone is its one chip). On the model alone,
  // the subscriptions are listed greyed: they need an API key.
  import Check from "@lucide/svelte/icons/check";
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import Info from "@lucide/svelte/icons/info";
  import Plus from "@lucide/svelte/icons/plus";
  import { untrack } from "svelte";
  import { Button } from "$lib/components/ui/button";
  import { requested, sameModel } from "../lib/access";
  import { ago } from "../lib/agents";
  import { api } from "../lib/api";
  import { allows } from "../lib/areas.svelte";
  import type { AccountInfo, Agent, ModelAccess, ProviderInfo } from "../lib/contracts.gen";
  import { harnesses, productName } from "../lib/harnesses.svelte";
  import { agentLabel } from "../lib/projects.svelte";
  import { href } from "../lib/router.svelte";
  import Popover from "./Popover.svelte";

  let {
    agent,
    value = $bindable(),
    ondefault,
    own = false,
    onchange,
    onalone,
  }: {
    agent: Pick<Agent, "id" | "name" | "model" | "area" | "modelAlone">;
    value?: ModelAccess;
    ondefault?: (model: ModelAccess) => Promise<void>; // make the one chosen the agent's own
    own?: boolean;
    onchange?: (model: ModelAccess) => void; // own: the model picked
    onalone?: (alone: boolean) => void; // own: the model alone, or back to an agent program
  } = $props();

  let accounts = $state<AccountInfo[]>([]);
  let providers = $state<ProviderInfo[]>([]);
  let loaded = $state(false);
  Promise.all([api.accounts(), api.providers()]).then(
    ([a, p]) => ((accounts = a), (providers = p), (loaded = true)),
    () => {}, // only the agent's own model then
  );
  void harnesses.load();

  // what one can run on: an account (it brings its program) or a provider (with one of the
  // programs that speak it; "": the model alone), each once
  type Access = { key: string; harness: string; account: string | null; provider: string | null; problem?: string | null };
  // a model of the chosen access: "" its account's or provider's default
  type Model = { value: string; label: string; problem?: string | null };

  const keyOf = (harness: string, account: string | null, provider: string | null) =>
    account ? `account:${account}` : `provider:${provider}:${harness}`;
  const ready = <T extends { status: string; areas?: string[] }>(list: T[]) => list.filter((x) => x.status === "ready" && allows(agent.area, x.areas));
  // made for its project's area (known once the accounts and providers are loaded)
  const fits = (m: { account?: string | null; provider?: string | null }) =>
    !loaded || allows(agent.area, (m.account ? accounts.find((x) => x.name === m.account) : providers.find((x) => x.name === m.provider))?.areas);
  const hasModel = $derived(!!(agent.model.account || agent.model.provider));
  const ownKey = $derived(keyOf(agent.model.harness ?? "", agent.model.account ?? null, agent.model.provider ?? null));
  const ownOn = (a: Access) => (a.key === ownKey ? [agent.model] : []);
  const accesses = $derived.by((): Access[] => {
    const m = agent.model;
    const own: Access[] = hasModel && fits(m) ? [{ key: ownKey, harness: m.harness ?? "", account: m.account ?? null, provider: m.provider ?? null, problem: m.problem }] : [];
    const listed = (key: string) => own.some((o) => o.key === key);
    if (agent.modelAlone) {
      const alone = ready(providers).filter((p) => p.modelAlone && !listed(keyOf("", null, p.name)));
      return [...own, ...alone.map((p): Access => ({ key: keyOf("", null, p.name), harness: "", account: null, provider: p.name }))];
    }
    return [
      ...own,
      ...ready(accounts)
        .filter((a) => a.harness && !listed(keyOf(a.harness, a.name, null)))
        .map((a): Access => ({ key: keyOf(a.harness ?? "", a.name, null), harness: a.harness ?? "", account: a.name, provider: null })),
      ...ready(providers).flatMap((p) =>
        (p.harnesses ?? [])
          .filter((h) => !listed(keyOf(h, null, p.name)))
          .map((h): Access => ({ key: keyOf(h, null, p.name), harness: h, account: null, provider: p.name })),
      ),
    ];
  });
  // ready or the agent's own, but not made for its project's area
  const theirs = (name: string) => agent.model.account === name || agent.model.provider === name;
  const hidden = $derived([
    ...accounts.filter((a) => (a.status === "ready" || theirs(a.name)) && !allows(agent.area, a.areas)).map((a) => a.name),
    ...providers.filter((p) => (p.status === "ready" || theirs(p.name)) && !allows(agent.area, p.areas)).map((p) => p.name),
  ]);

  const programs = $derived([...new Set(accesses.map((a) => a.harness))]);
  // the programs Handler knows that nothing ready runs here
  const notReady = $derived(agent.modelAlone ? [] : harnesses.list.filter((h) => !programs.includes(h.name)).map((h) => h.product));
  let harness = $state("");
  let key = $state("");
  let model = $state(""); // "": its default
  let forAgent = $state<string | null>(null); // none yet: a new agent's id is ""
  let programOpen = $state(false);
  let accessOpen = $state(false);
  let saving = $state(false);
  let error = $state<string | null>(null);

  const name = $derived(agentLabel(agent));
  const on = $derived(accesses.filter((a) => a.harness === harness));
  const chosen = $derived(accesses.find((a) => a.key === key));

  /** What runs on it, in a word: a subscription, an API key, a model on this computer. */
  function kindOf(a: { account: string | null; provider: string | null }): string {
    if (a.account) return "subscription";
    return providers.find((p) => p.name === a.provider)?.local ? "local" : "API key";
  }

  /** The program's version, from its image: "2.1.280 · updated 3 days ago". */
  function versionOf(h: string): string | null {
    const info = harnesses.list.find((x) => x.name === h);
    const number = info?.version?.match(/\d+\.\d+(\.\d+)?/)?.[0];
    if (!number) return null;
    return info?.builtAt ? `${number} · updated ${ago(info.builtAt)}` : number;
  }

  // what is ready but cannot run the chosen program, greyed with why
  const elsewhere = $derived.by(() => {
    if (!loaded) return [];
    if (agent.modelAlone) return ready(accounts).map((a) => ({ name: a.name, kind: "subscription", why: "needs an API key" }));
    const runs = new Set(on.map((a) => a.account ?? a.provider));
    return [
      ...ready(accounts)
        .filter((a) => a.harness && !runs.has(a.name))
        .map((a) => ({ name: a.name, kind: "subscription", why: `${productName(a.harness ?? "")} only` })),
      ...ready(providers)
        .filter((p) => !runs.has(p.name))
        .map((p) => ({
          name: p.name,
          kind: p.local ? "local" : "API key",
          why: p.harnesses?.length ? `${p.harnesses.map(productName).join(", ")} only` : "the model alone only",
        })),
    ];
  });

  // the models of an access: the agent's own on it, then the provider's others (an account has
  // no list: its default, unless the agent names one)
  function modelsOf(a: Access | undefined): { own: Model[]; others: Model[] } {
    if (!a) return { own: [], others: [] };
    const listed = a.provider ? (providers.find((p) => p.name === a.provider)?.models ?? []).filter((m) => !m.speech).map((m) => m.id) : [];
    const label = (m: string | null | undefined) => m ?? listed[0] ?? "default model";
    const own = ownOn(a).map((m): Model => ({ value: m.model ?? "", label: label(m.model), problem: m.problem }));
    const taken = new Set(own.map((m) => m.label));
    const others = listed.filter((m) => !taken.has(m)).map((m): Model => ({ value: m, label: m }));
    if (!own.length && !others.length) others.push({ value: "", label: "default model" });
    return { own, others };
  }
  const models = $derived(modelsOf(chosen));
  const offered = $derived([...models.own, ...models.others]);
  const modelLabel = $derived(offered.find((m) => m.value === model)?.label ?? "default model");
  const ownLabel = $derived(agent.model.model ?? "its default model");

  /** A provider's models, in short, beside its name: "Sonnet, Opus, Haiku". */
  function shortModels(a: Access): string {
    const ids = a.provider ? (providers.find((p) => p.name === a.provider)?.models ?? []).filter((m) => !m.speech).map((m) => m.id) : [];
    return ids.length > 3 ? `${ids.slice(0, 3).join(", ")}…` : ids.join(", ");
  }

  // the first offered: the agent's own model, unless not for its area
  function reset(): void {
    value = undefined;
    if (own && !hasModel && accesses.length !== 1) {
      [harness, key, model] = ["", "", ""]; // nothing chosen yet: the person chooses
      return;
    }
    harness = accesses[0]?.harness ?? "";
    pickAccess(accesses[0]?.key ?? "");
  }

  // another agent: back to its model
  $effect(() => {
    if (agent.id === forAgent) return;
    forAgent = agent.id;
    reset();
  });
  // own: a model given from outside (a new agent's, as its project's default agent): chosen
  $effect(() => {
    if (own && hasModel && ownKey !== untrack(() => key)) untrack(reset);
  });
  // the chosen one no longer offered (not for the area, known once loaded): the first that is
  $effect(() => {
    if (accesses.length && !accesses.some((a) => a.key === key) && !(own && key === "")) untrack(reset);
  });

  function update(): void {
    if (!chosen) return;
    const picked = { harness: chosen.harness || null, account: chosen.account, provider: chosen.provider, model: model || null };
    if (own) return onchange?.(picked);
    value = sameModel(picked, agent.model) ? undefined : requested(picked);
  }

  function pickHarness(next: string): void {
    harness = next;
    const candidates = accesses.filter((a) => a.harness === next);
    if (own && candidates.length > 1 && !candidates.some((a) => a.key === ownKey)) {
      [key, model] = ["", ""]; // two or more run it: the person chooses, in the next menu
      accessOpen = true;
      return;
    }
    pickAccess(accesses.find((a) => a.harness === next && !a.problem)?.key ?? accesses.find((a) => a.harness === next)?.key ?? "");
  }

  function pickAccess(next: string): void {
    key = next;
    const { own, others } = modelsOf(accesses.find((x) => x.key === next));
    model = (own.find((m) => !m.problem) ?? own[0] ?? others[0])?.value ?? "";
    update();
  }

  function pickModel(next: string): void {
    model = next;
    update();
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

  const programChanged = $derived(!own && !!value && harness !== (agent.model.harness ?? ""));
  const CHIP =
    "chip inline-flex h-7 max-w-full cursor-pointer items-center gap-1.5 rounded-md border bg-transparent px-2 font-sans text-xs text-foreground/85 hover:bg-secondary aria-expanded:ring-2 aria-expanded:ring-primary";
</script>

{#snippet dot()}
  <span class="size-1.5 shrink-0 rounded-full bg-primary" title="Changed for this session only" data-testid="model-choice-changed"></span>
{/snippet}

<div class="flex min-w-0 flex-wrap items-center gap-1.5" data-testid="model-choice">
  {#if !accesses.length && !own}
    <span class="text-xs text-warn" data-testid="model-choice-none">No account or provider made for {agent.area} projects is ready.</span>
  {:else}
    {#if !agent.modelAlone || (own && onalone)}
      <Popover bind:open={programOpen} label="Program" width="20rem" testid="model-choice-programs">
        {#snippet trigger(props)}
          <button type="button" class={CHIP} {...props} aria-label="program" data-testid="model-choice-harness">
            <span class="font-medium">{agent.modelAlone ? "The model alone" : harness ? productName(harness) : "Choose a program"}</span>
            {#if programChanged}{@render dot()}{/if}
            <ChevronDown class="size-3.5 opacity-60" />
          </button>
        {/snippet}
        {#snippet children(close)}
          <p class="menu-group">Program</p>
          {#if agent.modelAlone}
            <button type="button" class="menu-row" onclick={() => (onalone?.(false), close())} data-testid="model-choice-program-agent">
              <span class="radio"></span>
              <span class="min-w-0 flex-1">
                <span class="font-medium">An agent program</span>
                <span class="block text-xs text-muted-foreground">Claude Code, Codex…: it works on files and runs tools, in its sandbox</span>
              </span>
            </button>
          {/if}
          {#each agent.modelAlone ? [] : programs as h (h)}
            {@const count = accesses.filter((a) => a.harness === h).length}
            {@const version = versionOf(h)}
            <button type="button" class="menu-row" aria-pressed={h === harness} onclick={() => (pickHarness(h), close())} data-testid="model-choice-program">
              <span class="radio" class:on={h === harness}></span>
              <span class="min-w-0 flex-1">
                <span class="font-medium">{productName(h)}</span>
                <span class="text-xs text-muted-foreground">{count} ready to run it</span>
                {#if version}<span class="block text-xs text-muted-foreground" data-testid="model-choice-version">{version}</span>{/if}
              </span>
              {#if !own && h === (agent.model.harness ?? "")}<span class="text-[11px] text-muted-foreground">{name}'s</span>{/if}
            </button>
          {/each}
          {#if own && onalone}
            <button type="button" class="menu-row" aria-pressed={agent.modelAlone} onclick={() => (agent.modelAlone || onalone?.(true), close())} data-testid="model-choice-program-alone">
              <span class="radio" class:on={agent.modelAlone}></span>
              <span class="min-w-0 flex-1">
                <span class="font-medium">The model alone</span>
                <span class="block text-xs text-muted-foreground">One model call a turn: no files, no tools, no sandbox. On an API key.</span>
              </span>
            </button>
          {/if}
          {#if notReady.length}
            <p class="menu-foot" data-testid="model-choice-not-ready">
              <span>{notReady.join(", ")}: not ready</span>
              <a class="text-link no-underline hover:underline" href={href({ view: "settings", section: "models" })} onclick={close}>Model access</a>
            </p>
          {/if}
        {/snippet}
      </Popover>
    {/if}
    {#if !accesses.length}
      <span class="text-xs text-warn" data-testid="model-choice-none">{agent.area ? `No account or provider made for ${agent.area} projects is ready` : "No account or provider is ready"}{agent.modelAlone ? " for the model alone" : ""}.</span>
    {:else}
    <Popover bind:open={accessOpen} label="What it runs on" width="30rem" testid="model-choice-runs-on">
      {#snippet trigger(props)}
        <button type="button" class={CHIP} {...props} aria-label="account or provider, and model" data-testid="model-choice-access">
          {#if agent.modelAlone && !(own && onalone)}<span class="text-muted-foreground">the model alone</span>{/if}
          {#if chosen}
            <span class="truncate font-mono">{chosen.account ?? chosen.provider}</span>
            <span class="truncate text-muted-foreground" data-testid="model-choice-model-name">· {modelLabel}</span>
          {:else}
            <span class="text-muted-foreground">{own ? "Choose what it runs on" : "?"}</span>
          {/if}
          {#if value && !programChanged}{@render dot()}{/if}
          <ChevronDown class="size-3.5 shrink-0 opacity-60" />
        </button>
      {/snippet}
      {#snippet children(close)}
        <p class="menu-group">{agent.modelAlone ? "The model alone on" : harness ? `Runs ${productName(harness)} on` : "Runs on"}</p>
        {#each harness || agent.modelAlone ? on : accesses as a (a.key)}
          {@const selected = a.key === key}
          <button type="button" class="menu-row" class:selected aria-pressed={selected} disabled={!!a.problem} onclick={() => ((harness = a.harness), pickAccess(a.key))} data-testid="model-choice-access-row">
            <span class="radio" class:on={selected}></span>
            <span class="min-w-0 flex-1">
              <span class="font-mono">{a.account ?? a.provider}</span>
              <span class="text-xs text-muted-foreground"
                >{kindOf(a)}{#if !selected && shortModels(a)}{" · "}{shortModels(a)}{/if}{#if a.problem}{" · cannot start now"}{/if}</span
              >
            </span>
          </button>
          {#if selected}
            <div class="flex flex-wrap gap-1.5 pt-0.5 pr-2 pb-2 pl-9" role="group" aria-label="model">
              {#each offered as m (m.value)}
                {@const isOwn = models.own.includes(m)}
                <button
                  type="button"
                  class="model-chip"
                  class:on={m.value === model}
                  aria-pressed={m.value === model}
                  disabled={!!m.problem}
                  onclick={() => pickModel(m.value)}
                  title={m.problem ? `Cannot start now: ${m.problem}` : undefined}
                  data-testid="model-choice-model"
                  >{#if m.value === model}<Check class="size-3" />{/if}{m.label}{#if isOwn && !own}<span class="text-[11px] text-muted-foreground">{name}'s</span>{/if}</button
                >
              {/each}
            </div>
          {/if}
        {/each}
        {#each elsewhere as x (x.name)}
          <div class="menu-row off" data-testid="model-choice-elsewhere">
            <span class="radio"></span>
            <span><span class="font-mono">{x.name}</span> <span class="text-xs">{x.kind} · {x.why}</span></span>
          </div>
        {/each}
        <a class="menu-row no-underline" href={href({ view: "settings", section: "models" })} onclick={close}><Plus class="size-3.5 text-primary" />Connect another…</a>
        {#if hidden.length}
          <details class="px-2.5 py-1.5 text-xs text-muted-foreground" data-testid="model-choice-hidden">
            <summary class="cursor-pointer">{hidden.join(", ")} not offered: not for {agent.area} projects</summary>
            {#if own}An agent of this project runs only what is made for its area (Settings → Model access).{:else}To use {hidden.length === 1 ? "it" : "one"} anyway, run <code class="rounded bg-muted px-1">handler run {hidden[0]} --anyway</code> in this folder (it then runs
            outside the project).{/if}
          </details>
        {/if}
        {#if value}
          <div class="menu-foot" data-testid="model-choice-session-only">
            <span class="flex min-w-0 items-center gap-1.5"><Info class="size-3.5 shrink-0" />{modelLabel} for this session only. {name} stays on {ownLabel}.</span>
            {#if ondefault}
              <Button size="sm" variant="outline" disabled={saving} onclick={makeDefault} data-testid="model-choice-make-default">Make {modelLabel} {name}'s default</Button>
            {/if}
          </div>
          {#if error}<p class="px-2.5 pb-1.5 text-xs text-danger">{error}</p>{/if}
        {/if}
      {/snippet}
    </Popover>
    {/if}
  {/if}
</div>

<style>
  /* the terminal's own button style would hide its border */
  .chip {
    border-color: var(--border);
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
  .menu-row:hover:not(:disabled):not(.off),
  .menu-row.selected {
    background: var(--muted);
  }
  .menu-row:disabled,
  .menu-row.off {
    cursor: default;
    opacity: 0.5;
  }
  .radio {
    flex: none;
    width: 15px;
    height: 15px;
    border: 1.5px solid var(--muted-foreground);
    border-radius: 50%;
  }
  .radio.on {
    border: 4.5px solid var(--primary);
  }
  .model-chip {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    height: 28px;
    padding: 0 10px;
    border: 1px solid var(--border);
    border-radius: 7px;
    background: var(--background);
    font-size: 12.5px;
    cursor: pointer;
  }
  .model-chip.on {
    border-color: var(--primary);
    color: var(--primary);
    font-weight: 600;
  }
  .model-chip:disabled {
    cursor: default;
    opacity: 0.5;
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
</style>
