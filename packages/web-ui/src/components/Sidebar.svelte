<script lang="ts">
  // What needs you (across projects), the projects with their open sessions, the ad-hoc agents
  // and the sessions outside any project (`handler run`); links to the
  // other pages. In
  // Settings (Linear-style) it is the settings nav instead: its sections by group, back to the app,
  // and still what needs you.
  import AppWindow from "@lucide/svelte/icons/app-window";
  import ArrowLeft from "@lucide/svelte/icons/arrow-left";
  import Bot from "@lucide/svelte/icons/bot";
  import KeyRound from "@lucide/svelte/icons/key-round";
  import Package from "@lucide/svelte/icons/package";
  import Palette from "@lucide/svelte/icons/palette";
  import Puzzle from "@lucide/svelte/icons/puzzle";
  import FolderOpen from "@lucide/svelte/icons/folder-open";
  import InboxIcon from "@lucide/svelte/icons/inbox";
  import Sparkles from "@lucide/svelte/icons/sparkles";
  import BookOpen from "@lucide/svelte/icons/book-open";
  import Database from "@lucide/svelte/icons/database";
  import FolderGit from "@lucide/svelte/icons/folder-git-2";
  import Tags from "@lucide/svelte/icons/tags";
  import { contexts } from "../lib/contexts.svelte";
  import ContextTag from "./ContextTag.svelte";
  import Logo from "./Logo.svelte";
  import Plus from "@lucide/svelte/icons/plus";
  import Workflow from "@lucide/svelte/icons/workflow";
  import Settings from "@lucide/svelte/icons/settings";
  import LayoutGrid from "@lucide/svelte/icons/layout-grid";
  import LockKeyhole from "@lucide/svelte/icons/lock-keyhole";
  import Smartphone from "@lucide/svelte/icons/smartphone";
  import X from "@lucide/svelte/icons/x";
  import * as Sidebar from "$lib/components/ui/sidebar";
  import { accessLabel } from "../lib/access";
  import type { Project } from "../lib/contracts.gen";
  import { agentLabel, byRecentUse, projects } from "../lib/projects.svelte";
  import { LIGHT_LABEL, lightTone, remote } from "../lib/remote.svelte";
  import { router, href } from "../lib/router.svelte";
  import { SETTINGS_GROUPS, type SettingsSection } from "../lib/settings";
  import { STATUS_LABEL, sessions, type LiveSession } from "../lib/sessions.svelte";
  import SessionStatus from "./SessionStatus.svelte";

  const SECTION_ICONS: Record<SettingsSection, typeof Settings> = {
    models: KeyRound,
    contexts: Tags,
    addons: Puzzle,
    secrets: LockKeyhole,
    folders: FolderOpen,
    caches: Database,
    remote: Smartphone,
    images: Package,
    appearance: Palette,
  };
  const MAX_PROJECTS = 8; // more: on the Projects page (projects with open sessions always show)

  const route = $derived(router.route);
  const attention = $derived(sessions.list.filter((s) => s.status === "needs-you" || s.status === "replied"));
  const openIn = (p: Project) => sessions.list.filter((s) => s.agent.projectId === p.id);
  const shown = $derived(byRecentUse(projects.list).filter((p, i) => i < MAX_PROJECTS || openIn(p).length));
  const outside = $derived(sessions.list.filter((s) => !projects.get(s.agent.projectId)));
  // an agent's page is under its project, when it has one
  const agentProject = $derived(route.view === "agent" ? projects.list.find((p) => p.agents.some((a) => a.id === route.id))?.id : undefined);
  const adHoc = $derived(["agents", "agent", "edit-ad-hoc", "run"].includes(route.view) && !agentProject);
  const current = $derived(
    route.view === "project" || route.view === "edit-project" ? route.id : route.view === "edit-agent" ? route.project : agentProject,
  );

  function close(session: LiveSession): void {
    const busy = session.status === "working" || session.status === "needs-you";
    if (busy && !confirm(`${projects.label(session.agent)} is working. Stop it?`)) return;
    void sessions.close(session);
    if (route.view === "session" && route.key === session.key) {
      const projectId = session.agent.projectId;
      window.location.hash = projectId && projects.get(projectId) ? href({ view: "project", id: projectId }) : href({ view: "home" });
    }
  }

  /** What the session says under its name: in "Needs you", what it waits for (the question when
   *  this tab is attached); elsewhere its dot says it, so only "elsewhere" is spelled out. */
  function hint(s: LiveSession, inbox: boolean): string | null {
    if (inbox && s.status === "needs-you") {
      const asked = s.conn?.permissions[0]?.request.toolCall.title;
      return asked ? `asks: ${asked}` : "waiting for you";
    }
    if ((inbox && s.status === "replied") || s.status === "elsewhere") return STATUS_LABEL[s.status];
    return null;
  }

  /** The agent's name inside a project; the full label elsewhere. */
  function name(s: LiveSession, inProject: boolean): string {
    const found = projects.of(s.agent);
    return inProject && found ? agentLabel(found.agent) : projects.label(s.agent);
  }
  void contexts.load();
</script>

{#snippet sessionItem(s: LiveSession, inProject: boolean, inbox = false)}
  {@const active = route.view === "session" && route.key === s.key}
  {@const note = hint(s, inbox)}
  <Sidebar.MenuItem>
    <Sidebar.MenuButton isActive={active} class="h-auto items-start py-1.5 {inProject ? 'pl-4' : ''}">
      {#snippet child({ props })}
        <a href={href({ view: "session", key: s.key })} title={`${accessLabel(s.info)} in ${s.info.scope}`} data-testid="session-item" {...props}>
          <span class="mt-0.5 grid size-4 shrink-0 place-items-center"><SessionStatus status={s.status} /></span>
          <span class="flex min-w-0 flex-col">
            {#if inbox}
              <span class="truncate font-medium text-sidebar-accent-foreground">{name(s, inProject)}</span>
              {#if s.title}<span class="truncate text-xs text-muted-foreground">{s.title}</span>{/if}
            {:else}
              <span class="truncate">
                <span class="font-medium text-sidebar-accent-foreground">{name(s, inProject)}</span>
                {#if s.title}<span class="text-muted-foreground"> · {s.title}</span>{/if}
              </span>
            {/if}
            {#if remote.shared(s.key)}<span class="text-xs text-muted-foreground">shared remotely</span>{/if}
            {#if note}
              <span class="line-clamp-2 text-xs [overflow-wrap:anywhere] {s.status === 'needs-you' ? 'font-semibold text-warn' : 'text-link'}">{note}</span>
            {/if}
          </span>
        </a>
      {/snippet}
    </Sidebar.MenuButton>
    <Sidebar.MenuAction showOnHover aria-label="close session" title="close session" onclick={() => close(s)}>
      <X />
    </Sidebar.MenuAction>
  </Sidebar.MenuItem>
{/snippet}

{#snippet settingsNav()}
  <Sidebar.Header>
    <a class="flex items-center gap-2 px-2 py-1.5 text-sm text-muted-foreground no-underline hover:text-sidebar-accent-foreground" href={href({ view: "home" })} data-testid="settings-back">
      <ArrowLeft class="size-4" />Back to app
    </a>
  </Sidebar.Header>
  <Sidebar.Content>
    {#each SETTINGS_GROUPS as g (g.label)}
      <Sidebar.Group>
        <Sidebar.GroupLabel>{g.label}</Sidebar.GroupLabel>
        <Sidebar.Menu>
          {#each g.sections as s (s.id)}
            {@const Icon = SECTION_ICONS[s.id]}
            <Sidebar.MenuItem>
              <Sidebar.MenuButton isActive={route.view === "settings" && route.section === s.id}>
                {#snippet child({ props })}
                  <a href={href({ view: "settings", section: s.id })} {...props} data-testid="settings-nav-{s.id}">
                    <Icon /><span>{s.label}</span>
                    {#if s.id === "remote" && remote.status && remote.status.light !== "off"}
                      <span class="ml-auto size-2 rounded-full {lightTone(remote.status.light)}" aria-label={LIGHT_LABEL[remote.status.light]}></span>
                    {/if}
                  </a>
                {/snippet}
              </Sidebar.MenuButton>
            </Sidebar.MenuItem>
          {/each}
        </Sidebar.Menu>
      </Sidebar.Group>
    {/each}
    {@render needsYou()}
  </Sidebar.Content>
{/snippet}

{#snippet needsYou()}
  {#if attention.length}
    <Sidebar.Group>
      <Sidebar.GroupLabel>Needs you</Sidebar.GroupLabel>
      <Sidebar.Menu aria-label="sessions needing you" data-testid="needs-you">
        {#each attention as s (s.key)}
          {@render sessionItem(s, false, true)}
        {/each}
      </Sidebar.Menu>
    </Sidebar.Group>
  {/if}
{/snippet}

<Sidebar.Root variant="inset">
  {#if route.view === "settings"}
    {@render settingsNav()}
  {:else}
    <Sidebar.Header>
      <a class="flex items-center gap-2 px-2 py-1.5 text-sm font-semibold text-sidebar-accent-foreground no-underline" href={href({ view: "home" })}>
        <Logo class="size-6" />
        Handler
      </a>
      <Sidebar.Menu>
        <Sidebar.MenuItem>
          <Sidebar.MenuButton isActive={route.view === "home"}>
            {#snippet child({ props })}
              <a href={href({ view: "home" })} {...props} data-testid="projects-link"><LayoutGrid /><span>Projects</span></a>
            {/snippet}
          </Sidebar.MenuButton>
        </Sidebar.MenuItem>
        <Sidebar.MenuItem>
          <Sidebar.MenuButton isActive={route.view === "inbox"}>
            {#snippet child({ props })}
              <a href={href({ view: "inbox" })} {...props} data-testid="inbox-link"><InboxIcon /><span>Inbox</span></a>
            {/snippet}
          </Sidebar.MenuButton>
        </Sidebar.MenuItem>
        <Sidebar.MenuItem>
          <Sidebar.MenuButton isActive={route.view === "apps"}>
            {#snippet child({ props })}
              <a href={href({ view: "apps" })} {...props} data-testid="apps-link"><AppWindow /><span>Apps</span></a>
            {/snippet}
          </Sidebar.MenuButton>
        </Sidebar.MenuItem>
        <Sidebar.MenuItem>
          <Sidebar.MenuButton isActive={route.view === "automations" || route.view === "automation" || route.view === "edit-automation"}>
            {#snippet child({ props })}
              <a href={href({ view: "automations" })} {...props} data-testid="automations-link"><Workflow /><span>Automations</span></a>
            {/snippet}
          </Sidebar.MenuButton>
        </Sidebar.MenuItem>
        <Sidebar.MenuItem>
          <Sidebar.MenuButton isActive={route.view === "skills" || route.view === "skill"}>
            {#snippet child({ props })}
              <a href={href({ view: "skills" })} {...props} data-testid="skills-link"><Sparkles /><span>Skills</span></a>
            {/snippet}
          </Sidebar.MenuButton>
        </Sidebar.MenuItem>
        <Sidebar.MenuItem>
          <Sidebar.MenuButton isActive={route.view === "knowledge"}>
            {#snippet child({ props })}
              <a href={href({ view: "knowledge" })} {...props} data-testid="knowledge-link"><BookOpen /><span>Knowledge</span></a>
            {/snippet}
          </Sidebar.MenuButton>
        </Sidebar.MenuItem>
      </Sidebar.Menu>
    </Sidebar.Header>

    <Sidebar.Content>
      {#if sessions.loadError}<p class="px-4 text-xs text-danger" data-testid="sessions-error">{sessions.loadError}</p>{/if}

      {@render needsYou()}

      <Sidebar.Group>
        <Sidebar.GroupLabel>Projects</Sidebar.GroupLabel>
        <Sidebar.Menu aria-label="projects">
          {#each shown as p (p.id)}
            {@const open = openIn(p)}
            <Sidebar.MenuItem>
              <Sidebar.MenuButton isActive={current === p.id}>
                {#snippet child({ props })}
                  <a href={href({ view: "project", id: p.id })} title={p.folder} data-testid="sidebar-project" {...props}>
                    <FolderGit class={p.context ? `ctx-icon ${contexts.colorClass(p.context)}` : ""} /><span class="truncate">{p.name}</span>
                    {#if p.context}<span class="ml-auto shrink-0 {open.length ? 'mr-5' : ''}"><ContextTag name={p.context} /></span>{/if}
                  </a>
                {/snippet}
              </Sidebar.MenuButton>
              {#if open.length}<Sidebar.MenuBadge>{open.length}</Sidebar.MenuBadge>{/if}
            </Sidebar.MenuItem>
            {#each open as s (s.key)}
              {@render sessionItem(s, true)}
            {/each}
          {/each}
          <Sidebar.MenuItem>
            <Sidebar.MenuButton>
              {#snippet child({ props })}
                <a href={href({ view: "edit-project" })} class="text-muted-foreground" {...props} data-testid="sidebar-new-project"><Plus /><span>New project</span></a>
              {/snippet}
            </Sidebar.MenuButton>
          </Sidebar.MenuItem>
        </Sidebar.Menu>
      </Sidebar.Group>

      <Sidebar.Group>
        <Sidebar.GroupLabel>Outside projects</Sidebar.GroupLabel>
        <Sidebar.Menu aria-label="agents outside projects">
          <Sidebar.MenuItem>
            <Sidebar.MenuButton isActive={adHoc}>
              {#snippet child({ props })}
                <a href={href({ view: "agents" })} {...props} data-testid="sidebar-agents"><Bot /><span>Agents</span></a>
              {/snippet}
            </Sidebar.MenuButton>
          </Sidebar.MenuItem>
          {#each outside as s (s.key)}
            {@render sessionItem(s, false)}
          {/each}
        </Sidebar.Menu>
      </Sidebar.Group>
    </Sidebar.Content>

    <Sidebar.Footer>
      <Sidebar.Menu>
        {#if remote.status && remote.status.light !== "off"}
          <Sidebar.MenuItem>
            <Sidebar.MenuButton>
              {#snippet child({ props })}
                <a href={href({ view: "settings", section: "remote" })} {...props} title={remote.status?.detail ?? LIGHT_LABEL[remote.status!.light]} data-testid="remote-status">
                  <Smartphone /><span>Remote</span>
                  <span class="ml-auto size-2 rounded-full {lightTone(remote.status!.light)}" aria-label={LIGHT_LABEL[remote.status!.light]}></span>
                </a>
              {/snippet}
            </Sidebar.MenuButton>
          </Sidebar.MenuItem>
        {/if}
        <Sidebar.MenuItem>
          <Sidebar.MenuButton>
            {#snippet child({ props })}
              <a href={href({ view: "settings", section: "models" })} {...props} data-testid="settings-link"><Settings /><span>Settings</span></a>
            {/snippet}
          </Sidebar.MenuButton>
        </Sidebar.MenuItem>
      </Sidebar.Menu>
    </Sidebar.Footer>
  {/if}
</Sidebar.Root>
