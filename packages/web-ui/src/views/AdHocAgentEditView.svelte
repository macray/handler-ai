<script lang="ts">
  // An agent without a project: its settings, or a new one, from scratch or setting up a built-in
  // agent (D.18: at most one each; its skills go to the library when it is saved).
  import AgentEditor from "../components/AgentEditor.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import PageTitle from "../components/PageTitle.svelte";
  import { api } from "../lib/api";
  import type { Agent, BuiltinAgent } from "../lib/contracts.gen";
  import { agentLabel } from "../lib/projects.svelte";
  import { href, navigate, type Route } from "../lib/router.svelte";
  import { builtinSpec } from "../lib/runs";
  import { sessions } from "../lib/sessions.svelte";

  let { id, builtin: builtinName }: { id?: string; builtin?: string } = $props();

  let agent = $state<Agent | null>(null);
  let builtin = $state<BuiltinAgent | null>(null);
  let error = $state<string | null>(null);
  const ready = $derived(id ? agent !== null : builtinName ? builtin !== null : true);

  $effect(() => {
    if (id) api.agent(id).then((a) => (agent = a), (e: Error) => (error = e.message));
    if (builtinName)
      api.builtinAgents().then(
        (list) => {
          const found = list.find((b) => b.name === builtinName);
          if (!found) error = `No built-in agent ${builtinName}.`;
          // already set up: its settings
          else if (found.agentId) navigate({ view: "edit-ad-hoc", id: found.agentId }, true);
          else builtin = found;
        },
        (e: Error) => (error = e.message),
      );
  });

  function saved(a: Agent, then?: Route): void {
    sessions.updateAgent(a);
    navigate(then ?? { view: "agent", id: a.id }, !id);
  }

  function back(): void {
    if (history.length > 1) history.back();
    else navigate(id ? { view: "agent", id } : { view: "agents" });
  }

  const title = $derived(agent ? agentLabel(agent) : builtin ? `Set up the ${builtin.agentName}` : "New agent");
</script>

<PageHeader {title} parent={{ label: "Agents", href: href({ view: "agents" }) }} titled />
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-3xl space-y-8 px-8 pt-10">
    <PageTitle {title} description={builtin?.description ?? "What it is for, what it runs as and where, what it is given and what it may do."} />
    {#if builtin && !agent}
      <p class="text-sm text-muted-foreground" data-testid="builtin-setup">
        Choose the models it runs with; the rest are Handler's defaults for it, yours to change now or later. There is one
        {builtin.agentName}.{#if builtin.skills?.length}
          Its skills ({builtin.skills.join(", ")}) go to your Skills when you save, unless you have them.{/if}
      </p>
    {/if}
    {#if agent?.origin}
      <p class="text-sm text-muted-foreground">Handler's built-in {agent.origin}: there is only this one; its settings are yours.</p>
    {/if}
    {#if error}<p class="text-sm text-danger">{error}</p>{/if}
    {#if ready}
      <AgentEditor
        agent={agent ?? undefined}
        start={builtin ? builtinSpec(builtin) : undefined}
        origin={builtin?.name}
        pendingSkills={builtin?.skills ?? []}
        onsaved={saved}
        oncancel={back}
      />
    {:else if !error}
      <p class="text-sm text-muted-foreground">Loading…</p>
    {/if}
  </div>
</div>
