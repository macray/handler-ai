<script lang="ts">
  // An agent without a project: its settings, or a new one, from scratch. An agents file's agents
  // are set up on their own page (AgentSetupView). An existing one is deleted from here.
  import { ask } from "../lib/ask.svelte";
  import Trash from "@lucide/svelte/icons/trash-2";
  import { Button } from "$lib/components/ui/button";
  import AgentEditor from "../components/AgentEditor.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import { api } from "../lib/api";
  import { deletionStops } from "../lib/apps";
  import { isChat, setUpFrom } from "../lib/agents";
  import type { Agent } from "../lib/contracts.gen";
  import { agentLabel } from "../lib/projects.svelte";
  import { href, navigate, type Route } from "../lib/router.svelte";
  import { sessions } from "../lib/sessions.svelte";

  let { id }: { id?: string } = $props();

  let agent = $state<Agent | null>(null);
  let chat = $state(false); // someone you talk to: its place is Chat
  let error = $state<string | null>(null);
  const origin = $derived(setUpFrom(agent?.origin));
  const ready = $derived(id ? agent !== null : true);

  $effect(() => {
    if (id)
      api.agent(id).then(
        (a) => ((agent = a), (chat = isChat(a))),
        (e: Error) => (error = e.message),
      );
  });

  function saved(a: Agent, then?: Route): void {
    sessions.updateAgent(a);
    navigate(then ?? { view: "agent", id: a.id }, !id);
  }

  async function remove(): Promise<void> {
    if (!agent) return;
    const stops = await deletionStops(agent);
    if (!(await ask({ title: `Delete the agent ${agentLabel(agent)}?`, detail: `Its running sessions are stopped.${stops}`, yes: "Delete", danger: true }))) return;
    try {
      await api.deleteAgent(agent.id);
      navigate(chat ? { view: "chat" } : { view: "agents" }, true);
    } catch (e) {
      error = (e as Error).message;
    }
  }

  function back(): void {
    if (history.length > 1) history.back();
    else navigate(id ? { view: "agent", id } : { view: "agents" });
  }

  const title = $derived(agent ? agentLabel(agent) : "New agent");
</script>

<PageHeader width="max-w-3xl"
  {title}
  parent={chat
    ? { label: "Chat", href: href({ view: "chat" }) }
    : { label: "Agents outside projects", href: href({ view: "agents" }) }}
>
  {#snippet actions()}
    {#if agent}
      <Button variant="ghost" size="sm" class="text-destructive hover:text-destructive" onclick={remove} data-testid="agent-delete"><Trash />Delete</Button>
    {/if}
  {/snippet}
</PageHeader>
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-3xl space-y-8 px-8 pt-10">
    {#if origin}
      <p class="text-sm text-muted-foreground">Set up from {origin}; its settings are yours.</p>
    {/if}
    {#if error}<p class="text-sm text-danger">{error}</p>{/if}
    {#if ready}
      <AgentEditor agent={agent ?? undefined} onsaved={saved} oncancel={back} />
    {:else if !error}
      <p class="text-sm text-muted-foreground">Loading…</p>
    {/if}
  </div>
</div>
