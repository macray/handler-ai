<script lang="ts">
  // The menu, the same on every page: Handler and its bell ("need you" for every project and app,
  // Bell.svelte), then the places: Projects, Chat, Apps, Library; then Pinned, the projects and
  // apps the person put there, mixed, in their order (D.28; reordered by dragging, unpinned with
  // ×), each with one dot for its sessions (lib/menu.ts); Settings at its foot. It grows with the
  // install (menuShows): Chat and Apps once a model is ready, Library once a project exists. The
  // other pages (Inbox, Automations, Plans, Discover…) open from the bell, the Library or their
  // project, and each still by its address. Remote has no row: a shared session shows a phone,
  // and a broken gateway is said only while a session is shared.
  import { untrack } from "svelte";
  import AppWindow from "@lucide/svelte/icons/app-window";
  import Folder from "@lucide/svelte/icons/folder";
  import LayoutGrid from "@lucide/svelte/icons/layout-grid";
  import Library from "@lucide/svelte/icons/library-big";
  import MessagesSquare from "@lucide/svelte/icons/messages-square";
  import Settings from "@lucide/svelte/icons/settings";
  import Smartphone from "@lucide/svelte/icons/smartphone";
  import X from "@lucide/svelte/icons/x";
  import * as Sidebar from "$lib/components/ui/sidebar";
  import { appOf, isChat } from "../lib/agents";
  import { api } from "../lib/api";
  import { areas } from "../lib/areas.svelte";
  import type { Pin } from "../lib/contracts.gen";
  import { inbox } from "../lib/inbox.svelte";
  import { menuShows, placeDot } from "../lib/menu";
  import { menuUse } from "../lib/menuuse.svelte";
  import { pins } from "../lib/pins.svelte";
  import { projects } from "../lib/projects.svelte";
  import { remote } from "../lib/remote.svelte";
  import { href, router } from "../lib/router.svelte";
  import { sessions } from "../lib/sessions.svelte";
  import Bell from "./Bell.svelte";
  import Logo from "./Logo.svelte";
  import SessionStatus from "./SessionStatus.svelte";

  const route = $derived(router.route);

  // in a narrow window the menu is a sheet over the page: a place chosen closes it
  const sidebar = Sidebar.useSidebar();
  $effect(() => {
    void route;
    untrack(() => sidebar.setOpenMobile(false));
  });
  // a model ready, Pinned: read again on each page change (changed in another tab, by the API)
  $effect(() => {
    void route;
    menuUse.load();
    void pins.load();
  });
  const shows = $derived(menuShows({ projects: projects.list.length, modelReady: menuUse.modelReady }));

  // an agent's page is under its project, when it has one
  const agentProject = $derived(route.view === "agent" ? projects.list.find((p) => p.agents.some((a) => a.id === route.id))?.id : undefined);
  // an app's part (H.14) is under its app: its agent's page, its settings, setting one up; the
  // settings of someone you talk to, under Chat
  let routeApp = $state<string | null>(null);
  let routeChat = $state(false);
  $effect(() => {
    const r = route;
    routeChat = r.view === "chat" || r.view === "ask";
    if (r.view === "edit-ad-hoc" && r.app) routeApp = r.app;
    else if ((r.view === "agent" || r.view === "edit-ad-hoc") && r.id)
      api.agent(r.id).then(
        (a) => ((routeApp = appOf(a)), (routeChat = isChat(a))),
        () => (routeApp = null),
      );
    else routeApp = null;
  });
  const current = $derived(
    route.view === "project" ? route.id : route.view === "edit-agent" ? route.project : agentProject,
  );
  const inApp = (name: string) => (route.view === "apps" && route.app === name) || (route.view === "install-app" && route.name === name) || routeApp === name;
  const LIBRARY = ["library", "addons", "skills", "skill", "knowledge", "automations", "automation", "edit-automation", "tool", "discover-item"];
  const inLibrary = $derived(LIBRARY.includes(route.view));
  const inProjects = $derived(["projects", "agents", "plans", "plan", "review-plan"].includes(route.view) || (route.view === "agent" && !agentProject && !routeApp && !routeChat));

  // Pinned, as the person ordered it; a pin whose project is not listed (yet) is left out
  type Pinned = { pin: Pin; index: number; label: string; title: string; area?: string | null; active: boolean; dot: ReturnType<typeof placeDot> };
  const pinned = $derived(
    pins.items.flatMap((pin, index): Pinned[] => {
      if (pin.kind === "project") {
        const p = projects.get(pin.id);
        if (!p) return [];
        const dot = placeDot(sessions.list.filter((s) => s.agent.projectId === p.id).map((s) => s.status));
        return [{ pin, index, label: p.name, title: p.folder, area: p.area, active: current === p.id, dot }];
      }
      const dot = placeDot(sessions.list.filter((s) => s.agent.app === pin.id).map((s) => s.status));
      return [{ pin, index, label: pin.id, title: pin.id, active: inApp(pin.id), dot }];
    }),
  );

  // dragging a pinned item: where it comes from, the item it would take the place of
  let dragged = $state<number | null>(null);
  let over = $state<number | null>(null);
  function drop(to: number): void {
    if (dragged !== null && dragged !== to) void pins.move(dragged, to).catch(() => {});
    dragged = over = null;
  }

  /** What a broken gateway means for you, while a session is shared with your phone: nothing
   *  otherwise (Settings → Your phone and the session's phone button show the light). */
  const remoteBroken = $derived.by(() => {
    const st = remote.status;
    if (!st?.sharedSessions?.length) return null;
    if (st.light === "unreachable") return "Your phone can't reach Handler: the gateway is unreachable.";
    if (st.light === "unauthorized") return "Your phone can't reach Handler: the gateway refused this computer's token.";
    return null;
  });
  void areas.load();
  inbox.start();
</script>

<!-- A place's sessions in one mark (lib/menu.ts): the most urgent one's dot, or how many need
     you when more than one does; nothing when none runs. -->
{#snippet placeMark(dot: ReturnType<typeof placeDot>)}
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

{#snippet place(view: string, label: string, active: boolean, testid: string, Icon: typeof Folder)}
  <Sidebar.MenuItem>
    <Sidebar.MenuButton isActive={active}>
      {#snippet child({ props })}
        <a href={`#/${view}`} {...props} data-testid={testid}><Icon /><span>{label}</span></a>
      {/snippet}
    </Sidebar.MenuButton>
  </Sidebar.MenuItem>
{/snippet}

<Sidebar.Root>
  <!-- the menu is the page's main navigation, a landmark to jump to or skip -->
  <nav aria-label="Main" class="flex min-h-0 flex-1 flex-col">
  <Sidebar.Header>
    <div class="flex items-center gap-2 pr-1">
      <a class="flex items-center gap-2 px-2 py-1.5 text-sm font-semibold text-sidebar-accent-foreground no-underline" href={href({ view: "projects" })} data-testid="logo">
        <Logo class="size-6" />
        Handler
      </a>
      <Bell />
    </div>
    <Sidebar.Menu>
      {@render place("projects", "Projects", inProjects, "projects-link", LayoutGrid)}
      {#if shows.chat}{@render place("chat", "Chat", routeChat, "sidebar-chat", MessagesSquare)}{/if}
      {#if shows.apps}{@render place("apps", "Apps", route.view === "apps" && !route.app, "apps-link", AppWindow)}{/if}
      {#if shows.library}{@render place("library", "Library", inLibrary, "library-link", Library)}{/if}
    </Sidebar.Menu>
  </Sidebar.Header>

  <Sidebar.Content>
    {#if sessions.loadError}<p class="px-4 text-xs text-danger" data-testid="sessions-error">{sessions.loadError}</p>{/if}
    {#if pinned.length}
      <Sidebar.Group>
        <Sidebar.GroupLabel class="font-sans font-semibold normal-case" data-testid="pinned-label">Pinned</Sidebar.GroupLabel>
        <Sidebar.Menu aria-label="pinned">
          {#each pinned as item (`${item.pin.kind}/${item.pin.id}`)}
            <Sidebar.MenuItem
              draggable="true"
              class={dragged === null || over !== item.index || dragged === item.index ? "" : dragged < item.index ? "drop-below" : "drop-above"}
              ondragstart={(e: DragEvent) => {
                dragged = item.index;
                e.dataTransfer?.setData("text/plain", String(item.index));
              }}
              ondragover={(e: DragEvent) => {
                e.preventDefault();
                over = item.index;
              }}
              ondragend={() => (dragged = over = null)}
              ondrop={(e: DragEvent) => {
                e.preventDefault();
                drop(item.index);
              }}
              data-testid="pinned-item"
              data-kind={item.pin.kind}
            >
              <Sidebar.MenuButton isActive={item.active}>
                {#snippet child({ props })}
                  <a href={item.pin.kind === "project" ? href({ view: "project", id: item.pin.id }) : href({ view: "apps", app: item.pin.id })} title={item.title} {...props} data-testid={item.pin.kind === "project" ? "sidebar-project" : "sidebar-app"}>
                    <!-- a project's area: the colour of its folder, no group -->
                    {#if item.pin.kind === "project"}<Folder class={item.area ? `area-icon ${areas.colorClass(item.area)}` : ""} />{:else}<AppWindow />{/if}<span
                      class="truncate">{item.label}</span
                    >{@render placeMark(item.dot)}</a
                  >
                {/snippet}
              </Sidebar.MenuButton>
              <Sidebar.MenuAction showOnHover aria-label="unpin {item.label}" title="Unpin" onclick={() => void pins.unpin(item.pin.kind, item.pin.id).catch(() => {})} data-testid="unpin">
                <X />
              </Sidebar.MenuAction>
            </Sidebar.MenuItem>
          {/each}
        </Sidebar.Menu>
      </Sidebar.Group>
    {/if}
  </Sidebar.Content>

  <Sidebar.Footer>
    <!-- Remote is said in the menu only while it is used: a session shared, and the gateway broken -->
    {#if remoteBroken}
      <a
        href={href({ view: "settings", section: "phone" })}
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
  </nav>
</Sidebar.Root>

<style>
  /* where a dragged pin lands: it takes the place of the one it is dropped on */
  :global([data-sidebar="menu-item"].drop-above) {
    box-shadow: 0 -2px 0 var(--primary);
  }
  :global([data-sidebar="menu-item"].drop-below) {
    box-shadow: 0 2px 0 var(--primary);
  }
</style>
