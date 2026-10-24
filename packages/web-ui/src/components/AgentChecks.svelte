<script lang="ts">
  // A job's checks (D.20), on its page: how many pass and since what change, Run all, and each
  // check (its name, its input, what it compares, its last result; changed, deleted, its run
  // opened). Run when the person asks, never on their own. Polled while a check run goes on.
  // *Improve until they pass* (D.21) starts an improvement, followed under the block.
  import CircleCheck from "@lucide/svelte/icons/circle-check";
  import CircleDashed from "@lucide/svelte/icons/circle-dashed";
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import Play from "@lucide/svelte/icons/play";
  import ShieldAlert from "@lucide/svelte/icons/shield-alert";
  import Target from "@lucide/svelte/icons/target";
  import { Button } from "$lib/components/ui/button";
  import { api } from "../lib/api";
  import type { Agent, AgentChecks, Check, CheckResult } from "../lib/contracts.gen";
  import { href } from "../lib/router.svelte";
  import { fieldsOf, type Schema } from "../lib/runs";
  import Sparkles from "@lucide/svelte/icons/sparkles";
  import AgentImprovement from "./AgentImprovement.svelte";
  import CheckDialog from "./CheckDialog.svelte";
  import ImproveDialog from "./ImproveDialog.svelte";

  let { agent, onchanged }: { agent: Agent; onchanged?: () => void } = $props();
  let improving = $state(false); // the dialog
  let improvement = $state(0); // a new improvement started: its block loads it

  let data = $state<AgentChecks | null>(null);
  let error = $state<string | null>(null);
  let editing = $state<Check | null>(null);
  let dialogOpen = $state(false);

  const result = $derived(agent.interface?.result as Schema | undefined);
  const titles = $derived(Object.fromEntries(fieldsOf(result).map((f) => [f.key, f.title])));
  const running = $derived(!!data?.last && !data.last.endedAt);
  const resultOf = (c: Check): CheckResult | undefined => data?.last?.results.find((r) => r.checkId === c.id);
  const ended = $derived(data?.last?.results.filter((r) => r.state === "passed" || r.state === "failed" || r.state === "error") ?? []);
  const passed = $derived(ended.filter((r) => r.state === "passed").length);
  const inputLine = (c: Check) =>
    Object.values(c.input ?? {})
      .map((v) => (typeof v === "string" ? v : JSON.stringify(v)))
      .join(" · ");

  async function load(): Promise<void> {
    try {
      data = await api.agentChecks(agent.id);
    } catch (e) {
      error = (e as Error).message;
    }
  }

  $effect(() => {
    void agent.id;
    void load();
  });
  $effect(() => {
    if (!running) return;
    const timer = setInterval(load, 1000);
    return () => clearInterval(timer);
  });

  async function runAll(): Promise<void> {
    error = null;
    try {
      await api.runChecks(agent.id);
      await load();
    } catch (e) {
      error = (e as Error).message;
    }
  }

  async function remove(c: Check): Promise<void> {
    if (!confirm(`Delete the check "${c.name}"?`)) return;
    await api.deleteCheck(agent.id, c.id);
    await load();
  }

  function change(c: Check): void {
    editing = c;
    dialogOpen = true;
  }
</script>

<section class="overflow-hidden rounded-[10px] border bg-card shadow-panel" data-testid="agent-checks">
  <header class="flex flex-wrap items-center gap-2 border-b px-3.5 py-2.5">
    <h3 class="flex items-center gap-2 text-sm font-semibold"><Target class="size-4 text-muted-foreground" />Checks</h3>
    {#if data?.last && data.checks.length}
      <span class="text-xs {passed === ended.length && !running ? 'text-ok' : 'text-warn'}" data-testid="checks-summary">
        {#if running}running, {ended.length} of {data.last.results.length} done{:else}{passed} of {ended.length} pass{/if}
      </span>
    {/if}
    <Button size="sm" variant="outline" class="ml-auto" disabled={running || !data?.checks.some((c) => !c.problem)} onclick={runAll} data-testid="checks-run"><Play />Run all</Button>
    <Button size="sm" variant="outline" disabled={running || !data?.checks.some((c) => !c.problem)} onclick={() => (improving = true)} data-testid="checks-improve"><Sparkles />Improve until they pass</Button>
  </header>
  {#if data?.changed?.length}
    <p class="flex items-center gap-1.5 border-b bg-warn/5 px-3.5 py-2 text-xs text-warn" data-testid="checks-changed">
      <ShieldAlert class="size-3.5" />Not run since you changed {data.changed.join(" and ")}.
    </p>
  {/if}
  {#if data && !data.checks.length}
    <p class="px-3.5 py-3 text-xs text-muted-foreground">
      No check yet. Open a run whose answer is right and <span class="font-medium">Keep as a check</span>: Run all runs it again and says if the same
      answer still comes.
    </p>
  {:else if data}
    <ul class="divide-y">
      {#each data.checks as c (c.id)}
        {@const r = resultOf(c)}
        <li class="grid grid-cols-[1rem_1fr_auto] items-start gap-x-2.5 px-3.5 py-2.5 text-sm {r?.state === 'failed' || r?.state === 'error' ? 'bg-warn/5' : ''}" data-testid="check-row">
          {#if c.problem}<ShieldAlert class="mt-0.5 size-4 text-muted-foreground" />
          {:else if !r}<CircleDashed class="mt-0.5 size-4 text-muted-foreground" />
          {:else if r.state === "passed"}<CircleCheck class="mt-0.5 size-4 text-ok" />
          {:else if r.state === "running" || r.state === "waiting"}<LoaderCircle class="mt-0.5 size-4 animate-spin text-muted-foreground" />
          {:else}<ShieldAlert class="mt-0.5 size-4 text-warn" />{/if}
          <div class="min-w-0 space-y-0.5">
            <p class="font-medium">{c.name}</p>
            <p class="truncate text-xs text-muted-foreground" title={inputLine(c)}>{inputLine(c) || "no input"}</p>
            <p class="text-xs text-muted-foreground">the same: {c.compare.map((k) => `${titles[k] ?? k} (${JSON.stringify(c.answer[k])})`).join(", ")}</p>
            {#if c.problem}<p class="text-xs text-muted-foreground" data-testid="check-problem">Cannot run: {c.problem}.</p>
            {:else if r?.state === "passed"}<p class="text-xs text-ok" data-testid="check-state">passes</p>
            {:else if r?.state === "failed" || r?.state === "error"}<p class="text-xs text-warn" data-testid="check-state">{r.state === "failed" ? "came back: " : ""}{r.why}</p>
            {:else if r}<p class="text-xs text-muted-foreground" data-testid="check-state">{r.state}…</p>{/if}
          </div>
          <div class="flex items-center gap-1">
            {#if r?.sessionId && r.state !== "waiting"}<Button variant="ghost" size="sm" href={href({ view: "run", id: r.sessionId })}>Its run</Button>{/if}
            <Button variant="ghost" size="sm" onclick={() => change(c)} data-testid="check-change">Change</Button>
            <Button variant="ghost" size="sm" class="text-destructive hover:text-destructive" onclick={() => remove(c)} data-testid="check-delete">Delete</Button>
          </div>
        </li>
      {/each}
    </ul>
  {/if}
  {#if error}<p class="border-t px-3.5 py-2 text-xs text-danger">{error}</p>{/if}
  <p class="border-t px-3.5 py-2 text-xs text-muted-foreground">Run when you ask, never on their own; kept with the agent.</p>
</section>

{#if editing && data}
  {#key editing.id}
    <CheckDialog bind:open={dialogOpen} agentId={agent.id} {result} comparable={data.comparable ?? []} answer={editing.answer} check={editing} onsaved={() => void load()} />
  {/key}
{/if}

{#key improvement}
  <AgentImprovement
    {agent}
    onkept={() => {
      void load();
      onchanged?.();
    }}
  />
{/key}
<ImproveDialog bind:open={improving} agentId={agent.id} checks={data?.checks.filter((c) => !c.problem).length ?? 0} onstarted={() => (improvement += 1)} />
