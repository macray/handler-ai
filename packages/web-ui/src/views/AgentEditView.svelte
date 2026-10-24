<script lang="ts">
  // A new agent of a project (no `id`; a copy of agent `from`, "Duplicate"), or an existing
  // one's settings, with Duplicate and Delete.
  import Copy from "@lucide/svelte/icons/copy";
  import Trash from "@lucide/svelte/icons/trash-2";
  import { Button } from "$lib/components/ui/button";
  import AgentEditor from "../components/AgentEditor.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import PageTitle from "../components/PageTitle.svelte";
  import { api } from "../lib/api";
  import { deletionStops } from "../lib/apps";
  import type { Agent, Project } from "../lib/contracts.gen";
  import { agentLabel, duplicateAgent, projects } from "../lib/projects.svelte";
  import { href, navigate, type Route } from "../lib/router.svelte";
  import { sessions } from "../lib/sessions.svelte";

  let { project: projectId, id, from }: { project: string; id?: string; from?: string } = $props();

  let project = $state<Project | null>(null);
  let error = $state<string | null>(null);

  const agent = $derived(id ? project?.agents.find((a) => a.id === id) : undefined);
  const original = $derived(from ? project?.agents.find((a) => a.id === from) : undefined);
  const start = $derived(original && project ? duplicateAgent(original, project.agents.map(agentLabel)) : undefined);

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
    else navigate({ view: "project", id: projectId, agent: a.id }, true); // the new one, chosen
  }

  async function remove(): Promise<void> {
    if (!project || !agent) return;
    const running = agent.connections.length ? ` Its ${agent.connections.length} running session(s) are stopped.` : "";
    const stops = await deletionStops(agent);
    if (!confirm(`Remove the agent ${agentLabel(agent)} from ${project.name}?${running}${stops}`)) return;
    try {
      await api.deleteAgent(agent.id);
      void projects.refresh();
      navigate({ view: "project", id: project.id }, true);
    } catch (e) {
      error = (e as Error).message;
    }
  }
</script>

<PageHeader
  titled
  title={agent ? agentLabel(agent) : id ? "Agent" : original ? `Copy of ${agentLabel(original)}` : "New agent"}
  parent={{ label: project?.name ?? "Project", href: href({ view: "project", id: projectId }) }}
>
  {#snippet actions()}
    {#if agent}
      <Button variant="ghost" size="sm" href={href({ view: "edit-agent", project: projectId, from: agent.id })} data-testid="agent-duplicate">
        <Copy />Duplicate
      </Button>
    {/if}
    {#if agent && project && project.agents.length > 1}
      <Button variant="ghost" size="sm" class="text-destructive hover:text-destructive" onclick={remove} data-testid="agent-delete"><Trash />Remove</Button>
    {/if}
  {/snippet}
</PageHeader>
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-3xl space-y-8 px-8 pt-10">
    <PageTitle title={agent ? agentLabel(agent) : original ? `Copy of ${agentLabel(original)}` : "New agent"} description="What it is for, who works, what it is given and what it may do." />
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
