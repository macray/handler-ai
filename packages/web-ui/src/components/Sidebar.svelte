<script lang="ts">
  // The menu, which never moves, by question: what I want (Ask, D.24), where my things are, what I
  // am told, what runs by itself (Projects, Inbox, Schedule: the automations; the inbox counting its unread messages);
  // the pinned projects under their area's name (lib/menu.ts), each with one dot for its sessions,
  // then Other folders (a place always there: the agents of no project that are not Chat's); the
  // apps: Chat first (Handler's own, always there), then yours, each opening its page (none yet: a
  // row to get one, D.26); the library (Discover: what the sources offer; what agents are
  // given: Skills, Knowledge, Addons); and at its foot the open sessions of every project (under
  // "waiting for you" those that ask or replied, then the others), the one shown unfolded into its
  // card (lib/sessioncard.svelte.ts). The same menu on every page: Settings lists its sections in
  // its page (SettingsView), the menu never replaced. Remote has no row: a shared session shows a
  // phone, and a broken gateway is said only while a session is shared.
  import AppWindow from "@lucide/svelte/icons/app-window";
  import MessageCircle from "@lucide/svelte/icons/message-circle";
  import MessagesSquare from "@lucide/svelte/icons/messages-square";
  import FolderOpen from "@lucide/svelte/icons/folder-open";
  import Puzzle from "@lucide/svelte/icons/puzzle";
  import Compass from "@lucide/svelte/icons/compass";
  import InboxIcon from "@lucide/svelte/icons/inbox";
  import Sparkles from "@lucide/svelte/icons/sparkles";
  import BookOpen from "@lucide/svelte/icons/book-open";
  import Folder from "@lucide/svelte/icons/folder";
  import { areas } from "../lib/areas.svelte";
  import Logo from "./Logo.svelte";
  import Plus from "@lucide/svelte/icons/plus";
  import Workflow from "@lucide/svelte/icons/workflow";
  import Settings from "@lucide/svelte/icons/settings";
  import LayoutGrid from "@lucide/svelte/icons/layout-grid";
  import Smartphone from "@lucide/svelte/icons/smartphone";
  import X from "@lucide/svelte/icons/x";
  import * as Sidebar from "$lib/components/ui/sidebar";
  import { accessLabel } from "../lib/access";
  import { appOf, isChat } from "../lib/agents";
  import { api } from "../lib/api";
  import { agentLabel, byName, projects } from "../lib/projects.svelte";
  import { remote } from "../lib/remote.svelte";
  import { router, href } from "../lib/router.svelte";
  import { STATUS_LABEL, sessions, type LiveSession } from "../lib/sessions.svelte";
  import { sessionCard } from "../lib/sessioncard.svelte";
  import SessionStatus from "./SessionStatus.svelte";
  import { inbox } from "../lib/inbox.svelte";
  import { byArea, placeDot } from "../lib/menu";

  const WAITING: string[] = ["needs-you", "replied"];
  // the open sessions under two headings when some wait for you: those first, then the others
  const waiting = $derived(sessions.list.filter((s) => WAITING.includes(s.status)));
  const others = $derived(sessions.list.filter((s) => !WAITING.includes(s.status)));

  const route = $derived(router.route);
  const dotOf = (projectId: string | null) => placeDot(sessions.list.filter((s) => (s.agent.projectId ?? null) === projectId).map((s) => s.status));
  // the pinned projects by area, by name in each: the menu changes only when one is pinned or unpinned
  const groups = $derived(byArea(byName(projects.list.filter((p) => p.pinned)), areas.list.map((a) => a.name)));
  // an area's heading only where there are areas: "No area" alone says nothing
  const headed = $derived(groups.some((g) => g.area !== null));
  // the apps by name, read again on each page change (installed or removed elsewhere)
  let appNames = $state<string[] | null>(null);
  $effect(() => {
    void route;
    api.apps().then(
      (list) => (appNames = list.map((a) => a.name).sort()),
      () => (appNames = null),
    );
  });
  // an agent's page is under its project, when it has one
  const agentProject = $derived(route.view === "agent" ? projects.list.find((p) => p.agents.some((a) => a.id === route.id))?.id : undefined);
  // an app's part (H.14) is under its app: its agent's page, its settings, setting one up; the
  // settings of someone you talk to, under Chat
  let routeApp = $state<string | null>(null);
  let routeChat = $state(false);
  $effect(() => {
    const r = route;
    routeChat = r.view === "chat";
    if (r.view === "edit-ad-hoc" && r.app) routeApp = r.app;
    else if ((r.view === "agent" || r.view === "edit-ad-hoc") && r.id)
      api.agent(r.id).then(
        (a) => ((routeApp = appOf(a)), (routeChat = isChat(a))),
        () => (routeApp = null),
      );
    else routeApp = null;
  });
  const adHoc = $derived(["agents", "agent", "edit-ad-hoc", "run"].includes(route.view) && !agentProject && !routeApp && !routeChat);
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

  /** What the session says under its name: what it waits for (the question when this tab is
   *  attached), why it failed or stopped, that a stopped one resumes when opened; working and
   *  idle are said by its icon alone. */
  function hint(s: LiveSession): string | null {
    if (s.status === "needs-you") {
      const asked = s.conn?.permissions[0]?.request.toolCall.title;
      return asked ? `asks: ${asked}` : "waiting for you";
    }
    if (s.status === "failed") return s.info.error ? `failed: ${s.info.error}` : "failed";
    if (s.status === "stopped" && s.info.missingImage) return "can't start yet · open it to prepare what it needs";
    if (s.status === "stopped") return s.info.error ? `stopped: ${s.info.error}` : "stopped · open it to resume";
    if (s.status === "replied" || s.status === "elsewhere") return STATUS_LABEL[s.status];
    return null;
  }
  function hintTone(s: LiveSession): string {
    if (s.status === "needs-you") return "font-semibold text-warn";
    if (s.status === "stopped" && s.info.missingImage) return "text-warn";
    if (s.status === "failed" || (s.status === "stopped" && s.info.error)) return "text-danger";
    return s.status === "stopped" ? "text-muted-foreground" : "text-link";
  }

  /** What a broken gateway means for you, while a session is shared with your phone: nothing
   *  otherwise (Settings → Remote and the session's phone button show the light). */
  const remoteBroken = $derived.by(() => {
    const st = remote.status;
    if (!st?.sharedSessions?.length) return null;
    if (st.light === "unreachable") return "Your phone can't reach Handler: the gateway is unreachable.";
    if (st.light === "unauthorized") return "Your phone can't reach Handler: the gateway refused this computer's token.";
    return null;
  });

  /** The agent's name inside its project; the full label for one of no project. */
  function name(s: LiveSession): string {
    const found = projects.of(s.agent);
    return found ? agentLabel(found.agent) : projects.label(s.agent);
  }
  void areas.load();
  inbox.start();
</script>

{#snippet sessionItem(s: LiveSession)}
  {@const active = route.view === "session" && route.key === s.key}
  {@const note = hint(s)}
  {@const found = projects.of(s.agent)}
  {@const unfolded = active && sessionCard.key === s.key && sessionCard.card !== null}
  <Sidebar.MenuItem class="enter-side {unfolded ? 'unfolded' : ''}">
    <Sidebar.MenuButton isActive={active} class="h-auto items-start py-1.5">
      {#snippet child({ props })}
        <a href={href({ view: "session", key: s.key })} title={`${accessLabel(s.info)} in ${s.info.scope}`} data-testid="session-item" {...props}>
          <span class="mt-0.5 grid size-4 shrink-0 place-items-center"><SessionStatus status={s.status} /></span>
          <!-- wrapping: the menu button truncates its last child, the hint takes two lines -->
          <span class="flex min-w-0 flex-col whitespace-normal!">
            <span class="flex min-w-0 items-center gap-1.5">
              <span class="truncate">
                <!-- not running: the name dimmed, the running ones stand out -->
                <span class="font-medium {s.status === 'stopped' || s.status === 'failed' ? 'text-muted-foreground' : 'text-sidebar-accent-foreground'}">{name(s)}</span>
                {#if s.title}<span class="text-muted-foreground"> · {s.title}</span>{/if}
              </span>
              {#if remote.shared(s.key)}
                <span class="shrink-0 text-muted-foreground" title="shared with your phone" data-testid="session-shared"><Smartphone class="size-3!" /></span>
              {/if}
            </span>
            <!-- its project in plain text: its area is named once, above the project in the menu -->
            {#if found}<span class="truncate text-xs text-muted-foreground">{found.project.name}</span>{/if}
            {#if note}
              <span class="line-clamp-2 text-xs [overflow-wrap:anywhere] {hintTone(s)}">{note}</span>
            {/if}
          </span>
        </a>
      {/snippet}
    </Sidebar.MenuButton>
    {#if !active}
      <Sidebar.MenuAction showOnHover aria-label="close session" title="close session" onclick={() => close(s)}>
        <X />
      </Sidebar.MenuAction>
    {/if}
    {#if unfolded && sessionCard.card}
      <div class="card" data-testid="session-card">{@render sessionCard.card()}</div>
    {/if}
  </Sidebar.MenuItem>
{/snippet}

<!-- A place's sessions in one mark (lib/menu.ts): the most urgent one's dot, or how many need
     you when more than one does; nothing when none runs. -->
{#snippet placeMark(projectId: string | null)}
  {@const dot = dotOf(projectId)}
  {#if dot.status}
    <span class="ml-auto flex shrink-0 items-center overflow-visible! pr-0.5" title={dot.title} data-testid="place-dot" data-status={dot.status}>
      {#if dot.needYou > 1}
        <span class="rounded-full border border-warn/50 bg-warn/10 px-1.5 font-mono text-[11px] leading-4 font-semibold text-warn">{dot.needYou}</span>
      {:else}
        <SessionStatus status={dot.status} title={dot.title} />
      {/if}
    </span>
  {/if}
{/snippet}

<!-- The open sessions at the menu's foot, one list: under "waiting for you" (in amber) those that
     ask or replied, then the others under "open"; one heading, "open sessions", when none waits. -->
{#snippet openSessions()}
  {#if sessions.list.length}
    <Sidebar.Group class="open min-h-0 border-t border-sidebar-border">
      {#if waiting.length}
        <Sidebar.GroupLabel class="justify-between font-semibold text-warn" data-testid="sessions-waiting">waiting for you<span class="tabular-nums">{waiting.length}</span></Sidebar.GroupLabel>
      {:else}
        <Sidebar.GroupLabel class="justify-between">open sessions<span class="tabular-nums">{others.length}</span></Sidebar.GroupLabel>
      {/if}
      <Sidebar.Menu aria-label="open sessions" class="min-h-0 overflow-y-auto" data-testid="open-sessions">
        {#each waiting as s (s.key)}
          {@render sessionItem(s)}
        {/each}
        {#if waiting.length && others.length}
          <li class="flex h-8 shrink-0 items-center justify-between px-2 font-mono text-xs text-sidebar-foreground/75" data-testid="sessions-open">
            open<span class="tabular-nums">{others.length}</span>
          </li>
        {/if}
        {#each others as s (s.key)}
          {@render sessionItem(s)}
        {/each}
      </Sidebar.Menu>
    </Sidebar.Group>
  {/if}
{/snippet}

<Sidebar.Root>
  <Sidebar.Header>
    <a class="flex items-center gap-2 px-2 py-1.5 text-sm font-semibold text-sidebar-accent-foreground no-underline" href={href({ view: "home" })}>
      <Logo class="size-6" />
      Handler
    </a>
    <Sidebar.Menu>
      <Sidebar.MenuItem>
        <Sidebar.MenuButton isActive={route.view === "ask"}>
          {#snippet child({ props })}
            <a href={href({ view: "ask" })} {...props} data-testid="ask-link"><MessageCircle /><span>Ask</span></a>
          {/snippet}
        </Sidebar.MenuButton>
      </Sidebar.MenuItem>
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
        {#if inbox.unread}
          <Sidebar.MenuBadge class="rounded-full bg-primary font-semibold text-primary-foreground!" title="unread" data-testid="inbox-unread">{inbox.unread}</Sidebar.MenuBadge>
        {/if}
      </Sidebar.MenuItem>
      <Sidebar.MenuItem>
        <Sidebar.MenuButton isActive={route.view === "automations" || route.view === "automation" || route.view === "edit-automation"}>
          {#snippet child({ props })}
            <a href={href({ view: "automations" })} {...props} data-testid="automations-link"><Workflow /><span>Schedule</span></a>
          {/snippet}
        </Sidebar.MenuButton>
      </Sidebar.MenuItem>
    </Sidebar.Menu>
  </Sidebar.Header>

  <Sidebar.Content>
    {#if sessions.loadError}<p class="px-4 text-xs text-danger" data-testid="sessions-error">{sessions.loadError}</p>{/if}

    <Sidebar.Group>
      {#each groups as g (g.area)}
        {#if headed}
          <Sidebar.GroupLabel class="gap-1.5 font-sans font-semibold normal-case {g.area ? `area-icon ${areas.colorClass(g.area)}` : 'font-medium'}" data-testid="sidebar-area">
            {#if g.area}<span class="size-2 rounded-[2px] bg-current"></span>{/if}{g.area ?? "No area"}
          </Sidebar.GroupLabel>
        {/if}
        <Sidebar.Menu aria-label={g.area ?? "projects"}>
          {#each g.items as p (p.id)}
            <Sidebar.MenuItem>
              <Sidebar.MenuButton isActive={current === p.id}>
                {#snippet child({ props })}
                  <a href={href({ view: "project", id: p.id })} title={p.folder} data-testid="sidebar-project" {...props}>
                    <Folder class={p.area ? `area-icon ${areas.colorClass(p.area)}` : ""} /><span class="truncate">{p.name}</span>
                    {@render placeMark(p.id)}
                  </a>
                {/snippet}
              </Sidebar.MenuButton>
            </Sidebar.MenuItem>
          {/each}
        </Sidebar.Menu>
      {/each}
      <!-- a place of its own, not one of the last area's projects -->
      <Sidebar.Menu class={headed ? "mt-3" : ""}>
        <Sidebar.MenuItem>
          <Sidebar.MenuButton isActive={adHoc}>
            {#snippet child({ props })}
              <a href={href({ view: "agents" })} {...props} data-testid="sidebar-agents"><FolderOpen /><span>Other folders</span>{@render placeMark(null)}</a>
            {/snippet}
          </Sidebar.MenuButton>
        </Sidebar.MenuItem>
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
      <Sidebar.GroupLabel>
        {#snippet child({ props })}<a {...props} href={href({ view: "apps" })} class="{props.class} no-underline hover:text-foreground" data-testid="apps-link">Apps</a>{/snippet}
      </Sidebar.GroupLabel>
      <Sidebar.Menu aria-label="apps">
        <Sidebar.MenuItem>
          <Sidebar.MenuButton isActive={routeChat}>
            {#snippet child({ props })}
              <a href={href({ view: "chat" })} {...props} data-testid="sidebar-chat"><MessagesSquare class="text-primary" /><span>Chat</span></a>
            {/snippet}
          </Sidebar.MenuButton>
        </Sidebar.MenuItem>
        {#if appNames}
          {#each appNames as name (name)}
            <Sidebar.MenuItem>
              <Sidebar.MenuButton isActive={(route.view === "apps" && route.app === name) || routeApp === name}>
                {#snippet child({ props })}
                  <a href={href({ view: "apps", app: name })} {...props} data-testid="sidebar-app"><AppWindow class="text-primary" /><span class="truncate">{name}</span></a>
                {/snippet}
              </Sidebar.MenuButton>
            </Sidebar.MenuItem>
          {:else}
            <Sidebar.MenuItem>
              <Sidebar.MenuButton isActive={route.view === "apps"}>
                {#snippet child({ props })}
                  <a href={href({ view: "apps" })} class="text-muted-foreground" {...props} data-testid="sidebar-get-app"><Plus /><span>Get an app</span></a>
                {/snippet}
              </Sidebar.MenuButton>
            </Sidebar.MenuItem>
          {/each}
        {/if}
      </Sidebar.Menu>
    </Sidebar.Group>

    <Sidebar.Group>
      <Sidebar.GroupLabel>Library</Sidebar.GroupLabel>
      <Sidebar.Menu aria-label="library">
        <Sidebar.MenuItem>
          <Sidebar.MenuButton isActive={route.view === "discover" || route.view === "discover-item"}>
            {#snippet child({ props })}
              <a href={href({ view: "discover" })} {...props} data-testid="discover-link"><Compass /><span>Discover</span></a>
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
        <Sidebar.MenuItem>
          <Sidebar.MenuButton isActive={route.view === "addons"}>
            {#snippet child({ props })}
              <a href={href({ view: "addons" })} {...props} data-testid="addons-link"><Puzzle /><span>Addons</span></a>
            {/snippet}
          </Sidebar.MenuButton>
        </Sidebar.MenuItem>
      </Sidebar.Menu>
    </Sidebar.Group>
  </Sidebar.Content>

  {@render openSessions()}
  <Sidebar.Footer>
    <!-- Remote is said in the menu only while it is used: a session shared, and the gateway broken -->
    {#if remoteBroken}
      <a
        href={href({ view: "settings", section: "remote" })}
        class="mx-2 flex items-start gap-2 rounded-md bg-danger/8 px-2.5 py-2 text-xs text-danger no-underline hover:bg-danger/12"
        title={remote.status?.detail ?? undefined}
        data-testid="remote-problem"
        ><Smartphone class="mt-px size-3.5 shrink-0" /><span>{remoteBroken} <span class="underline">Remote settings</span></span></a>
    {/if}
    <Sidebar.Menu>
      <Sidebar.MenuItem>
        <Sidebar.MenuButton isActive={route.view === "settings"}>
          {#snippet child({ props })}
            <a href={href({ view: "settings", section: "models" })} {...props} data-testid="settings-link"><Settings /><span>Settings</span></a>
          {/snippet}
        </Sidebar.MenuButton>
      </Sidebar.MenuItem>
    </Sidebar.Menu>
  </Sidebar.Footer>
</Sidebar.Root>

<style>
  /* the open sessions: at the menu's foot, scrolling on their own past half its height */
  :global([data-sidebar="group"].open) {
    flex: none;
    max-height: 50%;
  }
  /* the session shown, unfolded: its row and its card (made by the session page) are one card */
  :global([data-sidebar="menu-item"].unfolded) {
    margin: 0.15rem 0 0.35rem;
    border-radius: 10px;
    background: var(--background);
    box-shadow: var(--panel-shadow);
  }
  :global(.unfolded > a[data-active]) {
    background: transparent;
    box-shadow: none;
  }
  .card {
    padding: 0.1rem 0.6rem 0.35rem 2.05rem;
    animation: card-in var(--dur-3) var(--ease) backwards;
  }
  @keyframes card-in {
    from {
      opacity: 0;
      transform: translateY(-4px);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .card {
      animation: none;
    }
  }
</style>
