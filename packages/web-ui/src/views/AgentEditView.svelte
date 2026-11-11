<script lang="ts">
  // A new agent of a project (no `id`; a copy of agent `from`, "Duplicate", or a job made from it
  // for a new automation, `job`, back to that automation once saved; a plan runner for the
  // review page `plan`, back to it once saved, the new agent chosen), or an existing one's settings, with Duplicate and Remove (the
  // last one too: the project stays, with no agent).
  import Copy from "@lucide/svelte/icons/copy";
  import Trash from "@lucide/svelte/icons/trash-2";
  import { Button } from "$lib/components/ui/button";
  import AgentEditor from "../components/AgentEditor.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import { api } from "../lib/api";
  import { deletionStops } from "../lib/apps";
  import type { Agent, Project } from "../lib/contracts.gen";
  import { planRunner } from "../lib/plans";
  import { agentLabel, duplicateAgent, emptyAgent, jobFrom, projects } from "../lib/projects.svelte";
  import { href, navigate, type ReviewRoute, type Route } from "../lib/router.svelte";
  import { sessions } from "../lib/sessions.svelte";

  let { project: projectId, id, from, job = false, plan }: { project: string; id?: string; from?: string; job?: boolean; plan?: ReviewRoute } = $props();

  let project = $state<Project | null>(null);
  let error = $state<string | null>(null);

  const agent = $derived(id ? project?.agents.find((a) => a.id === id) : undefined);
  const original = $derived(from ? project?.agents.find((a) => a.id === from) : undefined);
  const start = $derived(
    !project
      ? undefined
      : original
        ? (job ? jobFrom : duplicateAgent)(original, project.agents.map(agentLabel))
        : plan && !id
          ? planRunner(project)
          : undefined,
  );
  const fresh = $derived(original ? (job ? `A job from ${agentLabel(original)}` : `Copy of ${agentLabel(original)}`) : plan ? "New plan runner" : "New agent");

  $effect(() => {
    api.project(projectId).then(
      (current) => {
        project = current;
        if (id && !current.agents.some((a) => a.id === id)) error = "This agent is not in the project any more.";
      },
      (e: Error) => (error = e.message),
    );
  });

  function back(): void {
    if (history.length > 1) history.back();
    else navigate({ view: "project", id: projectId });
  }

  function saved(a: Agent, then?: Route): void {
    sessions.updateAgent(a); // open sessions show the new name at once
    void projects.refresh();
    if (then) navigate(then, !id);
    else if (id) back();
    else if (plan) navigate({ ...plan, runner: a.id }, true); // back to its review, it runs it
    else if (job) navigate({ view: "edit-automation", agent: a.id }, true); // the automation it was made for
    else navigate({ view: "project", id: projectId, agent: a.id }, true); // the new one, chosen
  }

  async function remove(): Promise<void> {
    if (!project || !agent) return;
    const running = agent.connections.length ? ` Its ${agent.connections.length} running session(s) are stopped.` : "";
    const stops = await deletionStops(agent);
    const last = project.agents.length === 1 ? ` ${project.name} stays, with no agent.` : "";
    if (!confirm(`Remove the agent ${agentLabel(agent)} from ${project.name}?${running}${stops}${last}`)) return;
    try {
      await api.deleteAgent(agent.id);
      void projects.refresh();
      navigate({ view: "project", id: project.id }, true);
    } catch (e) {
      error = (e as Error).message;
    }
  }
</script>

<PageHeader width="max-w-3xl"
  title={agent ? agentLabel(agent) : id ? "Agent" : fresh}
  parent={{ label: project?.name ?? "Project", href: href({ view: "project", id: projectId }) }}
>
  {#snippet actions()}
    {#if agent}
      <Button variant="ghost" size="sm" href={href({ view: "edit-agent", project: projectId, from: agent.id })} data-testid="agent-duplicate">
        <Copy />Duplicate
      </Button>
    {/if}
    {#if agent && project}
      <Button variant="ghost" size="sm" class="text-destructive hover:text-destructive" onclick={remove} data-testid="agent-delete"><Trash />Remove</Button>
    {/if}
  {/snippet}
</PageHeader>
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-3xl space-y-8 px-8 pt-4">
    {#if error}<p class="text-sm text-danger">{error}</p>{/if}
    {#if project && (agent || !id)}
      {#key agent?.id}
        <AgentEditor {project} {agent} {start} onsaved={saved} oncancel={back} />
      {/key}
    {:else if !error}
      <p class="text-sm text-muted-foreground">Loading…</p>
    {/if}
  </div>
</div>
