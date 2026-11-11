<script lang="ts">
  // One plan (D.27): Handler's copy of what you approved, its steps one after another with their
  // state, summary and session; why it stopped; Cancel (the step running stops), Run again from a
  // step (once stopped or done, up to its first step not done), Delete (its sessions stay) and
  // Edit as a new draft (its text copied into a draft of its project: approved, a new plan).
  import ExternalLink from "@lucide/svelte/icons/external-link";
  import FilePen from "@lucide/svelte/icons/file-pen";
  import RotateCcw from "@lucide/svelte/icons/rotate-ccw";
  import Trash from "@lucide/svelte/icons/trash-2";
  import X from "@lucide/svelte/icons/x";
  import { Button } from "$lib/components/ui/button";
  import Dialog from "../components/Dialog.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import RefusedHosts from "../components/RefusedHosts.svelte";
  import StatusBadge from "../components/StatusBadge.svelte";
  import When from "../components/When.svelte";
  import { api } from "../lib/api";
  import type { PlanView } from "../lib/contracts.gen";
  import { limit, restartable, stepsDone } from "../lib/plans";
  import { decideHosts, projects } from "../lib/projects.svelte";
  import { href, navigate } from "../lib/router.svelte";

  let { id }: { id: string } = $props();

  let plan = $state<PlanView | null>(null);
  let error = $state<string | null>(null);
  let busy = $state(false);
  let deleting = $state(false);
  const again = $derived(plan ? restartable(plan) : []);
  // the project it works in: its page's Plans tab is where it is listed
  const project = $derived(plan ? projects.list.find((p) => p.folder === plan?.folder) : undefined);

  async function load(): Promise<void> {
    try {
      plan = await api.plan(id);
      error = null;
    } catch (e) {
      error = (e as Error).message;
    }
  }

  $effect(() => {
    void load();
    const timer = setInterval(() => plan?.state === "running" && load(), 3000);
    return () => clearInterval(timer);
  });

  async function act(action: () => Promise<PlanView>): Promise<void> {
    busy = true;
    error = null;
    try {
      plan = await action();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  /** Hosts refused to a step put in one of its agent's lists (*Keep blocked*, or *Allow* while
   *  the plan runs). */
  async function decide(hosts: string[], list: "allow" | "blocked"): Promise<void> {
    await act(async () => {
      await decideHosts(plan!.agentId, hosts, list);
      return api.plan(id);
    });
  }

  async function editAsDraft(): Promise<void> {
    busy = true;
    error = null;
    try {
      const draft = await api.createPlanDraft({ fromPlan: id });
      navigate({ view: "review-plan", draft: draft.id });
    } catch (e) {
      error = (e as Error).message;
      busy = false;
    }
  }

  async function remove(): Promise<void> {
    busy = true;
    try {
      await api.deletePlan(id);
      navigate(project ? { view: "project", id: project.id, tab: "plans" } : { view: "plans" }, true);
    } catch (e) {
      error = (e as Error).message;
      busy = false;
    }
  }
</script>

<PageHeader width="max-w-4xl" title={plan?.title ?? id} parent={project ? { label: `${project.name} › Plans`, href: href({ view: "project", id: project.id, tab: "plans" }) } : { label: "Plans", href: href({ view: "plans" }) }}>
  {#snippet meta()}
    {#if plan}<StatusBadge status={plan.state} />{/if}
  {/snippet}
  {#snippet actions()}
    {#if plan}
      <Button size="sm" variant="ghost" disabled={busy} onclick={editAsDraft} title="Its text in a new draft, to edit and approve as a new plan" data-testid="plan-edit-as-draft"
        ><FilePen />Edit as a new draft</Button
      >
    {/if}
    {#if plan?.state === "running"}
      <Button size="sm" variant="outline" disabled={busy} onclick={() => act(() => api.cancelPlan(id))} data-testid="plan-cancel"><X />Cancel</Button>
    {:else if plan}
      <Button size="sm" variant="ghost" class="text-destructive hover:text-destructive" disabled={busy} onclick={() => (deleting = true)} data-testid="plan-delete">
        <Trash />Delete
      </Button>
    {/if}
  {/snippet}
</PageHeader>
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-4xl space-y-6 px-8 py-10">
    {#if error}<p class="text-sm text-danger" data-testid="plan-error">{error}</p>{/if}
    {#if plan}
            <p class="fact" data-testid="plan-facts">
        {stepsDone(plan)} · run by {plan.agent ?? "an agent since deleted"} in <span class="font-mono">{plan.folder}</span> · from
        {#if plan.source}<span class="font-mono">{plan.source}</span>{:else}a draft{/if} · approved <When at={plan.approvedAt} /> · each step at most {limit(plan.stepTimeoutSec)}
      </p>
      {#if plan.stoppedBecause}
        <div class="space-y-2 rounded-[10px] border border-danger/30 bg-danger/5 px-4 py-3 text-sm" data-testid="plan-stopped">
          <p class="font-medium text-danger">Stopped: {plan.stoppedBecause}</p>
          <p class="text-muted-foreground">No later step runs. Fix what failed (in a session of its agent, or in your editor), then run it again from that step.</p>
        </div>
      {/if}
      {#if plan.context}
        <div class="space-y-1">
          <p class="text-xs font-medium tracking-wide text-muted-foreground uppercase">Context</p>
          <p class="whitespace-pre-wrap text-sm">{plan.context}</p>
        </div>
      {/if}
      <ol class="space-y-3" data-testid="plan-steps">
        {#each plan.steps as step (step.n)}
          <li class="space-y-2 rounded-[10px] border bg-card px-4 py-3 text-sm shadow-panel" data-testid="plan-step">
            <p class="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span class="font-medium tabular-nums">{step.n}.</span>
              <span class="font-medium">{step.title}</span>
              <StatusBadge status={step.state} />
              {#if step.startedAt}<span class="fact">started <When at={step.startedAt} />{#if step.endedAt}, ended <When at={step.endedAt} />{/if}</span>{/if}
              <span class="ml-auto flex gap-1">
                {#if step.sessionId}
                  <Button size="sm" variant="ghost" href={href({ view: "session", key: step.sessionId })} data-testid="plan-step-session"><ExternalLink />Its session</Button>
                {/if}
                {#if again.includes(step.n)}
                  <Button size="sm" variant="outline" disabled={busy} onclick={() => act(() => api.runPlan(id, step.n))} data-testid="plan-run-again"
                    ><RotateCcw />Run again from here</Button
                  >
                {/if}
              </span>
            </p>
            {#if step.summary}<p data-testid="plan-step-summary">{step.summary}</p>{/if}
            {#if step.error}<p class="text-danger">{step.error}</p>{/if}
            {#if step.refused?.length}
              {@const runs = again.includes(step.n)}
              <RefusedHosts
                hosts={step.refused}
                said={step.said}
                completed={step.state === "done"}
                {busy}
                again={runs ? `Allow and run again from step ${step.n}` : null}
                onallow={(hosts) => (runs ? act(() => api.runPlan(id, step.n, hosts)) : decide(hosts, "allow"))}
                onkeep={(hosts) => decide(hosts, "blocked")}
              />
            {/if}
            {#if step.notes}<p class="whitespace-pre-wrap text-muted-foreground"><span class="font-medium">Notes for the next steps:</span> {step.notes}</p>{/if}
            <details class="text-muted-foreground">
              <summary class="cursor-pointer">Its goal and when it is done</summary>
              <p class="mt-2 whitespace-pre-wrap">{step.goal}</p>
              <p class="mt-2 whitespace-pre-wrap"><span class="font-medium">Done when:</span> {step.doneWhen}</p>
            </details>
          </li>
        {/each}
      </ol>
    {/if}
  </div>
</div>

<Dialog bind:open={deleting} title="Delete this plan?" description="Handler forgets it and how it went. The sessions of its steps stay with its agent." testid="plan-delete-dialog">
  <div class="flex justify-end gap-2">
    <Button variant="ghost" size="sm" onclick={() => (deleting = false)}>Keep it</Button>
    <Button variant="destructive" size="sm" disabled={busy} onclick={remove} data-testid="plan-delete-confirm">Delete</Button>
  </div>
</Dialog>
