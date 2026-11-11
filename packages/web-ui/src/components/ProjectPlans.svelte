<script lang="ts">
  // A project's Plans tab (D.27): New plan first, with who writes it (the plan builder, a helper:
  // its program and model, linking to Settings → Helpers); the plans working in its folder, a
  // card each: one that runs lists its steps (done: what it did; running: its session and the
  // time used; waiting: its Done when), one that stopped shows why on its step with the fix there
  // (the hosts refused allowed and run again, or kept blocked; else run again from that step);
  // then the plans being written (drafts); the finished ones folded.
  import Check from "@lucide/svelte/icons/check";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import RotateCcw from "@lucide/svelte/icons/rotate-ccw";
  import { Button } from "$lib/components/ui/button";
  import { api } from "../lib/api";
  import type { PlanDraft, PlanStepView, PlanView, Project } from "../lib/contracts.gen";
  import { limit, restartable } from "../lib/plans";
  import { decideHosts } from "../lib/projects.svelte";
  import { href } from "../lib/router.svelte";
  import LoadingCards from "./LoadingCards.svelte";
  import HelperLink from "./HelperLink.svelte";
  import NewPlan from "./NewPlan.svelte";
  import PlanDraftList from "./PlanDraftList.svelte";
  import RefusedHosts from "./RefusedHosts.svelte";
  import When from "./When.svelte";

  let { project }: { project: Project } = $props();

  let plans = $state<PlanView[] | null>(null);
  let drafts = $state<PlanDraft[]>([]);
  let error = $state<string | null>(null);
  let busy = $state(false);

  async function load(): Promise<void> {
    try {
      [plans, drafts] = await Promise.all([api.plans(project.id), api.planDrafts(project.id)]);
      error = null;
    } catch (e) {
      error = (e as Error).message;
    }
  }

  $effect(() => {
    void load();
    const timer = setInterval(load, 5000); // their steps go on
    return () => clearInterval(timer);
  });

  const current = $derived((plans ?? []).filter((p) => p.state !== "done"));
  const finished = $derived((plans ?? []).filter((p) => p.state === "done"));

  async function act(action: () => Promise<unknown>): Promise<void> {
    busy = true;
    error = null;
    try {
      await action();
      await load();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  /** "32 min", "1 h 5 min": between two times, or since one. */
  function span(from: string, to?: string | null): string {
    const minutes = Math.max(0, Math.round(((to ? Date.parse(to) : Date.now()) - Date.parse(from)) / 60000));
    return minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)} h${minutes % 60 ? ` ${minutes % 60} min` : ""}`;
  }

  /** The step it stopped at: the first one not done. */
  const stoppedAt = (p: PlanView): PlanStepView | undefined => p.steps.find((s) => s.state !== "done");
  const doneCount = (p: PlanView) => p.steps.filter((s) => s.state === "done").length;
  const runningStep = (p: PlanView) => p.steps.find((s) => s.state === "running");
</script>

<div class="flex flex-wrap items-start gap-3">
  <p class="py-1.5 text-sm text-muted-foreground" data-testid="plans-builder">
    <HelperLink need="plan-builder" />
  </p>
  <div class="ml-auto has-[[data-testid=helper-card]]:w-full"><NewPlan project={project.id} /></div>
</div>
{#if error}<p class="text-sm text-danger" data-testid="plans-error">{error}</p>{/if}

{#if !plans}
  <div class="space-y-3"><LoadingCards count={2} height="h-20" /></div>
{:else}
  {#each current as p (p.id)}
    {@const stopped = p.state === "stopped"}
    {@const at = stoppedAt(p)}
    <section class="overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel {stopped ? 'border-danger/30' : ''}" data-testid="plan-card">
      <header class="flex flex-wrap items-center gap-2 px-4 py-3 {stopped ? '' : 'border-b'}">
        <a class="font-semibold text-foreground no-underline hover:underline" href={href({ view: "plan", id: p.id })}>{p.title}</a>
        <span class="fact rounded bg-muted px-1.5 py-px text-xs">{p.agent ?? "its agent was deleted"}</span>
        <span class="ml-auto flex items-center gap-3">
          {#if stopped}
            <span class="text-danger" data-testid="plan-stopped-at">Stopped at step {at?.n ?? p.steps.length} of {p.steps.length}</span>
          {:else}
            <span class="text-xs text-muted-foreground">step {(runningStep(p)?.n ?? doneCount(p) + 1)} of {p.steps.length}</span>
            <span class="h-1.5 w-28 overflow-hidden rounded-full bg-muted"><span class="block h-full bg-primary" style="width:{(doneCount(p) / p.steps.length) * 100}%"></span></span>
            <Button size="sm" variant="ghost" disabled={busy} onclick={() => act(() => api.cancelPlan(p.id))} data-testid="plan-cancel">Cancel</Button>
          {/if}
        </span>
      </header>
      {#if stopped && at}
        {@const again = restartable(p).includes(at.n)}
        <div class="space-y-2 px-4 pb-3.5" data-testid="plan-stopped">
          <p class="flex items-center gap-2.5">
            <span class="step-n fail">{at.n}</span><span class="font-medium">{at.title}</span>
          </p>
          <div class="space-y-2 pl-8">
            {#if at.refused?.length}
              <RefusedHosts
                hosts={at.refused}
                said={at.said}
                {busy}
                again={again ? `Allow it and run again from step ${at.n}` : null}
                onallow={(hosts) => act(() => (again ? api.runPlan(p.id, at.n, hosts) : decideHosts(p.agentId, hosts, "allow")))}
                onkeep={(hosts) => act(() => decideHosts(p.agentId, hosts, "blocked"))}
              />
            {:else}
              <p class="text-muted-foreground">{at.error ?? p.stoppedBecause}</p>
            {/if}
            <div class="flex flex-wrap gap-2">
              {#if again && !at.refused?.length}
                <Button size="sm" disabled={busy} onclick={() => act(() => api.runPlan(p.id, at.n))} data-testid="plan-run-again"><RotateCcw />Run again from step {at.n}</Button>
              {/if}
              {#if at.sessionId}<Button size="sm" variant="ghost" href={href({ view: "session", key: at.sessionId })} data-testid="plan-step-session">Its session</Button>{/if}
            </div>
          </div>
        </div>
      {:else}
        <ol class="divide-y">
          {#each p.steps as step (step.n)}
            <li class="grid grid-cols-[1.5rem_1fr_auto] items-center gap-x-3 gap-y-0.5 px-4 py-2.5" data-testid="plan-step">
              <span class="step-n {step.state === 'done' ? 'done' : step.state === 'running' ? 'run' : ''}">{#if step.state === "done"}<Check class="size-3" />{:else}{step.n}{/if}</span>
              <span class="font-medium {step.state === 'waiting' ? 'text-muted-foreground' : ''}">{step.title}</span>
              <span class="row-span-2 text-xs text-muted-foreground">
                {#if step.state === "running" && step.sessionId}
                  <Button size="sm" variant="outline" href={href({ view: "session", key: step.sessionId })} data-testid="plan-step-session">Its session<ChevronRight /></Button>
                {:else if step.state === "done" && step.startedAt}
                  {span(step.startedAt, step.endedAt)}
                {/if}
              </span>
              <span class="col-start-2 text-xs text-muted-foreground">
                {#if step.state === "done"}
                  Done: {step.summary ?? "no summary"}{#if step.notes}{" · notes for the next steps"}{/if}
                {:else if step.state === "running"}
                  Running{#if step.startedAt}{" · "}{span(step.startedAt)} of {limit(p.stepTimeoutSec)}{/if}
                {:else}
                  Done when: {step.doneWhen}
                {/if}
              </span>
            </li>
          {/each}
        </ol>
      {/if}
    </section>
  {/each}

  {#if drafts.length}
    <section class="space-y-2">
      <h2 class="section-label">Being written</h2>
      <PlanDraftList {drafts} ongone={() => void load()} />
    </section>
  {/if}

  {#if finished.length}
    <details class="group" data-testid="plans-finished">
      <summary class="section-label flex cursor-pointer items-center gap-1.5"><ChevronRight class="size-3.5 transition-transform group-open:rotate-90" />Finished <span class="text-muted-foreground">{finished.length}</span></summary>
      <ul class="mt-2 divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
        {#each finished as p (p.id)}
          <li>
            <a class="flex items-center gap-3 px-4 py-2.5 text-foreground no-underline hover:bg-muted/40" href={href({ view: "plan", id: p.id })} data-testid="plan-finished">
              <span class="min-w-0 flex-1 truncate font-medium">{p.title}</span>
              <span class="fact text-xs text-muted-foreground">{p.steps.length} steps · {p.agent ?? "its agent was deleted"} · approved <When at={p.approvedAt} /></span>
            </a>
          </li>
        {/each}
      </ul>
    </details>
  {/if}

  {#if !current.length && !drafts.length && !finished.length}
    <div class="rounded-[10px] border border-dashed px-6 py-10 text-center text-sm text-muted-foreground" data-testid="no-plan">
      No plan yet. <em>New plan</em>: the plan builder reads the project, asks what you want done, and writes the steps for you to review.
    </div>
  {/if}
{/if}

<style>
  .step-n {
    display: grid;
    width: 22px;
    height: 22px;
    place-items: center;
    border-radius: 50%;
    background: var(--muted);
    color: var(--muted-foreground);
    font-size: 11px;
    font-weight: 600;
  }
  .step-n.done {
    background: color-mix(in oklab, var(--ok) 15%, transparent);
    color: var(--ok);
  }
  .step-n.run {
    background: color-mix(in oklab, var(--primary) 14%, transparent);
    color: var(--primary);
  }
  .step-n.fail {
    background: color-mix(in oklab, var(--danger) 12%, transparent);
    color: var(--danger);
  }
</style>
