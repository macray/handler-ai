<script lang="ts">
  // Plans (D.27): New plan (a project chosen: the plan builder writes a draft for it), the plans
  // being written (drafts), and the plans you approved, most recent first, each opening its page
  // (its steps, their state and sessions). An agent may also write one in its folder (the skill
  // handler-plan), reviewed from the session's Files, or with `handler plan run`.
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import ListChecks from "@lucide/svelte/icons/list-checks";
  import LoadingCards from "../components/LoadingCards.svelte";
  import NewPlan from "../components/NewPlan.svelte";
  import PlanDraftList from "../components/PlanDraftList.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import StatusBadge from "../components/StatusBadge.svelte";
  import When from "../components/When.svelte";
  import { api } from "../lib/api";
  import type { PlanDraft, PlanView } from "../lib/contracts.gen";
  import { stepsDone } from "../lib/plans";
  import { href } from "../lib/router.svelte";

  let plans = $state<PlanView[] | null>(null);
  let drafts = $state<PlanDraft[]>([]);
  let error = $state<string | null>(null);

  async function load(): Promise<void> {
    try {
      [plans, drafts] = await Promise.all([api.plans(), api.planDrafts()]);
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
</script>

<PageHeader width="max-w-4xl" title="Plans" />
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-4xl space-y-8 px-8 py-10">
        {#if error}<p class="text-sm text-danger" data-testid="plans-error">{error}</p>{/if}
    <NewPlan />
    {#if drafts.length}
      <section class="space-y-2">
        <h2 class="section-label">Being written</h2>
        <PlanDraftList {drafts} ongone={load} />
      </section>
    {/if}

    {#if !plans}
      <div class="space-y-3"><LoadingCards count={2} height="h-20" /></div>
    {:else if plans.length}
      {#if drafts.length}<h2 class="section-label">Approved</h2>{/if}
      <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
        {#each plans as p (p.id)}
          <li class="enter">
            <a
              href={href({ view: "plan", id: p.id })}
              class="group flex items-center gap-4 px-4 py-3.5 text-foreground no-underline transition-colors hover:bg-muted/40"
              data-testid="plan-card"
            >
              <span class="hidden size-9 shrink-0 items-center justify-center rounded-lg sm:flex {p.state === 'running' ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground'}"
                ><ListChecks class="size-4" /></span
              >
              <div class="min-w-0 flex-1 space-y-0.5">
                <p class="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span class="font-medium">{p.title}</span>
                  <StatusBadge status={p.state} />
                </p>
                {#if p.stoppedBecause}<p class="text-danger">{p.stoppedBecause}</p>{/if}
                <p class="fact">
                  {stepsDone(p)} · {p.agent ?? "its agent was deleted"} · approved <When at={p.approvedAt} />
                </p>
              </div>
              <ChevronRight class="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
            </a>
          </li>
        {/each}
      </ul>
    {:else}
      <div class="flex flex-col items-center gap-3 rounded-[10px] border border-dashed px-6 py-12 text-center" data-testid="no-plan">
        <span class="flex size-10 items-center justify-center rounded-lg bg-muted text-muted-foreground"><ListChecks class="size-5" /></span>
        <p class="font-medium">No plan yet</p>
        <p class="max-w-md text-sm text-muted-foreground">
          <em>New plan</em> starts the plan builder on a project: it reads the project, asks what you want done, and writes the plan for you to review.
        </p>
      </div>
    {/if}
  </div>
</div>
