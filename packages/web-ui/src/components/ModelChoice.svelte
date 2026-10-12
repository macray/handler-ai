<script lang="ts">
  // Which model a session runs with (D.1, D.19): one of the agent's (its first by default), or any
  // other account or provider its project's context allows, for this session only: never saved
  // to the agent (another model is not another agent). Those not made for its context are not
  // offered; a line says how many, and how to run one anyway (the terminal only, outside the
  // project). `value`: the model as a request names it; undefined: the agent's first.
  import { accessLabel, accessOf, requested } from "../lib/access";
  import { api } from "../lib/api";
  import { allows, ANY } from "../lib/contexts.svelte";
  import type { AccountInfo, Agent, ModelAccess, ProviderInfo } from "../lib/contracts.gen";
  import * as NativeSelect from "$lib/components/ui/native-select";
  import ContextTag from "./ContextTag.svelte";

  let { agent, value = $bindable() }: { agent: Pick<Agent, "id" | "models" | "context">; value?: ModelAccess } = $props();

  type Choice = { key: string; label: string; model?: ModelAccess; disabled: boolean; contexts: string[] };

  let accounts = $state<AccountInfo[]>([]);
  let providers = $state<ProviderInfo[]>([]);
  Promise.all([api.accounts(), api.providers()]).then(
    ([a, p]) => ((accounts = a), (providers = p)),
    () => {}, // only the agent's own models then
  );

  function madeFor(m: { account?: string | null; provider?: string | null }): string[] {
    const found = m.account ? accounts.find((a) => a.name === m.account) : providers.find((p) => p.name === m.provider);
    return found?.contexts ?? [];
  }

  function label(text: string, contexts: string[]): string {
    return contexts.length ? `${text} — ${contexts.map((c) => (c === ANY ? "any context" : c)).join(", ")}` : text;
  }

  const listed = (name: string) => agent.models.some((m) => m.account === name || m.provider === name);
  const own = $derived(
    agent.models.map(
      (m, i): Choice => ({
        key: `own:${i}`,
        label: label(accessLabel(m), madeFor(m)) + (i === 0 ? " (default)" : "") + (m.problem ? " — cannot start" : ""),
        model: i === 0 ? undefined : requested(accessOf(m)),
        disabled: !!m.problem,
        contexts: madeFor(m),
      }),
    ),
  );
  const others = $derived([
    ...accounts
      .filter((a) => a.status === "ready" && !listed(a.name) && allows(agent.context, a.contexts))
      .map(
        (a): Choice => ({
          key: `account:${a.name}`,
          label: label(accessLabel({ harness: a.harness, account: a.name }), a.contexts ?? []),
          model: { harness: null, account: a.name, provider: null, model: null },
          disabled: false,
          contexts: a.contexts ?? [],
        }),
      ),
    ...providers
      .filter((p) => p.status === "ready" && !listed(p.name) && allows(agent.context, p.contexts))
      .flatMap((p) =>
        (p.harnesses ?? []).map(
          (h): Choice => ({
            key: `provider:${p.name}:${h}`,
            label: label(accessLabel({ harness: h, provider: p.name }), p.contexts ?? []),
            model: { harness: h, account: null, provider: p.name, model: null },
            disabled: false,
            contexts: p.contexts ?? [],
          }),
        ),
      ),
  ]);
  // ready, but not made for its project's context
  const hidden = $derived([
    ...accounts.filter((a) => a.status === "ready" && !allows(agent.context, a.contexts)).map((a) => a.name),
    ...providers.filter((p) => p.status === "ready" && !allows(agent.context, p.contexts)).map((p) => p.name),
  ]);

  let key = $state("own:0");
  let forAgent = $state("");
  // another agent: back to its default
  $effect(() => {
    if (agent.id === forAgent) return;
    forAgent = agent.id;
    key = "own:0";
    value = undefined;
  });

  const chosen = $derived([...own, ...others].find((c) => c.key === key));

  function pick(next: string): void {
    key = next;
    value = [...own, ...others].find((c) => c.key === next)?.model;
  }
</script>

{#if own.length + others.length > 1 || hidden.length}
  <div class="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground" data-testid="model-choice">
    <label class="flex items-center gap-2">
      Run with
      <NativeSelect.Root class="w-auto max-w-96" value={key} onchange={(e) => pick(e.currentTarget.value)} data-testid="model-choice-select">
        <NativeSelect.OptGroup label="Its models">
          {#each own as c (c.key)}<NativeSelect.Option value={c.key} disabled={c.disabled}>{c.label}</NativeSelect.Option>{/each}
        </NativeSelect.OptGroup>
        {#if others.length}
          <NativeSelect.OptGroup label="Another model, for this session only">
            {#each others as c (c.key)}<NativeSelect.Option value={c.key}>{c.label}</NativeSelect.Option>{/each}
          </NativeSelect.OptGroup>
        {/if}
      </NativeSelect.Root>
    </label>
    {#each chosen?.contexts ?? [] as c (c)}<ContextTag name={c} />{/each}
    {#if hidden.length}
      <span class="basis-full" data-testid="model-choice-hidden">
        {hidden.join(", ")} {hidden.length === 1 ? "is" : "are"} hidden here because {hidden.length === 1 ? "it isn't" : "they aren't"} set up for {agent.context} projects.
        To use {hidden.length === 1 ? "it" : "one"} anyway, run <code class="rounded bg-muted px-1">handler run {hidden[0]} --anyway</code> in this folder
        (it then runs outside the project).
      </span>
    {/if}
  </div>
{/if}
