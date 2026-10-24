<script lang="ts">
  // Which model a session or a run starts with (D.1, D.19), as a sentence: "in [program] on
  // [account or provider] with [model]". Each list is short and names one thing: the programs;
  // the accounts and providers that run the chosen one, each once (the agent's own first); the
  // models of the chosen one, the agent's own first, under its name. The agent's model by
  // default; another is for this session only, never saved to the agent (another model
  // is not another agent), and not said again beside it: the list shows whose is whose. Accounts and providers not made for its project's area are not
  // offered, the agent's own included (an account's areas may have changed since): a line says
  // which, and how to run one anyway (the terminal only, outside the project). `value`: the
  // model as a request names it; undefined: the agent's. An agent on the model alone (D.18)
  // reads "the model alone on [provider] [model]": its program is "" here, and only the providers
  // handlerd can call are offered.
  import { untrack } from "svelte";
  import { requested, sameModel } from "../lib/access";
  import { api } from "../lib/api";
  import { allows } from "../lib/areas.svelte";
  import type { AccountInfo, Agent, ModelAccess, ProviderInfo } from "../lib/contracts.gen";
  import { productName } from "../lib/harnesses.svelte";
  import { agentLabel } from "../lib/projects.svelte";
  import * as NativeSelect from "$lib/components/ui/native-select";

  let { agent, value = $bindable() }: { agent: Pick<Agent, "id" | "name" | "model" | "area" | "modelAlone">; value?: ModelAccess } = $props();

  let accounts = $state<AccountInfo[]>([]);
  let providers = $state<ProviderInfo[]>([]);
  let loaded = $state(false);
  Promise.all([api.accounts(), api.providers()]).then(
    ([a, p]) => ((accounts = a), (providers = p), (loaded = true)),
    () => {}, // only the agent's own model then
  );

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
  const ownKey = $derived(keyOf(agent.model.harness ?? "", agent.model.account ?? null, agent.model.provider ?? null));
  const ownOn = (a: Access) => (a.key === ownKey ? [agent.model] : []);
  const accesses = $derived.by((): Access[] => {
    const m = agent.model;
    const own: Access[] = fits(m) ? [{ key: ownKey, harness: m.harness ?? "", account: m.account ?? null, provider: m.provider ?? null, problem: m.problem }] : [];
    const listed = (key: string) => own.some((o) => o.key === key);
    if (agent.modelAlone) {
      const alone = ready(providers).filter((p) => p.modelAlone && !listed(keyOf("", null, p.name)));
      return [...own, ...alone.map((p): Access => ({ key: keyOf("", null, p.name), harness: "", account: null, provider: p.name }))];
    }
    return [
      ...own,
      ...ready(accounts)
        .filter((a) => a.harness && !listed(keyOf(a.harness, a.name, null)))
        .map((a): Access => ({ key: keyOf(a.harness ?? "", a.name, null), harness: a.harness ?? "", account: a.name, provider: null})),
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
  let harness = $state("");
  let key = $state("");
  let model = $state(""); // "": its default
  let forAgent = $state("");

  const name = $derived(agentLabel(agent));
  const on = $derived(accesses.filter((a) => a.harness === harness));
  const chosen = $derived(accesses.find((a) => a.key === key));

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

  // the first offered: the agent's own model, unless not for its area
  function reset(): void {
    value = undefined;
    harness = accesses[0]?.harness ?? "";
    pickAccess(accesses[0]?.key ?? "");
  }

  // another agent: back to its model
  $effect(() => {
    if (agent.id === forAgent) return;
    forAgent = agent.id;
    reset();
  });
  // the chosen one no longer offered (not for the area, known once loaded): the first that is
  $effect(() => {
    if (accesses.length && !accesses.some((a) => a.key === key)) untrack(reset);
  });

  function update(): void {
    if (!chosen) return;
    const picked = { harness: chosen.harness || null, account: chosen.account, provider: chosen.provider, model: model || null };
    value = sameModel(picked, agent.model) ? undefined : requested(picked);
  }

  function pickHarness(next: string): void {
    harness = next;
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
</script>

{#snippet options(list: Model[])}
  {#each list as m (m.value)}<NativeSelect.Option value={m.value} disabled={!!m.problem}>{m.label}{m.problem ? " (cannot start now)" : ""}</NativeSelect.Option>{/each}
{/snippet}

<div class="flex min-w-0 flex-wrap items-center gap-1.5 font-mono text-xs" data-testid="model-choice">
  {#if !accesses.length}
    <span class="font-sans text-warn" data-testid="model-choice-none">No account or provider made for {agent.area} projects is ready.</span>
  {:else}
  {#if harness === ""}
    <span class="font-medium">the model alone</span>
  {:else}
  <span class="text-muted-foreground">in</span>
  {#if programs.length > 1}
    <NativeSelect.Root class="h-8 w-auto text-xs" value={harness} onchange={(e) => pickHarness(e.currentTarget.value)} aria-label="program" data-testid="model-choice-harness">
      {#each programs as h (h)}<NativeSelect.Option value={h}>{productName(h)}</NativeSelect.Option>{/each}
    </NativeSelect.Root>
  {:else}
    <span class="font-medium">{productName(harness)}</span>
  {/if}
  {/if}
  <span class="text-muted-foreground">on</span>
  {#if on.length > 1}
    <NativeSelect.Root class="h-8 w-auto text-xs" value={key} onchange={(e) => pickAccess(e.currentTarget.value)} aria-label="account or provider" data-testid="model-choice-access">
      {#each on as a (a.key)}<NativeSelect.Option value={a.key} disabled={!!a.problem}>{a.account ?? a.provider}{a.problem ? " (cannot start now)" : ""}</NativeSelect.Option>{/each}
    </NativeSelect.Root>
  {:else}
    <span class="font-medium">{chosen?.account ?? chosen?.provider ?? "?"}</span>
  {/if}
  <span class="text-muted-foreground">with</span>
  {#if offered.length > 1}
    <NativeSelect.Root class="h-8 w-auto text-xs" value={model} onchange={(e) => pickModel(e.currentTarget.value)} aria-label="model" data-testid="model-choice-model">
      {#if models.own.length && models.others.length}
        <NativeSelect.OptGroup label="{name}'s model">{@render options(models.own)}</NativeSelect.OptGroup>
        <NativeSelect.OptGroup label="other {chosen?.provider} models">{@render options(models.others)}</NativeSelect.OptGroup>
      {:else}
        {@render options(offered)}
      {/if}
    </NativeSelect.Root>
  {:else}
    <span class="font-medium" data-testid="model-choice-model-name">{offered[0]?.label}</span>
  {/if}
  {/if}
  {#if hidden.length}
    <details class="basis-full text-xs text-muted-foreground" data-testid="model-choice-hidden">
      <summary class="cursor-pointer">{hidden.join(", ")} not offered: not for {agent.area} projects</summary>
      To use {hidden.length === 1 ? "it" : "one"} anyway, run <code class="rounded bg-muted px-1">handler run {hidden[0]} --anyway</code> in this folder
      (it then runs outside the project).
    </details>
  {/if}
</div>
