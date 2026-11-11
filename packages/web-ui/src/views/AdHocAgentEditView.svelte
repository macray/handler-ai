<script lang="ts">
  // An agent without a project: its settings, or a new one, from scratch or set up from the
  // definition an app ships for one of its needs (H.2: saved, it is given to the app; its skills go
  // to the library). An agents file's agents are set up on their own page (AgentSetupView). An
  // existing one is deleted from here.
  import Trash from "@lucide/svelte/icons/trash-2";
  import { Button } from "$lib/components/ui/button";
  import AgentEditor from "../components/AgentEditor.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import { api } from "../lib/api";
  import { deletionStops } from "../lib/apps";
  import { appOf, isChat, setUpFrom } from "../lib/agents";
  import type { AddonInfo, AddonUse, Agent, AgentDefinition, App, AppAgentNeed } from "../lib/contracts.gen";
  import { agentLabel } from "../lib/projects.svelte";
  import { href, navigate, type Route } from "../lib/router.svelte";
  import { definitionSpec } from "../lib/runs";
  import { toolsAsked } from "../lib/setup";
  import { sessions } from "../lib/sessions.svelte";

  let { id, app: appName, need: needName }: { id?: string; app?: string; need?: string } = $props();

  let agent = $state<Agent | null>(null);
  let chat = $state(false); // someone you talk to: its place is Chat
  let app = $state<App | null>(null); // setting up the agent of one of its needs
  let need = $state<AppAgentNeed | null>(null);
  let error = $state<string | null>(null);
  const definition = $derived<AgentDefinition | null>(need?.definition ?? null);
  const origin = $derived(setUpFrom(agent?.origin));
  // the addons the definition needs (G.3), with a configuration of those with settings (G.2);
  // null: not read yet
  let chosen = $state<AddonUse[] | null>(null);
  let lacking = $state<AddonInfo[]>([]); // addons with settings it needs, with no configuration yet
  let uninstalled = $state<string[]>([]); // addons it needs that are not installed
  const ready = $derived(
    (id ? agent !== null : appName ? need !== null : true) && (!definition?.addons?.length || chosen !== null),
  );
  const start = $derived(definition ? { ...definitionSpec(definition), addons: chosen ?? [] } : undefined);

  async function readAddons(names: string[]): Promise<void> {
    const [bindings, addons] = await Promise.all([api.bindings(), api.addons()]);
    const valid = bindings.filter((b) => !b.error);
    const { install, connect } = toolsAsked(names, addons);
    chosen = names.flatMap((addon): AddonUse[] => {
      if (install.includes(addon)) return [];
      if (!connect.includes(addon)) return [{ addon }];
      const binding = valid.find((b) => b.addon === addon)?.name;
      return binding ? [{ addon, binding }] : [];
    });
    lacking = addons.filter((a) => connect.includes(a.name) && !valid.some((b) => b.addon === a.name));
    uninstalled = install;
  }

  $effect(() => {
    const names = definition?.addons ?? [];
    if (names.length && chosen === null) void readAddons(names).catch((e: Error) => (error = e.message));
  });
  // the folder given for the need's `worksIn`: it works there
  const needFolder = $derived(need?.worksIn ? (app?.files?.find((f) => f.name === need?.worksIn)?.path ?? null) : null);
  // the app it is (or is being set up as) one of the parts of (H.14): its page is the agent's place
  const partOf = $derived(appName ?? (agent ? appOf(agent) : null));

  $effect(() => {
    if (id)
      api.agent(id).then(
        (a) => ((agent = a), (chat = isChat(a))),
        (e: Error) => (error = e.message),
      );
    if (appName && needName)
      api.app(appName).then(
        (a) => {
          const found = a.agents?.find((n) => n.name === needName);
          if (!found?.definition) error = found?.problem ?? `${appName} needs no agent ${needName}.`;
          else if (found.worksIn && !a.files?.find((f) => f.name === found.worksIn)?.path)
            error = `Give ${appName} its folder ${found.worksIn} first (its Manage, on its page): this agent works there.`;
          else {
            app = a;
            need = found;
          }
        },
        (e: Error) => (error = e.message),
      );
  });

  async function saved(a: Agent, then?: Route): Promise<void> {
    sessions.updateAgent(a);
    if (app && need) {
      try {
        await api.setAppAgent(app.name, need.name, a.id);
      } catch (e) {
        error = `Saved, but not given to ${app.name}: ${(e as Error).message}`;
        return;
      }
      navigate(then ?? { view: "apps", app: app.name }, true);
      return;
    }
    navigate(then ?? { view: "agent", id: a.id }, !id);
  }

  async function remove(): Promise<void> {
    if (!agent) return;
    const stops = await deletionStops(agent);
    if (!confirm(`Delete the agent ${agentLabel(agent)}? Its running sessions are stopped.${stops}`)) return;
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

  const title = $derived(agent ? agentLabel(agent) : definition ? `Set up the ${definition.agentName}` : "New agent");
</script>

<PageHeader width="max-w-3xl"
  {title}
  parent={partOf
    ? { label: partOf, href: href({ view: "apps", app: partOf }) }
    : chat
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
        {#each uninstalled as addon (addon)}
      <p class="text-sm text-warn" data-testid="setup-addon-missing">
        It needs the {addon} tool, not installed: install it from
        <a class="text-link hover:underline" href={href({ view: "library", shelf: "tools", more: true })}>Library → Tools</a>, then come back.
      </p>
    {/each}
        {#each lacking as addon (addon.name)}
      <p class="text-sm text-warn" data-testid="setup-addon-lacking">
        It needs a connection to the {addon.name} tool ({addon.description ?? ""}). Make one in
        <a class="text-link hover:underline" href={href({ view: "addons" })}>Library → Tools</a>, then come back.
      </p>
    {/each}
    {#if app && need && !agent}
      <p class="text-sm text-muted-foreground" data-testid="app-agent-setup">
        For the app {app.name}: choose the models it runs with; the rest is what the app's author wrote for it, yours to change now or later.
        Saved, it is one of {app.name}'s parts (on its page, started by it){#if needFolder}, and works in its folder <span class="fact">{needFolder}</span>{/if}.{#if need.definition?.skills?.length}
          Its skills ({need.definition.skills.join(", ")}) go to your Skills when you save, unless you have them.{/if}
      </p>
    {/if}
    {#if agent && appOf(agent)}
      <p class="text-sm text-muted-foreground">One of the app {appOf(agent)}'s parts, started by it; its settings are yours.</p>
    {:else if origin}
      <p class="text-sm text-muted-foreground">Set up from {origin}; its settings are yours.</p>
    {/if}
    {#if error}<p class="text-sm text-danger">{error}</p>{/if}
    {#if ready}
      <AgentEditor
        agent={agent ?? undefined}
        {start}
        origin={need?.origin}
        startFolder={needFolder}
        pendingSkills={definition?.skills ?? []}
        onsaved={saved}
        oncancel={back}
      />
    {:else if !error}
      <p class="text-sm text-muted-foreground">Loading…</p>
    {/if}
  </div>
</div>
