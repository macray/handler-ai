<script lang="ts">
  // A project: its facts on one line, what waits for you (whichever agent), and its agents. One
  // is chosen (the route's, else its default) and the rest of the page is that agent's, read the
  // same way for every agent: who it is, how it starts, what it did. An agent without an
  // interface starts from a request (a session); one with an interface (D.18) from its form (a
  // run, unattended). Each starts "in [program] on [account or provider] with [model]" (ModelChoice).
  import AppWindow from "@lucide/svelte/icons/app-window";
  import Download from "@lucide/svelte/icons/download";
  import FileUp from "@lucide/svelte/icons/file-up";
  import CalendarClock from "@lucide/svelte/icons/calendar-clock";
  import SquareArrowOutUpRight from "@lucide/svelte/icons/square-arrow-out-up-right";
  import StatusBadge from "../components/StatusBadge.svelte";
  import When from "../components/When.svelte";
  import { whenSentence } from "../lib/automations";
  import Database from "@lucide/svelte/icons/database";
  import Folder from "@lucide/svelte/icons/folder";
  import Plus from "@lucide/svelte/icons/plus";
  import Settings from "@lucide/svelte/icons/settings";
  import Sparkles from "@lucide/svelte/icons/sparkles";
  import Store from "@lucide/svelte/icons/store";
  import { Button } from "$lib/components/ui/button";
  import AgentPick from "../components/AgentPick.svelte";
  import AgentWorkspace from "../components/AgentWorkspace.svelte";
  import AreaTag from "../components/AreaTag.svelte";
  import LiveList from "../components/LiveList.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import ExportAgentsDialog from "../components/ExportAgentsDialog.svelte";
  import SourceAgentsDialog from "../components/SourceAgentsDialog.svelte";
  import SessionStatus from "../components/SessionStatus.svelte";
  import { accessLabel } from "../lib/access";
  import { inFolder } from "../lib/agents";
  import { api } from "../lib/api";
  import type { Agent, App, AutomationView, Project, Session } from "../lib/contracts.gen";
  import { agentLabel, projects } from "../lib/projects.svelte";
  import { href, navigate } from "../lib/router.svelte";
  import { sessions, type SessionStatus as Status } from "../lib/sessions.svelte";

  let { id, agent: chosenId }: { id: string; agent?: string } = $props();

  let project = $state<Project | null>(null);
  let list = $state<Session[]>([]); // its sessions and runs, any state
  let outside = $state<Agent[]>([]); // agents outside projects working in its folder (`--anyway`): their terminals
  let automations = $state<AutomationView[]>([]);
  let apps = $state<App[]>([]); // those given its folder (H.14): they live in Apps
  let appRuns = $state<Session[]>([]); // their runs (their agents work in its folder)
  let error = $state<string | null>(null);
  let exporting = $state(false); // Export agents (D.23)
  let fileInput = $state<HTMLInputElement | null>(null);
  let fromSource = $state(false); // Add agents from a source (D.26)

  /** An agents file read: its agents set up into this project, on their own page. */
  async function importFile(file: File | undefined): Promise<void> {
    if (!file || !project) return;
    try {
      const read = await api.importAgents(file);
      navigate({ view: "setup", file: read.name, project: project.id });
    } catch (e) {
      error = `${file.name}: ${(e as Error).message}`;
    }
  }

  $effect(() => {
    void sessions.stopping.size; // a session closed here has stopped: load again
    const load = () =>
      Promise.all([api.project(id), api.sessions(), api.agents(), api.automations().catch(() => []), api.apps().catch(() => [])]).then(
        ([p, s, all, auto, a]) => {
          automations = auto;
          apps = a.filter((x) => p.apps?.includes(x.name));
          appRuns = s.filter((x) => x.app && p.apps?.includes(x.app));
          project = p;
          outside = all.filter((a) => !a.projectId && a.scope && inFolder(a.scope, p.folder));
          list = s.filter((x) => x.projectId === id);
        },
        (e: Error) => (error = e.message),
      );
    void load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  });

  // what runs by itself: the automations that run its agents
  const scheduled = $derived(automations.filter((a) => project?.agents.some((g) => g.id === a.agentId)));

  const agent = $derived(
    project?.agents.find((a) => a.id === chosenId) ?? project?.agents.find((a) => a.id === project?.defaultAgent) ?? project?.agents[0],
  );
  const isLive = (s: Session) => (s.state === "running" || s.state === "starting") && !sessions.stopping.has(s.id);
  const waiting = $derived(list.filter((s) => isLive(s) && s.pendingPermissions));

  // an agent's dot in the list: waits for you, works, or open
  function dotOf(a: Agent): Status | null {
    const open = list.filter((s) => s.agentId === a.id && isLive(s));
    if (open.some((s) => s.pendingPermissions)) return "needs-you";
    if (open.some((s) => s.busy)) return "working";
    return open.length ? "idle" : null;
  }

  function choose(a: Agent): void {
    navigate({ view: "project", id, agent: a.id }, true);
  }

  function agentOf(s: Session): Agent | undefined {
    return project?.agents.find((a) => a.id === s.agentId);
  }

  function open(s: Session): void {
    const on = agentOf(s);
    if (on) navigate({ view: "session", key: sessions.open(s, on).key });
  }
</script>

<PageHeader titled title={project?.name ?? "Project"} parent={{ label: "Projects", href: href({ view: "home" }) }}>
  {#snippet actions()}
    {#if project}
      <Button variant="ghost" size="sm" onclick={() => (exporting = true)} data-testid="project-export-agents"><Download />Export agents</Button>
      <Button variant="ghost" size="sm" href={href({ view: "edit-project", id: project.id })} data-testid="project-edit"><Settings />Settings</Button>
    {/if}
  {/snippet}
</PageHeader>
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-6xl space-y-5 px-8 py-8">
    {#if project}
      <div class="space-y-1">
        <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
          <h1 class="text-2xl leading-tight font-semibold tracking-[-0.02em]">{project.name}</h1>
          {#if project.area}<AreaTag name={project.area} />{/if}
          <p class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground" data-testid="project-defaults">
            <span class="inline-flex min-w-0 items-center gap-1.5" title={project.folder}><Folder class="size-3.5 shrink-0" /><span class="fact truncate">{project.folder}</span></span>
            <span class="inline-flex items-center gap-1.5" title="Toolchain caches, for all its agents"><Database class="size-3.5" />caches: {project.caches === "global" ? "global" : project.caches === "off" ? "off" : "this project"}</span>
            {#if agent?.projectSkills?.length}
              <span class="inline-flex items-center gap-1.5" title="Given to all its agents"><Sparkles class="size-3.5" />skills: {agent.projectSkills.join(", ")}</span>
            {/if}
          </p>
        </div>
        {#if project.description}<p class="text-sm text-muted-foreground">{project.description}</p>{/if}
      </div>
    {/if}
    {#if error}<p class="text-sm text-danger" data-testid="project-error">{error}</p>{/if}

    {#if project}
      <!-- what waits for you, whichever agent is chosen -->
      {#each waiting as s (s.id)}
        {@const on = agentOf(s)}
        <div class="flex items-center gap-3 rounded-lg bg-warn/10 px-3 py-2 text-sm" data-testid="project-waiting">
          <SessionStatus status="needs-you" />
          <span class="min-w-0 flex-1 truncate"><b class="font-semibold">{on ? agentLabel(on) : s.harness}</b> needs you in “{s.title ?? "untitled"}”</span>
          <Button variant="outline" size="sm" onclick={() => open(s)}>Open</Button>
        </div>
      {/each}
      <LiveList agents={outside} list={[]} outside />

      <div class="grid items-start gap-6 md:grid-cols-[15rem_minmax(0,1fr)]">
        <nav class="space-y-0.5" aria-label="agents">
          <h2 class="section-label px-2.5 pb-1.5">Agents</h2>
          <ul class="space-y-0.5" data-testid="project-agents">
            {#each project.agents as a (a.id)}
              <AgentPick
                agent={a}
                chosen={a.id === agent?.id}
                dot={dotOf(a)}
                about={a.description ?? accessLabel(a.model)}
                isDefault={a.id === project.defaultAgent}
                onclick={() => choose(a)}
              />
            {/each}
          </ul>
          <Button variant="ghost" size="sm" class="w-full justify-start text-muted-foreground" href={href({ view: "edit-agent", project: project.id })} data-testid="add-agent"><Plus />Add an agent</Button>
          <Button variant="ghost" size="sm" class="w-full justify-start text-muted-foreground" onclick={() => fileInput?.click()} title="Agents exported from a project, here or elsewhere" data-testid="add-agent-file"
            ><FileUp />Add agents from a file</Button
          >
          <Button variant="ghost" size="sm" class="w-full justify-start text-muted-foreground" onclick={() => (fromSource = true)} title="Agents Handler or a source you added offers" data-testid="add-agent-source"
            ><Store />Add agents from a source</Button
          >
          <SourceAgentsDialog bind:open={fromSource} onread={(read) => project && navigate({ view: "setup", file: read.name, project: project.id })} />
          <input bind:this={fileInput} type="file" accept=".zip,application/zip" class="hidden" onchange={(e) => importFile(e.currentTarget.files?.[0])} data-testid="add-agent-file-input" />
          {#if apps.length}
            <h2 class="section-label px-2.5 pt-4 pb-1.5">Apps using this folder</h2>
            <ul class="space-y-0.5" data-testid="project-apps">
              {#each apps as a (a.name)}
                {@const last = appRuns.filter((r) => r.app === a.name).sort((x, y) => y.createdAt.localeCompare(x.createdAt))[0]}
                <li class="space-y-0.5 rounded-lg px-2.5 py-1.5 text-sm hover:bg-muted/60">
                  <div class="flex items-center gap-2">
                    <AppWindow class="size-4 text-primary" />
                    <a class="min-w-0 flex-1 truncate text-foreground no-underline" href={href({ view: "apps", app: a.name })} title="Its page" data-testid="project-app">{a.name}</a>
                    {#if a.current}<a href={a.url} target="_blank" rel="noreferrer" title="Open it" class="text-muted-foreground hover:text-foreground"><SquareArrowOutUpRight class="size-3.5" /></a>{/if}
                  </div>
                  <p class="pl-6 text-xs text-muted-foreground">
                    {(a.files ?? []).some((f) => f.mode === "rw" && f.path && project && inFolder(f.path, project.folder)) ? "reads and writes it" : "reads it"}{#if last}{" · its agent ran "}<When at={last.createdAt} />{/if}
                  </p>
                </li>
              {/each}
            </ul>
          {/if}
          {#if scheduled.length}
            <h2 class="section-label px-2.5 pt-4 pb-1.5">Runs by itself</h2>
            <ul class="space-y-0.5" data-testid="project-scheduled">
              {#each scheduled as a (a.name)}
                <li class="space-y-0.5 rounded-lg px-2.5 py-1.5 text-sm hover:bg-muted/60">
                  <a class="flex items-center gap-2 text-foreground no-underline" href={href({ view: "automation", name: a.name })}>
                    <CalendarClock class="size-4 text-muted-foreground" /><span class="min-w-0 flex-1 truncate">{a.name}</span><StatusBadge status={a.enabled ? "on" : "off"} />
                  </a>
                  <p class="pl-6 text-xs text-muted-foreground">{whenSentence(a.definition)}</p>
                </li>
              {/each}
            </ul>
          {/if}
        </nav>

        {#if agent}
          <AgentWorkspace
            {agent}
            {list}
            {automations}
            edit={href({ view: "edit-agent", project: project.id, id: agent.id })}
            onstarted={() => void projects.refresh()}
            onchanged={() => void projects.refresh()}
          >
            {#snippet tags()}
              {#if agent.id === project?.defaultAgent}<span class="rounded bg-accent-soft px-1.5 py-px text-xs font-medium text-accent-soft-foreground">default</span>{/if}
            {/snippet}
          </AgentWorkspace>
        {/if}
      </div>
    {:else if !error}
      <p class="text-sm text-muted-foreground">Loading…</p>
    {/if}
  </div>
</div>
{#if project}
  <ExportAgentsDialog bind:open={exporting} projectId={project.id} place={project.name} agents={project.agents} />
{/if}
