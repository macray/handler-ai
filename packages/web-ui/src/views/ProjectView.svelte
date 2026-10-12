<script lang="ts">
  // A project: say what you want, pick the agent (or keep the default) and, when it has several,
  // the model it runs with, start; an agent with an interface (D.18) is run from its page, with
  // its form. Below: its live and recent sessions, its agents (those run by automations show
  // when) and the defaults they get.
  import ContextTag from "../components/ContextTag.svelte";
  import When from "../components/When.svelte";
  import Pencil from "@lucide/svelte/icons/pencil";
  import Play from "@lucide/svelte/icons/play";
  import Plus from "@lucide/svelte/icons/plus";
  import { Button } from "$lib/components/ui/button";
  import * as NativeSelect from "$lib/components/ui/native-select";
  import { Textarea } from "$lib/components/ui/textarea";
  import PageHeader from "../components/PageHeader.svelte";
  import PageTitle from "../components/PageTitle.svelte";
  import StatusBadge from "../components/StatusBadge.svelte";
  import ModelChoice from "../components/ModelChoice.svelte";
  import { api } from "../lib/api";
  import { accessLabel } from "../lib/access";
  import type { Agent, ModelAccess, Project, Session } from "../lib/contracts.gen";
  import { agentLabel, presetOf, projects } from "../lib/projects.svelte";
  import { href, navigate } from "../lib/router.svelte";
  import { sessions } from "../lib/sessions.svelte";
  import { inFolder, sandboxStatus } from "../lib/agents";
  import LiveList from "../components/LiveList.svelte";
  import AgentSchedules from "../components/AgentSchedules.svelte";
  import type { AutomationView } from "../lib/contracts.gen";

  let { id }: { id: string } = $props();

  let project = $state<Project | null>(null);
  let list = $state<Session[]>([]);
  let outside = $state<Agent[]>([]); // agents outside projects working in its folder (`--anyway`): their terminals
  let error = $state<string | null>(null);
  let request = $state("");
  let agentId = $state("");
  let model = $state<ModelAccess | undefined>(); // the model chosen; undefined: the agent's first (D.1, D.19)
  let starting = $state(false);
  let showAll = $state(false);
  let automations = $state<AutomationView[]>([]);

  $effect(() => {
    void sessions.stopping.size; // a session closed here has stopped: load again
    const load = () =>
      Promise.all([api.project(id), api.sessions(), api.agents(), api.automations().catch(() => [])]).then(
        ([p, s, all, auto]) => {
          automations = auto;
          project = p;
          outside = all.filter((a) => !a.projectId && a.scope && inFolder(a.scope, p.folder));
          list = s.filter((x) => x.projectId === id && x.state !== "failed");
          if (!p.agents.some((a) => a.id === agentId)) agentId = p.defaultAgent ?? p.agents[0]?.id ?? "";
        },
        (e: Error) => (error = e.message),
      );
    void load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  });

  const agent = $derived(project?.agents.find((a) => a.id === agentId));
  const recent = $derived(list.filter((s) => s.state === "stopped"));
  // who started it, when not you in the web UI
  const ORIGIN: Record<string, string> = { cli: "terminal", editor: "editor", phone: "phone" };

  function agentOf(s: Session): Agent | undefined {
    return project?.agents.find((a) => a.id === s.agentId);
  }

  async function start(on: Agent | undefined = agent, text = request.trim(), runs = model): Promise<void> {
    if (!on) return;
    starting = true;
    error = null;
    try {
      const session = await sessions.start(on, undefined, text || undefined, runs);
      request = "";
      void projects.refresh();
      navigate({ view: "session", key: session.key });
    } catch (e) {
      error = (e as Error).message;
    } finally {
      starting = false;
    }
  }

  function open(s: Session): void {
    const on = agentOf(s);
    if (on) navigate({ view: "session", key: sessions.open(s, on).key });
  }

  function requestKey(e: KeyboardEvent): void {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      void start();
    }
  }
</script>

<PageHeader titled title={project?.name ?? "Project"} parent={{ label: "Projects", href: href({ view: "home" }) }}>
  {#snippet meta()}
    {#if project?.context}<ContextTag name={project.context} />{/if}
  {/snippet}
  {#snippet actions()}
    {#if project}
      <Button variant="ghost" size="sm" href={href({ view: "edit-project", id: project.id })} data-testid="project-edit"><Pencil />Project settings</Button>
    {/if}
  {/snippet}
</PageHeader>
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-4xl space-y-8 px-8 py-10">
    {#if error}<p class="text-sm text-danger" data-testid="project-error">{error}</p>{/if}
    {#if project}
      <div class="space-y-2">
        <PageTitle title={project.name} description={project.description ?? ""} />
        <p class="font-mono text-xs text-muted-foreground">{project.folder}</p>
      </div>

      <form class="space-y-3 rounded-lg border bg-card p-4" onsubmit={(e) => { e.preventDefault(); void start(); }} data-testid="project-start">
        {#if agent?.interface}
          <p class="text-sm text-muted-foreground" data-testid="project-agent-runs">
            {agentLabel(agent)} runs unattended: it is started with its form, and gives a result back.
          </p>
        {:else}
        <Textarea
          bind:value={request}
          onkeydown={requestKey}
          rows={3}
          placeholder="What do you want to do?"
          aria-label="request"
          aria-describedby="project-request-hint"
          class="resize-y border-0 bg-transparent p-0 shadow-none focus-visible:ring-0 dark:bg-transparent"
          data-testid="project-request"
        />
        <p id="project-request-hint" class="text-xs text-muted-foreground">
          Enter to start · Shift+Enter for a new line · Start with nothing typed opens an empty chat
        </p>
        {/if}
        <div class="flex flex-wrap items-center gap-2">
          <label class="text-sm text-muted-foreground" for="project-agent">Agent</label>
          <NativeSelect.Root id="project-agent" bind:value={agentId} class="min-w-56" data-testid="project-agent">
            {#each project.agents as a (a.id)}
              <NativeSelect.Option value={a.id}>{agentLabel(a)}{a.id === project.defaultAgent ? " (default)" : ""}</NativeSelect.Option>
            {/each}
          </NativeSelect.Root>
          {#if agent && !agent.interface}<ModelChoice {agent} bind:value={model} />{/if}
          {#if agent?.description}<span class="truncate text-xs text-muted-foreground">{agent.description}</span>{/if}
          {#if agent?.interface}
            <Button size="sm" class="ml-auto" href={href({ view: "agent", id: agent.id })} data-testid="project-new-run"><Play />New run</Button>
          {:else}
            <Button type="submit" size="sm" class="ml-auto" disabled={starting || !agent} data-testid="project-start-button"><Play />Start</Button>
          {/if}
        </div>
      </form>

      <LiveList agents={[...project.agents, ...outside]} {list} outside />

      <section class="space-y-2">
        <div class="flex items-center">
          <h2 class="text-xs font-medium tracking-wide text-muted-foreground uppercase">Agents</h2>
          <Button variant="ghost" size="sm" class="ml-auto" href={href({ view: "edit-agent", project: project.id })} data-testid="add-agent"><Plus />Add an agent</Button>
        </div>
        <ul class="divide-y overflow-hidden rounded-lg border bg-card" data-testid="project-agents">
          {#each project.agents as a (a.id)}
            <li class="flex items-start gap-3 px-4 py-3" data-testid="agent-row">
              {#if a.interface}
                <Button size="icon-sm" variant="outline" class="mt-0.5" href={href({ view: "agent", id: a.id })} title="A new run, on its page" aria-label={`run ${agentLabel(a)}`}>
                  <Play />
                </Button>
              {:else}
                <Button size="icon-sm" variant="outline" class="mt-0.5" onclick={() => start(a, "", undefined)} title="An empty chat with this agent" aria-label={`start ${agentLabel(a)}`}>
                  <Play />
                </Button>
              {/if}
              <div class="min-w-0 flex-1 space-y-1">
                <div class="flex flex-wrap items-center gap-2">
                  <a class="font-medium text-foreground [overflow-wrap:anywhere] hover:underline" href={href({ view: "agent", id: a.id })} data-testid="agent-name">{agentLabel(a)}</a>
                  {#if a.id === project.defaultAgent}
                    <span class="rounded bg-accent-soft px-1.5 py-px text-xs font-medium text-accent-soft-foreground">default</span>
                  {/if}
                  {#if a.interface}<span class="rounded bg-accent-soft px-1.5 py-px text-xs font-medium text-accent-soft-foreground">runs unattended</span>{/if}
                  <AgentSchedules {automations} name={a.name} project={project.name} />
                </div>
                {#if a.description}<p class="text-sm text-muted-foreground">{a.description}</p>{/if}
                <p class="text-xs text-muted-foreground">{a.models.map(accessLabel).join(" | ")}</p>
                <div class="flex flex-wrap gap-1 pt-0.5">
                  {#if presetOf(a)}
                    <StatusBadge status={`preset-${presetOf(a)?.id}`} />
                  {:else}
                    <StatusBadge status={a.egress === "log-only" ? "log-only" : a.network} />
                    <StatusBadge status={a.permissions} />
                    {#if sandboxStatus(a) !== "container"}<StatusBadge status={sandboxStatus(a)} />{/if}
                  {/if}
                  {#if a.display}<StatusBadge status="display" />{/if}
                </div>
              </div>
              <Button variant="ghost" size="icon-sm" href={href({ view: "edit-agent", project: project.id, id: a.id })} title="Edit" aria-label={`edit ${agentLabel(a)}`} data-testid="agent-edit">
                <Pencil />
              </Button>
            </li>
          {/each}
        </ul>
      </section>

      {#if recent.length}
        <section class="space-y-2">
          <h2 class="text-xs font-medium tracking-wide text-muted-foreground uppercase">Recent</h2>
          <ul class="divide-y overflow-hidden rounded-lg border bg-card" data-testid="project-recent">
            {#each showAll ? recent : recent.slice(0, 8) as s (s.id)}
              {@const on = agentOf(s)}
              <li class="flex items-center gap-3 px-3 py-2 text-sm">
                <span class="shrink-0 font-medium">{on ? agentLabel(on) : s.harness}</span>
                <span class="min-w-0 flex-1 truncate text-muted-foreground">{s.title ?? "—"}</span>
                {#if ORIGIN[s.origin ?? "ui"]}<span class="shrink-0 text-xs text-muted-foreground">{ORIGIN[s.origin ?? "ui"]}</span>{/if}
                <span class="shrink-0 text-xs text-muted-foreground"><When at={s.lastActivityAt} /></span>
                {#if s.canResume && on}
                  <Button variant="ghost" size="sm" onclick={() => open(s)} data-testid="resume-session">Resume</Button>
                {/if}
              </li>
            {/each}
          </ul>
          {#if recent.length > 8 && !showAll}
            <button type="button" class="cursor-pointer text-xs text-link hover:underline" onclick={() => (showAll = true)}>Show all {recent.length}</button>
          {/if}
        </section>
      {/if}

      <section class="space-y-1 text-sm">
        <h2 class="text-xs font-medium tracking-wide text-muted-foreground uppercase">Given to all its agents</h2>
        <p class="text-muted-foreground" data-testid="project-defaults">
          caches: {project.caches ?? "project"}
          · skills: {project.agents[0]?.projectSkills?.length ? project.agents[0].projectSkills.join(", ") : "none"}
          · <a class="text-link hover:underline" href={href({ view: "edit-project", id: project.id })}>change</a>
        </p>
      </section>
    {:else if !error}
      <p class="text-sm text-muted-foreground">Loading…</p>
    {/if}
  </div>
</div>
