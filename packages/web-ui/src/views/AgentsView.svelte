<script lang="ts">
  // Agents without a project: handler's built-in agents (D.18: each set up at most once, choosing its
  // models), and yours, made here or by `handler run` outside projects. An agent may have no folder
  // (each session gets its own), and an interface (its runs take an input and give a result back).
  import When from "../components/When.svelte";
  import Pencil from "@lucide/svelte/icons/pencil";
  import Play from "@lucide/svelte/icons/play";
  import Plus from "@lucide/svelte/icons/plus";
  import { Button } from "$lib/components/ui/button";
  import PageHeader from "../components/PageHeader.svelte";
  import PageTitle from "../components/PageTitle.svelte";
  import { accessLabel } from "../lib/access";
  import { whereLabel } from "../lib/agents";
  import LiveList from "../components/LiveList.svelte";
  import AgentSchedules from "../components/AgentSchedules.svelte";
  import { api } from "../lib/api";
  import type { Agent, AutomationView, BuiltinAgent, Session } from "../lib/contracts.gen";
  import { agentLabel } from "../lib/projects.svelte";
  import { href, navigate } from "../lib/router.svelte";
  import { sessions } from "../lib/sessions.svelte";

  let agents = $state<Agent[]>([]);
  let builtins = $state<BuiltinAgent[]>([]);
  let list = $state<Session[]>([]); // their sessions: the live ones are listed
  let error = $state<string | null>(null);
  let automations = $state<AutomationView[]>([]);

  const yours = $derived(agents.filter((a) => !a.origin));

  $effect(() => {
    void sessions.stopping.size; // a session closed here has stopped: load again
    const load = () =>
      Promise.all([api.agents(), api.sessions(), api.automations().catch(() => [])]).then(
        ([all, s, auto]) => {
          automations = auto;
          agents = all.filter((a) => !a.projectId).sort((a, b) => (b.lastUsedAt ?? b.createdAt).localeCompare(a.lastUsedAt ?? a.createdAt));
          list = s.filter((x) => agents.some((a) => a.id === x.agentId));
        },
        (e: Error) => (error = e.message),
      );
    void load();
    const timer = setInterval(load, 5000); // sessions and terminals come and go
    return () => clearInterval(timer);
  });

  $effect(() => {
    api.builtinAgents().then(
      (list) => (builtins = list),
      (e: Error) => (error = e.message),
    );
  });

  async function start(a: Agent): Promise<void> {
    error = null;
    try {
      navigate({ view: "session", key: (await sessions.start(a)).key });
    } catch (e) {
      error = (e as Error).message;
    }
  }

  function setUp(b: BuiltinAgent): Agent | undefined {
    return agents.find((a) => a.id === b.agentId);
  }
</script>

<PageHeader title="Agents" titled>
  {#snippet actions()}
    <Button size="sm" href={href({ view: "edit-ad-hoc" })} data-testid="new-ad-hoc"><Plus />New agent</Button>
  {/snippet}
</PageHeader>
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-4xl space-y-10 px-8 py-10">
    <PageTitle title="Agents" description="Agents outside projects: Handler's built-in ones, and yours, made here or by handler run outside a project." />
    {#if error}<p class="text-sm text-danger">{error}</p>{/if}

    <LiveList {agents} {list} />

    <section class="space-y-3" data-testid="builtin-agents">
      <h2 class="text-base font-semibold">Built-in</h2>
      <div class="grid gap-3 sm:grid-cols-2">
        {#each builtins as b (b.name)}
          {@const agent = setUp(b)}
          <a
            href={agent ? href({ view: "agent", id: agent.id }) : href({ view: "edit-ad-hoc", builtin: b.name })}
            class="space-y-1 rounded-lg border bg-card p-4 no-underline transition-colors hover:border-accent"
            data-testid={`builtin-${b.name}`}
          >
            <p class="font-medium">{agent ? agentLabel(agent) : b.agentName}</p>
            <p class="text-sm text-muted-foreground">{b.description}</p>
            {#if agent}
              <p class="text-xs text-muted-foreground">{agent.models.map(accessLabel).join(" | ")} · <When at={agent.lastUsedAt} /></p>
            {:else}
              <p class="text-xs font-medium text-warn">Not set up: choose its models</p>
            {/if}
          </a>
        {/each}
      </div>
      <p class="text-xs text-muted-foreground">One of each: set up once, then its settings are yours.</p>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold">Your agents</h2>
      <ul class="divide-y overflow-hidden rounded-lg border bg-card">
        {#each yours as a (a.id)}
          <li class="flex items-start gap-3 px-4 py-3" data-testid="ad-hoc-row">
            {#if a.interface}
              <Button size="icon-sm" variant="outline" class="mt-0.5" href={href({ view: "agent", id: a.id })} title="A new run, on its page" aria-label={`run ${agentLabel(a)}`}>
                <Play />
              </Button>
            {:else}
              <Button size="icon-sm" variant="outline" class="mt-0.5" onclick={() => start(a)} title="An empty chat with this agent" aria-label={`start ${agentLabel(a)}`}>
                <Play />
              </Button>
            {/if}
            <div class="min-w-0 flex-1 space-y-1">
              <div class="flex flex-wrap items-center gap-2">
                <a class="font-medium text-foreground [overflow-wrap:anywhere] hover:underline" href={href({ view: "agent", id: a.id })} data-testid="ad-hoc-agent">{agentLabel(a)}</a>
                {#if a.interface}<span class="rounded bg-accent-soft px-1.5 py-px text-xs font-medium text-accent-soft-foreground">runs unattended</span>{/if}
                <AgentSchedules {automations} name={a.name} project={null} />
              </div>
              {#if a.description}<p class="text-sm text-muted-foreground">{a.description}</p>{/if}
              <p class="text-xs text-muted-foreground">
                {a.models.map(accessLabel).join(" | ")} · <span title={a.scope ?? ""}>{a.scope ? "in " : ""}{whereLabel(a)}</span> · {#if a.lastUsedAt}used <When at={a.lastUsedAt} />{:else}not used yet{/if}
              </p>
            </div>
            <Button variant="ghost" size="icon-sm" href={href({ view: "edit-ad-hoc", id: a.id })} title="Edit" aria-label={`edit ${agentLabel(a)}`}>
              <Pencil />
            </Button>
          </li>
        {:else}
          <li class="px-4 py-6 text-center text-sm text-muted-foreground">None yet: make one with New agent, or <code>handler run</code> outside a project.</li>
        {/each}
      </ul>
    </section>
  </div>
</div>
