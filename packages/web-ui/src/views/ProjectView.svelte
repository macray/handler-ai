<script lang="ts">
  // A project's page: its header (Projects ›, its name, its folder and branch, its pin and ⋯:
  // Export agents, Get agents…: Library → Agents → Get more for this project), then four tabs. Sessions: its agents as
  // one row of tabs (AgentTabs: the rest under "+N more", + to add one, Edit in the chosen one),
  // the chosen one's box (who works and what it gets and may do, as chips in its footer:
  // AgentWorkspace), what waits for you (answered in place
  // when this tab is attached to it), and what the agent did; with no agent yet, NoAgentYet (a
  // suggestion added in one click, Set up an agent, Get agents…). Plans, Automations: this project's
  // (ProjectPlans, ProjectAutomations). Settings: the project's own (ProjectEditor), Delete last.
  import AppWindow from "@lucide/svelte/icons/app-window";
  import Ellipsis from "@lucide/svelte/icons/ellipsis";
  import Download from "@lucide/svelte/icons/download";
  import GitBranch from "@lucide/svelte/icons/git-branch";
  import SquareArrowOutUpRight from "@lucide/svelte/icons/square-arrow-out-up-right";
  import Store from "@lucide/svelte/icons/store";
  import { Button } from "$lib/components/ui/button";
  import AgentTabs from "../components/AgentTabs.svelte";
  import AgentWorkspace from "../components/AgentWorkspace.svelte";
  import AreaTag from "../components/AreaTag.svelte";
  import ExportAgentsDialog from "../components/ExportAgentsDialog.svelte";
  import LiveList from "../components/LiveList.svelte";
  import NoAgentYet from "../components/NoAgentYet.svelte";
  import PageHeader, { type PageTab } from "../components/PageHeader.svelte";
  import PinButton from "../components/PinButton.svelte";
  import Popover from "../components/Popover.svelte";
  import ProjectAutomations from "../components/ProjectAutomations.svelte";
  import ProjectEditor from "../components/ProjectEditor.svelte";
  import ProjectPlans from "../components/ProjectPlans.svelte";
  import SessionStatus from "../components/SessionStatus.svelte";
  import When from "../components/When.svelte";
  import { inFolder } from "../lib/agents";
  import { api } from "../lib/api";
  import { bell, question } from "../lib/bell.svelte";
  import type { Agent, App, AutomationView, Project, Session } from "../lib/contracts.gen";
  import { agentLabel, projects } from "../lib/projects.svelte";
  import { href, navigate, type ProjectTab } from "../lib/router.svelte";
  import { sessions, type SessionStatus as Status } from "../lib/sessions.svelte";

  let { id, agent: chosenId, tab }: { id: string; agent?: string; tab?: ProjectTab } = $props();

  const WIDTH = "max-w-4xl";

  let project = $state<Project | null>(null);
  let list = $state<Session[]>([]); // its sessions and runs, any state
  let outside = $state<Agent[]>([]); // agents outside projects working in its folder (`--anyway`): their terminals
  let automations = $state<AutomationView[]>([]);
  let apps = $state<App[]>([]); // those given its folder (H.14): they live in Apps
  let appRuns = $state<Session[]>([]); // their runs (their agents work in its folder)
  let planCount = $state(0); // its plans not finished, and those being written
  let error = $state<string | null>(null);
  let exporting = $state(false); // Export agents (D.23)
  let menuOpen = $state(false);
  let saves = $state(0); // the settings' editor starts again from what was saved

  async function load(): Promise<void> {
    try {
      const [p, s, all, auto, a, plans, drafts] = await Promise.all([
        api.project(id),
        api.sessions(),
        api.agents(),
        api.automations().catch(() => []),
        api.apps().catch(() => []),
        api.plans(id).catch(() => []),
        api.planDrafts(id).catch(() => []),
      ]);
      automations = auto;
      apps = a.filter((x) => p.apps?.includes(x.name));
      appRuns = s.filter((x) => x.app && p.apps?.includes(x.app));
      planCount = plans.filter((x) => x.state !== "done").length + drafts.length;
      project = p;
      outside = all.filter((x) => !x.projectId && x.scope && inFolder(x.scope, p.folder));
      list = s.filter((x) => x.projectId === id);
    } catch (e) {
      error = (e as Error).message;
    }
  }

  $effect(() => {
    void sessions.stopping.size; // a session closed here has stopped: load again
    void load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  });

  const agent = $derived(
    project?.agents.find((a) => a.id === chosenId) ?? project?.agents.find((a) => a.id === project?.defaultAgent) ?? project?.agents[0],
  );
  const isLive = (s: Session) => (s.state === "running" || s.state === "starting") && !sessions.stopping.has(s.id);
  // what waits for you here, whichever agent is chosen: those this tab knows (answered in place
  // when attached), then those it does not (opened)
  const waitingHere = $derived(bell.waiting.filter((s) => s.info.projectId === id));
  const waitingElse = $derived(list.filter((s) => isLive(s) && s.pendingPermissions && !waitingHere.some((w) => w.info.id === s.id)));
  const theirAutomations = $derived(project ? automations.filter((a) => project?.agents.some((g) => g.id === a.agentId)) : []);

  const tabs = $derived<PageTab[]>([
    { label: "Sessions", href: href({ view: "project", id }), active: !tab, testid: "project-tab-sessions" },
    { label: "Plans", href: href({ view: "project", id, tab: "plans" }), active: tab === "plans", count: planCount, testid: "project-plans" },
    { label: "Automations", href: href({ view: "project", id, tab: "automations" }), active: tab === "automations", count: theirAutomations.length, testid: "project-tab-automations" },
    { label: "Settings", href: href({ view: "project", id, tab: "settings" }), active: tab === "settings", testid: "project-edit" },
  ]);

  // an agent's dot on its tab: waits for you, works, or open
  function dotOf(a: Agent): Status | null {
    const open = list.filter((s) => s.agentId === a.id && isLive(s));
    if (open.some((s) => s.pendingPermissions)) return "needs-you";
    if (open.some((s) => s.busy)) return "working";
    return open.length ? "idle" : null;
  }

  function choose(a: Agent): void {
    navigate({ view: "project", id, agent: a.id }, true);
  }

  function open(s: Session): void {
    const on = project?.agents.find((a) => a.id === s.agentId);
    if (on) navigate({ view: "session", key: sessions.open(s, on).key });
  }

  function saved(p?: Project): void {
    if (p) ((project = p), saves++);
    void projects.refresh();
    void load();
  }

  async function remove(): Promise<void> {
    if (!project) return;
    const running = project.agents.reduce((n, a) => n + a.connections.length, 0);
    const also = running ? ` Its ${running} running agent(s) are stopped.` : "";
    if (!confirm(`Delete the project ${project.name} and its agents? The folder stays as it is.${also}`)) return;
    try {
      await api.deleteProject(project.id);
      void projects.refresh();
      navigate({ view: "projects" }, true);
    } catch (e) {
      error = (e as Error).message;
    }
  }
</script>

<PageHeader title={project?.name ?? "Project"} parent={{ label: "Projects", href: href({ view: "projects" }) }} tabs={project ? tabs : undefined} width={WIDTH}>
  {#snippet meta()}
    {#if project?.area}<AreaTag name={project.area} />{/if}
  {/snippet}
  {#snippet sub()}
    {#if project}
      <span class="fact truncate" title={project.folder} data-testid="project-folder">{project.folder}</span>
      {#if project.branch}<span class="inline-flex items-center gap-1 rounded-md border px-1.5 py-px" title="Its git branch" data-testid="project-branch"><GitBranch class="size-3" />{project.branch}</span>{/if}
      {#if project.description}<span class="basis-full text-sm">{project.description}</span>{/if}
    {/if}
  {/snippet}
  {#snippet menu()}
    {#if project}
      <PinButton kind="project" id={project.id} label={project.name} />
      <Popover bind:open={menuOpen} align="end" label="More" width="15rem" testid="project-menu">
        {#snippet trigger(props)}
          <Button variant="ghost" size="icon" class="size-8 text-muted-foreground" {...props} aria-label="More" data-testid="project-more"><Ellipsis /></Button>
        {/snippet}
        {#snippet children(close)}
          <button type="button" class="menu-item" onclick={() => ((exporting = true), close())} data-testid="project-export-agents"><Download />Export agents</button>
          <button type="button" class="menu-item" onclick={() => (close(), project && navigate({ view: "library", shelf: "agents", more: true, project: project.id }))} title="In the Library: agents a source offers, or exported from a project" data-testid="get-agents"><Store />Get agents…</button>
        {/snippet}
      </Popover>
    {/if}
  {/snippet}
</PageHeader>
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full {WIDTH} space-y-5 px-8 py-6">
    {#if error}<p class="text-sm text-danger" data-testid="project-error">{error}</p>{/if}

    {#if !project}
      {#if !error}<p class="text-sm text-muted-foreground">Loading…</p>{/if}
    {:else if tab === "plans"}
      <ProjectPlans {project} />
    {:else if tab === "automations"}
      <ProjectAutomations {project} automations={automations} onchanged={load} />
    {:else if tab === "settings"}
      {#key saves}
        <ProjectEditor {project} onsaved={saved} oncancel={() => {}} ondelete={remove} />
      {/key}
    {:else if !project.agents.length}
      <NoAgentYet {project} onadded={(a) => (saved(), choose(a))} />
    {:else}
      <AgentTabs
        agents={project.agents}
        chosen={agent}
        {dotOf}
        onchoose={choose}
        edit={(a) => href({ view: "edit-agent", project: project!.id, id: a.id })}
        add={href({ view: "edit-agent", project: project.id })}
      />

      {#if agent}
        <AgentWorkspace
          {agent}
          {list}
          {automations}
          tabbed
          caches={project.caches}
          edit={href({ view: "edit-agent", project: project.id, id: agent.id })}
          onstarted={() => void projects.refresh()}
          onchanged={() => saved()}
        >
          {#snippet waiting()}
            {#each waitingHere as s (s.key)}
              {@const q = question(s)}
              <div class="waiting" data-testid="project-waiting">
                <SessionStatus status="needs-you" />
                <b class="font-semibold">{agentLabel(s.agent)}</b>
                {#if q}<span class="text-muted-foreground">asks</span><code class="ask min-w-0 truncate">{q.title}</code>{:else}<span class="min-w-0 truncate text-muted-foreground">needs you in “{s.title ?? "untitled"}”</span>{/if}
                <span class="ml-auto flex shrink-0 gap-1.5">
                  {#if q?.allow}
                    <Button size="sm" onclick={() => q.answer({ outcome: "selected", optionId: q.allow!.optionId })} data-testid="project-waiting-allow">Allow</Button>
                    {#if q.reject}<Button size="sm" variant="outline" onclick={() => q.answer({ outcome: "selected", optionId: q.reject!.optionId })} data-testid="project-waiting-reject">No</Button>{/if}
                  {/if}
                  <Button size="sm" variant="ghost" href={href({ view: "session", key: s.key })}>Open</Button>
                </span>
              </div>
            {/each}
            {#each waitingElse as s (s.id)}
              {@const on = project?.agents.find((a) => a.id === s.agentId)}
              <div class="waiting" data-testid="project-waiting">
                <SessionStatus status="needs-you" />
                <b class="font-semibold">{on ? agentLabel(on) : s.harness}</b>
                <span class="min-w-0 truncate text-muted-foreground">needs you in “{s.title ?? "untitled"}”</span>
                <Button size="sm" variant="ghost" class="ml-auto" onclick={() => open(s)}>Open</Button>
              </div>
            {/each}
          {/snippet}
        </AgentWorkspace>
      {/if}
      <LiveList agents={outside} />

      {#if apps.length}
        <section class="space-y-2">
          <h2 class="section-label">Apps using this folder</h2>
          <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm" data-testid="project-apps">
            {#each apps as a (a.name)}
              {@const last = appRuns.filter((r) => r.app === a.name).sort((x, y) => y.createdAt.localeCompare(x.createdAt))[0]}
              <li class="flex items-center gap-2 px-4 py-2.5">
                <AppWindow class="size-4 text-primary" />
                <a class="text-foreground no-underline hover:underline" href={href({ view: "apps", app: a.name })} title="Its page" data-testid="project-app">{a.name}</a>
                <span class="min-w-0 flex-1 truncate text-xs text-muted-foreground">
                  {(a.files ?? []).some((f) => f.mode === "rw" && f.path && project && inFolder(f.path, project.folder)) ? "reads and writes it" : "reads it"}{#if last}{" · its agent ran "}<When at={last.createdAt} />{/if}
                </span>
                {#if a.current}<a href={a.url} target="_blank" rel="noreferrer" title="Open it" class="text-muted-foreground hover:text-foreground"><SquareArrowOutUpRight class="size-3.5" /></a>{/if}
              </li>
            {/each}
          </ul>
        </section>
      {/if}
    {/if}
  </div>
</div>
{#if project}
  <ExportAgentsDialog bind:open={exporting} projectId={project.id} place={project.name} agents={project.agents} />
{/if}

<style>
  .waiting {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 10px 8px 14px;
    border: 1px solid color-mix(in oklab, var(--warn) 45%, transparent);
    border-radius: 10px;
    background: var(--card);
    font-size: 14px;
  }
  .ask {
    padding: 3px 8px;
    border-radius: 6px;
    background: #1d1b19;
    color: #ddd8cf;
    font-size: 12.5px;
  }
</style>
