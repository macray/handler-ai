<script lang="ts">
  // An agent's address, wherever it is (`#/agents/:id`, linked from apps, runs, terminals,
  // sessions): it opens its place with it chosen, its project's page, Chat or Other folders. One of
  // an app's parts (H.14) has no other place: it is shown here, under its app, with no start (its
  // app starts it).
  import AgentWorkspace from "../components/AgentWorkspace.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import { appOf, isChat } from "../lib/agents";
  import { api } from "../lib/api";
  import type { Agent, AutomationView, Session } from "../lib/contracts.gen";
  import { agentLabel } from "../lib/projects.svelte";
  import { href, navigate } from "../lib/router.svelte";

  let { id }: { id: string } = $props();

  let error = $state<string | null>(null);
  let part = $state<Agent | null>(null); // an app's part, shown here
  let list = $state<Session[]>([]);
  let automations = $state<AutomationView[]>([]);
  const app = $derived(part ? appOf(part) : null);

  $effect(() => {
    api.agent(id).then(
      (a) => {
        if (appOf(a)) {
          part = a;
          void Promise.all([api.sessions(), api.automations().catch(() => [])]).then(([s, auto]) => ((list = s.filter((x) => x.agentId === a.id)), (automations = auto)));
        } else if (a.projectId) navigate({ view: "project", id: a.projectId, agent: a.id }, true);
        else navigate(isChat(a) ? { view: "chat", agent: a.id } : { view: "agents", agent: a.id }, true);
      },
      (e: Error) => (error = e.message),
    );
  });
</script>

{#if part && app}
  <PageHeader width="max-w-4xl" title={agentLabel(part)} parent={{ label: app, href: href({ view: "apps", app }) }} />
  <div class="flex-1 overflow-y-auto">
    <div class="mx-auto w-full max-w-4xl px-8 py-8">
      <AgentWorkspace agent={part} {list} {automations} edit={href({ view: "edit-ad-hoc", id: part.id })} partOf={app} />
    </div>
  </div>
{:else}
  <PageHeader width="max-w-4xl" title="Agent" />
  <div class="mx-auto w-full max-w-4xl px-8 py-10">
    {#if error}<p class="text-sm text-danger">{error}</p>{:else}<p class="text-sm text-muted-foreground">Loading…</p>{/if}
  </div>
{/if}
