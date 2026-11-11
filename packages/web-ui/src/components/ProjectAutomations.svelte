<script lang="ts">
  // A project's Automations tab (I): New automation first (for its default agent), then the
  // automations that run its agents, a row each (when, which agent, its last run, on or off: off
  // at once; on from its page, where turning it on is your approval), then, faintly, those of the
  // Library that also run on it (a script read when a session of it stops), edited where they
  // live.
  import Plus from "@lucide/svelte/icons/plus";
  import SquareTerminal from "@lucide/svelte/icons/square-terminal";
  import { Button } from "$lib/components/ui/button";
  import { whenSentence } from "../lib/automations";
  import type { AutomationView, Project } from "../lib/contracts.gen";
  import { agentLabel } from "../lib/projects.svelte";
  import { href } from "../lib/router.svelte";
  import AutomationRow from "./AutomationRow.svelte";

  let { project, automations, onchanged }: { project: Project; automations: AutomationView[]; onchanged: () => void } = $props();

  const ids = $derived(new Set(project.agents.map((a) => a.id)));
  const theirs = $derived(automations.filter((a) => a.agentId && ids.has(a.agentId)));
  // a session's automation that reads this project's sessions: named for it, for one of its
  // agents, or for every project
  const alsoHere = $derived(
    automations.filter(
      (a) =>
        !theirs.includes(a) &&
        a.definition &&
        typeof a.definition.when === "string" &&
        ((!a.onlyProjects?.length && !a.onlyAgents?.length) || a.onlyProjects?.includes(project.id) || a.onlyAgents?.some((g) => ids.has(g))),
    ),
  );
  const nameOf = (agentId: string | null | undefined) => {
    const a = project.agents.find((g) => g.id === agentId);
    return a ? agentLabel(a) : "";
  };
  const defaultAgent = $derived(project.defaultAgent ?? project.agents[0]?.id);
</script>

<div class="flex justify-end">
  <Button size="sm" href={href({ view: "edit-automation", ...(defaultAgent ? { agent: defaultAgent } : {}) })} data-testid="new-automation"><Plus />New automation</Button>
</div>

{#if theirs.length}
  <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel" data-testid="project-automations">
    {#each theirs as a (a.name)}
      <AutomationRow automation={a} agentName={nameOf(a.agentId)} {onchanged} testid="project-automation" />
    {/each}
  </ul>
{:else}
  <div class="rounded-[10px] border border-dashed px-6 py-10 text-center text-sm text-muted-foreground" data-testid="no-automation">
    No automation runs this project's agents yet: run one every morning, or when a session stops.
  </div>
{/if}

{#if alsoHere.length}
  <section class="space-y-2" data-testid="project-automations-also">
    <h2 class="section-label">Also runs on this project</h2>
    <ul class="divide-y overflow-hidden rounded-[10px] border text-sm opacity-80">
      {#each alsoHere as a (a.name)}
        <li class="flex items-center gap-3 px-4 py-3">
          <SquareTerminal class="size-4 shrink-0 text-muted-foreground" />
          <span class="min-w-0 flex-1">
            <span class="block">{a.name}</span>
            <span class="text-xs text-muted-foreground"
              >{whenSentence(a.definition)}{a.enabled ? "" : " · off"}</span
            >
          </span>
          <a class="text-sm text-link no-underline hover:underline" href={href({ view: "automation", name: a.name })}>Open in Library</a>
        </li>
      {/each}
    </ul>
  </section>
{/if}
