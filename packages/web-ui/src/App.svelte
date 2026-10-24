<script lang="ts">
  // Shell: the menu (the pages, projects, and the open sessions at its foot) on the left, the
  // current page on the right, flush against it.
  import { untrack } from "svelte";
  import * as SidebarUI from "$lib/components/ui/sidebar";
  import NotConnected from "./components/NotConnected.svelte";
  import RuntimeBanner from "./components/RuntimeBanner.svelte";
  import Sidebar from "./components/Sidebar.svelte";
  import { token } from "./lib/auth";
  import { projects } from "./lib/projects.svelte";
  import { router } from "./lib/router.svelte";
  import { harnesses } from "./lib/harnesses.svelte";
  import { runtime } from "./lib/runtime.svelte";
  import { sessions } from "./lib/sessions.svelte";
  import AppInstallView from "./views/AppInstallView.svelte";
  import AgentSetupView from "./views/AgentSetupView.svelte";
  import AdHocAgentEditView from "./views/AdHocAgentEditView.svelte";
  import AgentView from "./views/AgentView.svelte";
  import AgentEditView from "./views/AgentEditView.svelte";
  import AppsView from "./views/AppsView.svelte";
  import AppView from "./views/AppView.svelte";
  import AskView from "./views/AskView.svelte";
  import ChatView from "./views/ChatView.svelte";
  import AutomationsView from "./views/AutomationsView.svelte";
  import InboxView from "./views/InboxView.svelte";
  import AutomationView from "./views/AutomationView.svelte";
  import AutomationEditView from "./views/AutomationEditView.svelte";
  import KnowledgeView from "./views/KnowledgeView.svelte";
  import OutsideView from "./views/OutsideView.svelte";
  import ProjectEditView from "./views/ProjectEditView.svelte";
  import ProjectsView from "./views/ProjectsView.svelte";
  import ProjectView from "./views/ProjectView.svelte";
  import RunView from "./views/RunView.svelte";
  import SessionView from "./views/SessionView.svelte";
  import TerminalView from "./views/TerminalView.svelte";
  import SettingsView from "./views/SettingsView.svelte";
  import SkillsView from "./views/SkillsView.svelte";
  import AddonsView from "./views/AddonsView.svelte";
  import DiscoverItemView from "./views/DiscoverItemView.svelte";
  import DiscoverView from "./views/DiscoverView.svelte";
  import SkillView from "./views/SkillView.svelte";

  const authenticated = token() !== null;

  // the projects, for the sidebar, the labels of sessions and the pickers: read again on each page
  // change (one made in another tab, by the CLI or the API shows); pages refresh it when they
  // change one
  $effect(() => {
    void router.route;
    if (authenticated) untrack(() => void projects.refresh());
  });

  // can agents run here at all: shown on every page when not
  $effect(() => {
    if (authenticated) {
      void runtime.refresh();
      void harnesses.load();
    }
  });

  // A page change: the new page comes in under the steady top bar (motion only: the page itself is
  // not remade for it).
  let panel = $state<HTMLElement | null>(null);
  $effect(() => {
    void router.route;
    const el = untrack(() => panel);
    if (!el || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    for (const child of el.children) {
      if (child.tagName === "HEADER") continue;
      child.animate([{ opacity: 0, transform: "translateY(6px)" }, { opacity: 1, transform: "none" }], {
        duration: 260,
        easing: "cubic-bezier(0.32, 0.72, 0, 1)",
      });
    }
  });

  // Sessions waiting for the user, in the tab title: visible from other tabs.
  $effect(() => {
    const n = sessions.attention;
    document.title = n ? `(${n}) Handler` : "Handler";
  });
</script>

{#if !authenticated}
  <NotConnected />
{:else}
  <SidebarUI.Provider style="--sidebar-width: 17rem">
    <Sidebar />
    <!-- the page, against the menu's edge: one edge, the menu never moves -->
    <SidebarUI.Inset bind:ref={panel} class="h-svh min-w-0 overflow-hidden">
      <RuntimeBanner />
      {#if router.route.view === "session"}
        {#key router.route.key}<SessionView key={router.route.key} />{/key}
      {:else if router.route.view === "terminal"}
        {#key `${router.route.agent}/${router.route.connection}`}
          <TerminalView agent={router.route.agent} connection={router.route.connection} />
        {/key}
      {:else if router.route.view === "agents"}
        <OutsideView agent={router.route.agent} />
      {:else if router.route.view === "agent"}
        {#key router.route.id}<AgentView id={router.route.id} />{/key}
      {:else if router.route.view === "edit-ad-hoc"}
        {#key `${router.route.id ?? `new/${router.route.app ?? ""}/${router.route.need ?? ""}`}`}
          <AdHocAgentEditView id={router.route.id} app={router.route.app} need={router.route.need} />
        {/key}
      {:else if router.route.view === "install-app"}
        {#key router.route.name}<AppInstallView name={router.route.name} />{/key}
      {:else if router.route.view === "setup"}
        {#key `${router.route.file}/${router.route.project ?? ""}`}
          <AgentSetupView file={router.route.file} project={router.route.project} />
        {/key}
      {:else if router.route.view === "set-up-helper"}
        {#key router.route.need}<AgentSetupView need={router.route.need} />{/key}
      {:else if router.route.view === "run"}
        {#key router.route.id}<RunView id={router.route.id} />{/key}
      {:else if router.route.view === "settings"}
        <SettingsView section={router.route.section} />
      {:else if router.route.view === "skills"}
        <SkillsView />
      {:else if router.route.view === "addons"}
        <AddonsView install={router.route.install} />
      {:else if router.route.view === "discover"}
        <DiscoverView />
      {:else if router.route.view === "discover-item"}
        {#key `${router.route.source}/${router.route.kind}/${router.route.name}`}
          <DiscoverItemView source={router.route.source} kind={router.route.kind} name={router.route.name} />
        {/key}
      {:else if router.route.view === "skill"}
        {#key router.route.name ?? "new"}<SkillView name={router.route.name} imported={router.route.imported} />{/key}
      {:else if router.route.view === "ask"}
        <AskView />
      {:else if router.route.view === "chat"}
        <ChatView agent={router.route.agent} say={router.route.say} new={router.route.new} />
      {:else if router.route.view === "apps"}
        {#if router.route.app}
          {#key router.route.app}<AppView name={router.route.app} />{/key}
        {:else}
          <AppsView />
        {/if}
      {:else if router.route.view === "automations"}
        <AutomationsView />
      {:else if router.route.view === "inbox"}
        <InboxView />
      {:else if router.route.view === "edit-automation"}
        {#key `${router.route.name ?? ""}/${router.route.agent ?? ""}`}<AutomationEditView name={router.route.name} agent={router.route.agent} />{/key}
      {:else if router.route.view === "automation"}
        {#key router.route.name}<AutomationView name={router.route.name} />{/key}
      {:else if router.route.view === "project"}
        {#key router.route.id}<ProjectView id={router.route.id} agent={router.route.agent} />{/key}
      {:else if router.route.view === "edit-project"}
        {#key router.route.id ?? router.route.knowledge ?? router.route.folder ?? "new"}
          <ProjectEditView id={router.route.id} knowledge={router.route.knowledge} folder={router.route.folder} />
        {/key}
      {:else if router.route.view === "edit-agent"}
        {#key `${router.route.project}/${router.route.id ?? `new/${router.route.from ?? ""}`}`}
          <AgentEditView project={router.route.project} id={router.route.id} from={router.route.from} />
        {/key}
      {:else if router.route.view === "knowledge"}
        <KnowledgeView path={router.route.path} note={router.route.note} />
      {:else}
        <ProjectsView />
      {/if}
    </SidebarUI.Inset>
  </SidebarUI.Provider>
{/if}
