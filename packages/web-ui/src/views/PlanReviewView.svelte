<script lang="ts">
  // A plan read (D.27), a draft Handler keeps or a file of an agent's folder, before anything runs:
  // its steps, its problems, what approving means; Approve and run sends back the digest read, so
  // a text changed since is refused ("read it again"). A draft is edited here too (saved over the
  // text read: refused when its builder wrote since), its builder session continued, or thrown
  // away. Who runs it: the agent its `Agent:` line names, or one chosen here
  // among the folder's agents that may run steps, bound by id at approval; the page fixes instead
  // of refusing: Switch it to Auto-approve (the agent's own update, by you), Create a plan runner
  // (the new-agent form, prefilled). On a subscription, an API key is recommended, as for an
  // unattended run (vendors' terms): not refused, you start its steps by approving it.
  import MessageSquare from "@lucide/svelte/icons/message-square";
  import Pencil from "@lucide/svelte/icons/pencil";
  import Play from "@lucide/svelte/icons/play";
  import Trash from "@lucide/svelte/icons/trash-2";
  import Plus from "@lucide/svelte/icons/plus";
  import RefreshCw from "@lucide/svelte/icons/refresh-cw";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import { Button } from "$lib/components/ui/button";
  import PageHeader from "../components/PageHeader.svelte";
  import { api, ApiError } from "../lib/api";
  import type { PlanDraft, PlanRead } from "../lib/contracts.gen";
  import { continueBuilder, limit, runnerFix, runnerOf, throwAwayDraft } from "../lib/plans";
  import { projects, switchToBypass } from "../lib/projects.svelte";
  import { href, navigate, type ReviewRoute } from "../lib/router.svelte";

  let {
    draft,
    path,
    session,
    agent,
    runner,
  }: { draft?: string; path?: string; session?: string; agent?: string; runner?: string } = $props();

  const where = $derived(draft ? { draftId: draft } : session ? { sessionId: session, path: path ?? "" } : { agentId: agent, path: path ?? "" });
  // this page, without its runner: where a plan runner made for it comes back
  const here = $derived<ReviewRoute>({
    view: "review-plan",
    ...(draft ? { draft } : { path: path ?? "" }),
    ...(session ? { session } : {}),
    ...(agent ? { agent } : {}),
  });
  const what = $derived(draft ? "draft" : "file");
  let drafted = $state<PlanDraft | null>(null); // the draft's: its project, its builder session
  let editing = $state<string | null>(null); // the draft's text, being edited
  let read = $state<PlanRead | null>(null);
  let error = $state<string | null>(null);
  let changed = $state(false); // the file changed since it was read: approving it was refused
  let busy = $state(false);
  const problems = $derived(read?.problems ?? []);
  const steps = $derived(read?.steps ?? []);
  const runners = $derived(read?.runners ?? []);
  const runs = $derived(read ? runnerOf(read) : undefined); // who runs it, if one may
  const fix = $derived(read ? runnerFix(read) : null);
  // the plan names another agent than the one chosen: the choice wins
  const overridden = $derived(!!read?.agent && !!runs && runs.name.toLowerCase() !== read.agent.toLowerCase());

  async function load(): Promise<void> {
    error = null;
    changed = false;
    try {
      read = await api.readPlan(where, runner);
      if (draft) drafted = await api.planDraft(draft);
    } catch (e) {
      error = (e as Error).message;
    }
  }

  $effect(() => {
    void load();
  });

  async function approve(): Promise<void> {
    if (!read) return;
    busy = true;
    error = null;
    try {
      const plan = await api.approvePlan(where, read.digest, runner);
      navigate({ view: "plan", id: plan.id });
    } catch (e) {
      changed = e instanceof ApiError && e.title === "the plan changed since you read it";
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  function choose(id: string): void {
    navigate({ ...here, ...(id ? { runner: id } : {}) }, true);
  }

  async function save(): Promise<void> {
    if (!read || !draft || editing === null) return;
    busy = true;
    error = null;
    try {
      await api.savePlanDraft(draft, editing, read.digest);
      editing = null;
      await load();
    } catch (e) {
      changed = e instanceof ApiError && e.title === "the draft changed since you read it";
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  // the project it is for: its page's Plans tab lists it
  const project = $derived(projects.list.find((p) => p.id === (drafted?.projectId ?? read?.projectId)));
  const back = $derived(project ? { label: `${project.name} › Plans`, href: href({ view: "project", id: project.id, tab: "plans" }) } : { label: "Plans", href: href({ view: "plans" }) });

  async function throwAway(): Promise<void> {
    if (drafted && (await throwAwayDraft(drafted))) navigate(project ? { view: "project", id: project.id, tab: "plans" } : { view: "plans" });
  }

  async function switchIt(): Promise<void> {
    if (!runs) return;
    busy = true;
    error = null;
    try {
      await switchToBypass(await api.agent(runs.id));
      await load();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

<PageHeader width="max-w-4xl" title="Review a plan" parent={back}>
  {#snippet actions()}
    {#if drafted}
      <Button size="sm" variant="ghost" class="text-destructive hover:text-destructive" disabled={busy} onclick={throwAway} data-testid="plan-draft-delete"><Trash />Throw away</Button>
      {#if drafted.sessionId}
        <Button size="sm" variant="ghost" onclick={() => drafted?.sessionId && continueBuilder(drafted.sessionId)} data-testid="plan-draft-continue"><MessageSquare />Continue with the plan builder</Button>
      {/if}
      <Button size="sm" variant="ghost" disabled={busy || editing !== null || !read} onclick={() => (editing = read?.text ?? "")} data-testid="plan-draft-edit"><Pencil />Edit</Button>
    {/if}
    <Button size="sm" variant="ghost" disabled={busy || editing !== null} onclick={load} data-testid="plan-read-again"><RefreshCw />Read it again</Button>
    <Button size="sm" disabled={busy || !read || problems.length > 0 || changed || editing !== null} onclick={approve} data-testid="plan-approve"><Play />Approve and run</Button>
  {/snippet}
</PageHeader>
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-4xl space-y-6 px-8 py-10">
    {#if error}
      <p class="text-sm text-danger" data-testid="plan-review-error">{error}{#if changed}. Read it again, then approve what you read.{/if}</p>
    {/if}
    {#if editing !== null}
      <div class="space-y-2" data-testid="plan-draft-editor">
        <textarea class="code min-h-[28rem] w-full rounded-[10px] border bg-background p-3 text-sm" bind:value={editing} aria-label="The plan's text" data-testid="plan-draft-text"></textarea>
        <div class="flex gap-2">
          <Button size="sm" disabled={busy} onclick={save} data-testid="plan-draft-save">Save</Button>
          <Button size="sm" variant="ghost" disabled={busy} onclick={() => (editing = null)}>Cancel</Button>
          <p class="flex-1 text-sm text-muted-foreground">Saved over the text you read: if the plan builder writes meanwhile, Handler says so and keeps its version.</p>
        </div>
      </div>
    {/if}
    {#if read && editing === null}
            <p class="fact" data-testid="plan-review-facts">
        {#if drafted}a draft for {projects.list.find((p) => p.id === drafted?.projectId)?.name ?? drafted.folder}{:else}<span class="font-mono">{read.path}</span>{/if} · {runs ? `run by ${runs.name}` : read.agent ? `names ${read.agent}` : "no agent chosen"} · {steps.length} step{steps.length === 1 ? "" : "s"} · each at most
        {limit(read.stepTimeoutSec)}
      </p>
      <div class="space-y-2 rounded-[10px] border bg-card px-4 py-3 text-sm shadow-panel" data-testid="plan-runner">
        <p class="font-medium">Who runs its steps</p>
        {#if runners.length}
          <select
            class="h-8 rounded-lg border bg-background px-2 text-sm"
            aria-label="The agent that runs its steps"
            value={runs?.id ?? ""}
            disabled={busy}
            onchange={(e) => choose(e.currentTarget.value)}
            data-testid="plan-runner-choice"
          >
            {#if !runs}<option value="" disabled>Choose an agent…</option>{/if}
            {#each runners as r (r.id)}
              <option value={r.id}>{r.name}{r.bypass ? "" : " (asks before acting)"}</option>
            {/each}
          </select>
          {#if overridden}
            <p class="text-muted-foreground" data-testid="plan-runner-overridden">The plan names {read.agent}; {runs?.name} runs it, as you chose. The {what} is not changed.</p>
          {/if}
        {:else}
          <p class="text-muted-foreground">
            No agent of this folder can run a plan's steps: one that works in the folder, takes no form and is not one of an app's parts.
          </p>
        {/if}
        {#if fix === "switch" && runs}
          <div class="flex flex-wrap items-center gap-3" data-testid="plan-runner-switch">
            <Button size="sm" variant="outline" disabled={busy} onclick={switchIt} data-testid="plan-switch-bypass">Switch it to Auto-approve</Button>
            <p class="flex-1 text-muted-foreground">
              Nobody answers a plan's steps. Saved in <em>Auto-approve</em>, {runs.name} never asks before acting, in every session, not only this plan's.
            </p>
          </div>
        {:else if fix === "create" && read.projectId}
          <div class="flex flex-wrap items-center gap-3">
            <Button size="sm" variant="outline" href={href({ view: "edit-agent", project: read.projectId, plan: here })} data-testid="plan-create-runner"><Plus />Create a plan runner</Button>
            <p class="flex-1 text-muted-foreground">A new agent of the project, in its folder, reaching only the sites it needs: you choose its model and save it.</p>
          </div>
        {/if}
      </div>
      {#if problems.length}
        <div class="space-y-1 rounded-[10px] border border-danger/30 bg-danger/5 px-4 py-3 text-sm" data-testid="plan-problems">
          <p class="font-medium text-danger">It cannot be approved until these are fixed:</p>
          <ul class="list-disc space-y-0.5 pl-5">
            {#each problems as problem, i (i)}<li>{problem}</li>{/each}
          </ul>
        </div>
      {:else}
        <p class="text-sm text-muted-foreground" data-testid="plan-what-runs">
          Approving it runs its steps one after another, each a new session of {runs?.name} with its own settings, unattended: nobody answers it, and each
          step checks its "Done when" itself. Handler stops at the first step not done. What runs is this {what} as you read it now: changed afterwards, it
          changes nothing.
        </p>
      {/if}
      {#if read.recommendation}
        <p class="flex items-start gap-1.5 text-sm text-warn" data-testid="plan-recommendation"><TriangleAlert class="mt-0.5 size-4 shrink-0" />{read.recommendation}</p>
      {/if}
      {#if read.context}
        <div class="space-y-1">
          <p class="text-xs font-medium tracking-wide text-muted-foreground uppercase">Context</p>
          <p class="whitespace-pre-wrap text-sm">{read.context}</p>
        </div>
      {/if}
      <ol class="space-y-3" data-testid="plan-review-steps">
        {#each steps as step (step.n)}
          <li class="space-y-2 rounded-[10px] border bg-card px-4 py-3 text-sm shadow-panel">
            <p class="font-medium"><span class="tabular-nums">{step.n}.</span> {step.title}</p>
            <p class="whitespace-pre-wrap">{step.goal}</p>
            <p class="whitespace-pre-wrap text-muted-foreground"><span class="font-medium">Done when:</span> {step.doneWhen}</p>
          </li>
        {/each}
      </ol>
      <details class="text-sm text-muted-foreground">
        <summary class="cursor-pointer">The {what}, as written</summary>
        <pre class="code mt-2">{read.text}</pre>
      </details>
    {/if}
  </div>
</div>
