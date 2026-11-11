<script lang="ts">
  // Plans being written (D.27): drafts Handler keeps, newest change first; each reviewed (and
  // edited, approved) on its page, its plan builder session continued, or thrown away.
  import FilePen from "@lucide/svelte/icons/file-pen";
  import { Button } from "$lib/components/ui/button";
  import type { PlanDraft } from "../lib/contracts.gen";
  import { continueBuilder, throwAwayDraft } from "../lib/plans";
  import { projects } from "../lib/projects.svelte";
  import { href } from "../lib/router.svelte";
  import When from "./When.svelte";

  let { drafts, ongone }: { drafts: PlanDraft[]; ongone: (id: string) => void } = $props();

  async function throwAway(d: PlanDraft): Promise<void> {
    if (await throwAwayDraft(d)) ongone(d.id);
  }
</script>

<ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel" data-testid="plan-drafts">
  {#each drafts as d (d.id)}
    <li class="flex flex-wrap items-center gap-3 px-4 py-3" data-testid="plan-draft">
      <a class="flex min-w-0 flex-1 items-center gap-2 text-foreground no-underline" href={href({ view: "review-plan", draft: d.id })} title="Review it">
        <FilePen class="size-4 shrink-0 text-muted-foreground" /><span class="min-w-0 truncate font-medium">{d.title || "A plan being written"}</span>
      </a>
      <p class="text-xs text-muted-foreground">
        {`${projects.list.find((p) => p.id === d.projectId)?.name ?? d.folder} · `}changed <When at={d.changedAt} />
      </p>
      <div class="flex gap-1">
        {#if d.sessionId}
          <Button size="sm" variant="ghost" onclick={() => d.sessionId && continueBuilder(d.sessionId)} data-testid="plan-draft-continue">Continue</Button>
        {/if}
        <Button size="sm" variant="ghost" href={href({ view: "review-plan", draft: d.id })} data-testid="plan-draft-review">Review</Button>
        <Button size="sm" variant="ghost" class="text-destructive hover:text-destructive" onclick={() => throwAway(d)} data-testid="plan-draft-throw">Throw away</Button>
      </div>
    </li>
  {/each}
</ul>
