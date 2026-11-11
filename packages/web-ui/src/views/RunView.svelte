<script lang="ts">
  // A run of an agent with an interface (D.18): what it was given, how it went, and its result,
  // shown from its schema. Polled while it runs; watching it live opens its session. Titled by what
  // it was given; run again with the same input and model; a job's run that ended well can be kept
  // as a check (D.20).
  import When from "../components/When.svelte";
  import Eye from "@lucide/svelte/icons/eye";
  import RotateCcw from "@lucide/svelte/icons/rotate-ccw";
  import Target from "@lucide/svelte/icons/target";
  import CheckDialog from "../components/CheckDialog.svelte";
  import Trash from "@lucide/svelte/icons/trash-2";
  import X from "@lucide/svelte/icons/x";
  import { Button } from "$lib/components/ui/button";
  import * as Collapsible from "$lib/components/ui/collapsible";
  import OutputView from "../components/OutputView.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import StatusBadge from "../components/StatusBadge.svelte";
  import { api } from "../lib/api";
  import type { Agent, Session } from "../lib/contracts.gen";
  import { agentLabel, projects } from "../lib/projects.svelte";
  import { href, navigate } from "../lib/router.svelte";
  import { accessLabel } from "../lib/access";
  import { inputSummary, runState, startedBy, verdictOf, type Schema } from "../lib/runs";

  let { id }: { id: string } = $props();

  let run = $state<Session | null>(null);
  let agent = $state<Agent | null>(null);
  let digest = $state<string | null>(null); // the subject skill's, now
  let error = $state<string | null>(null);

  const status = $derived(run ? runState(run) : "running");
  const skill = $derived(run?.subject?.skill ?? undefined);
  const result = $derived(agent?.interface?.result as Schema | undefined);
  const verdict = $derived(run?.output ? verdictOf(result, run.output.value) : null);
  const changed = $derived(Boolean(digest && run?.subject && digest !== run.subject.digest));
  const found = $derived(agent ? projects.of(agent) : undefined);
  const title = $derived(run ? (inputSummary(run) ?? run.title ?? "Run") : "Run");
  const parent = $derived(
    agent
      ? { label: found ? `${found.project.name} · ${agentLabel(found.agent)}` : agentLabel(agent), href: href({ view: "agent", id: agent.id }) }
      : undefined,
  );

  async function refresh(): Promise<void> {
    try {
      run = await api.session(id);
      if (!agent) agent = await api.agent(run.agentId).catch(() => null);
    } catch (e) {
      error = (e as Error).message;
    }
  }

  $effect(() => {
    void refresh();
  });

  $effect(() => {
    if (status !== "running") return;
    const timer = setInterval(refresh, 1500);
    return () => clearInterval(timer);
  });

  $effect(() => {
    if (!skill) return;
    api.skill(skill).then(
      (s) => (digest = s.digest ?? null),
      () => (digest = null),
    );
  });

  async function again(): Promise<void> {
    if (!run || !agent) return;
    error = null;
    try {
      const input = { fields: run.input?.fields ?? {} };
      const model = { harness: run.harness, account: run.account ?? null, provider: run.provider ?? null, model: run.model ?? null };
      navigate({ view: "run", id: (await api.startRun(agent.id, input, model)).id });
    } catch (e) {
      error = (e as Error).message;
    }
  }

  // kept as a check (D.20): what may be compared comes from its agent's checks
  let keeping = $state(false);
  let comparable = $state<string[]>([]);
  let kept = $state(false);
  const keepable = $derived(status === "done" && !!agent?.interface?.result && run?.origin !== "check" && !!run?.output?.valid);
  async function keep(): Promise<void> {
    if (!agent) return;
    try {
      comparable = (await api.agentChecks(agent.id)).comparable ?? [];
      keeping = true;
    } catch (e) {
      error = (e as Error).message;
    }
  }

  /** A run waiting for its turn, not started after all. */
  async function cancel(): Promise<void> {
    if (!run) return;
    try {
      run = await api.cancelSession(run.id);
    } catch (e) {
      error = (e as Error).message;
    }
  }

  async function remove(): Promise<void> {
    if (!run || !confirm("Delete this run, its result and its conversation?")) return;
    const back = agent ? { view: "agent" as const, id: agent.id } : { view: "projects" as const };
    await api.deleteSession(run.id);
    navigate(back, true);
  }

  const STATE: Record<string, string> = { running: "running", done: "succeeded", invalid: "failed", "no result": "failed" };
  const TONE = {
    ok: "border-ok/40 bg-ok/10 text-ok",
    warn: "border-warn/40 bg-warn/10 text-warn",
    danger: "border-danger/40 bg-danger/10 text-danger",
    muted: "border-border bg-muted text-muted-foreground",
  };
</script>

<PageHeader width="max-w-4xl" {title} {parent}>
  {#snippet actions()}
    {#if run?.waitingFor}
      <Button variant="ghost" size="sm" onclick={cancel} title="It will not start" data-testid="run-cancel"><X />Cancel</Button>
    {:else if run}
      <Button variant="ghost" size="sm" href={href({ view: "session", key: run.id })} title={status === "running" ? "Its conversation, live" : "Its conversation: restarts its sandbox to show it"} data-testid="run-watch">
        <Eye />{status === "running" ? "Watch" : "Conversation"}
      </Button>
    {/if}
    {#if run}
      {#if status !== "running" && agent}
        <Button variant="ghost" size="sm" onclick={again} title="A new run with the same input and model" data-testid="run-again"><RotateCcw />Run again</Button>
      {/if}
      {#if keepable && !kept}
        <Button variant="ghost" size="sm" onclick={keep} title="This answer is right: run it again later to see it still comes" data-testid="run-keep-check"><Target />Keep as a check</Button>
      {/if}
      {#if status !== "running"}
        <Button variant="ghost" size="sm" class="text-destructive hover:text-destructive" onclick={remove} data-testid="run-delete"><Trash />Delete</Button>
      {/if}
    {/if}
  {/snippet}
</PageHeader>
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-4xl space-y-8 px-8 py-10">
        {#if error}<p class="text-sm text-danger">{error}</p>{/if}
    {#if run}
      {#if kept && agent}
        <p class="text-sm" data-testid="run-kept">Kept as a check: <a class="text-link hover:underline" href={href({ view: "agent", id: agent.id })}>its checks</a>.</p>
      {/if}
      <section class="flex flex-wrap items-center gap-3 text-sm" data-testid="run-status">
        <StatusBadge status={STATE[status] ?? "failed"} />
        {#if verdict}
          <span class="text-muted-foreground">Verdict</span>
          <span class="inline-flex rounded-md border px-2 py-0.5 text-xs font-medium {TONE[verdict.tone]}" data-testid="run-verdict">{verdict.value}</span>
        {/if}
        <span class="text-xs text-muted-foreground"><When at={run.createdAt} /> · {startedBy(run)} · {accessLabel(run)}</span>
      </section>

      <section class="space-y-3">
        <h2 class="text-base font-semibold">Given</h2>
        {#if skill}
          <p class="text-sm">
            The skill <a class="text-link hover:underline" href={href({ view: "skill", name: skill })}>{skill}</a>, read-only.
            {#if changed}<span class="text-warn" data-testid="run-changed">Its files changed since this run read them: the result may not hold any more.</span>{/if}
          </p>
        {/if}
        {#if run.input?.fields && Object.keys(run.input.fields).length}
          <OutputView schema={agent?.interface?.fields as Schema | undefined} value={run.input.fields} />
        {:else if !skill}
          <p class="text-sm text-muted-foreground">Nothing.</p>
        {/if}
      </section>

      <section class="space-y-3" data-testid="run-result">
        <h2 class="text-base font-semibold">Result</h2>
        {#if run.waitingFor}
          <p class="text-sm text-muted-foreground" data-testid="run-waiting">
            It waits for <a class="text-link hover:underline" href={href({ view: "run", id: run.waitingFor })}>the run of its agent in progress</a>: one run of an agent at a time.
            It starts when that one ends, and gives up after 30 minutes.
          </p>
        {:else if status === "running"}
          <p class="text-sm text-muted-foreground">It is working{run.busy ? "" : " (starting)"}… Watch it live from the top bar.</p>
        {:else if run.output?.valid}
          <OutputView schema={result} value={run.output.value} {skill} />
          {#if skill}
            <p class="text-xs text-muted-foreground">The lines shown are read from the skill now, not quoted by the agent. Its verdict advises: check what it points at.</p>
          {/if}
        {:else if run.output}
          <p class="text-sm text-danger">Its result does not match what its interface asks for: {run.output.error}</p>
          {#if run.output.value !== undefined && run.output.value !== null}
            <pre class="overflow-x-auto rounded-md border bg-muted p-3 text-xs">{JSON.stringify(run.output.value, null, 2)}</pre>
          {/if}
        {:else}
          <p class="text-sm text-danger">No result: {run.error ?? (run.lastStopReason ? `its turn ended (${run.lastStopReason.replaceAll("_", " ")})` : "it did not run")}.</p>
        {/if}
      </section>

      {#if run.answer}
        <Collapsible.Root>
          <Collapsible.Trigger class="text-sm text-muted-foreground hover:text-foreground">Its final message ▸</Collapsible.Trigger>
          <Collapsible.Content>
            <pre class="mt-2 max-h-96 overflow-y-auto rounded-md border bg-muted p-3 text-xs whitespace-pre-wrap">{run.answer}</pre>
          </Collapsible.Content>
        </Collapsible.Root>
      {/if}
    {:else if !error}
      <p class="text-sm text-muted-foreground">Loading…</p>
    {/if}
  </div>
</div>

{#if agent && run && keeping}
  <CheckDialog
    bind:open={keeping}
    agentId={agent.id}
    result={agent.interface?.result as Schema | undefined}
    {comparable}
    answer={(run.output?.value ?? {}) as Record<string, unknown>}
    fromRun={run.id}
    name={title}
    onsaved={() => (kept = true)}
  />
{/if}
