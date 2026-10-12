<script lang="ts">
  // Shell: the sidebar (what needs you, projects and their open sessions) on the left, the
  // current page on the right.
  import * as Card from "$lib/components/ui/card";
  import * as SidebarUI from "$lib/components/ui/sidebar";
  import RuntimeBanner from "./components/RuntimeBanner.svelte";
  import Sidebar from "./components/Sidebar.svelte";
  import { token } from "./lib/auth";
  import { projects } from "./lib/projects.svelte";
  import { router } from "./lib/router.svelte";
  import { harnesses } from "./lib/harnesses.svelte";
  import { runtime } from "./lib/runtime.svelte";
  import { sessions } from "./lib/sessions.svelte";
  import AdHocAgentEditView from "./views/AdHocAgentEditView.svelte";
  import AgentView from "./views/AgentView.svelte";
  import AgentEditView from "./views/AgentEditView.svelte";
  import AgentsView from "./views/AgentsView.svelte";
  import AppsView from "./views/AppsView.svelte";
  import AutomationsView from "./views/AutomationsView.svelte";
  import InboxView from "./views/InboxView.svelte";
  import AutomationView from "./views/AutomationView.svelte";
  import AutomationEditView from "./views/AutomationEditView.svelte";
  import KnowledgeView from "./views/KnowledgeView.svelte";
  import ProjectEditView from "./views/ProjectEditView.svelte";
  import ProjectsView from "./views/ProjectsView.svelte";
  import ProjectView from "./views/ProjectView.svelte";
  import RunView from "./views/RunView.svelte";
  import SessionView from "./views/SessionView.svelte";
  import TerminalView from "./views/TerminalView.svelte";
  import SettingsView from "./views/SettingsView.svelte";
  import SkillsView from "./views/SkillsView.svelte";
  import SkillView from "./views/SkillView.svelte";

  const authenticated = token() !== null;

  // the projects, for the sidebar and the labels of sessions; pages refresh it when they change one
  $effect(() => {
    if (authenticated) void projects.refresh();
  });

  // can agents run here at all: shown on every page when not
  $effect(() => {
    if (authenticated) {
      void runtime.refresh();
      void harnesses.load();
    }
  });

  // Sessions waiting for the user, in the tab title: visible from other tabs.
  $effect(() => {
    const n = sessions.attention;
    document.title = n ? `(${n}) Handler` : "Handler";
  });
</script>

{#if !authenticated}
  <main class="grid min-h-svh place-items-center bg-background p-4">
    <Card.Root class="max-w-md">
      <Card.Header>
        <Card.Title>Not connected</Card.Title>
        <Card.Description>Open this page with <code>handler ui</code>: it passes the daemon's token to this tab.</Card.Description>
      </Card.Header>
    </Card.Root>
  </main>
{:else}
  <SidebarUI.Provider style="--sidebar-width: 15rem">
    <Sidebar />
    <SidebarUI.Inset class="h-svh min-w-0 overflow-hidden md:h-[calc(100svh-1rem)] md:shadow-panel">
      <RuntimeBanner />
      {#if router.route.view === "session"}
        {#key router.route.key}<SessionView key={router.route.key} />{/key}
      {:else if router.route.view === "terminal"}
        {#key `${router.route.agent}/${router.route.connection}`}
          <TerminalView agent={router.route.agent} connection={router.route.connection} />
        {/key}
      {:else if router.route.view === "agents"}
        <AgentsView />
      {:else if router.route.view === "agent"}
        {#key router.route.id}<AgentView id={router.route.id} />{/key}
      {:else if router.route.view === "edit-ad-hoc"}
        {#key `${router.route.id ?? `new/${router.route.builtin ?? ""}`}`}
          <AdHocAgentEditView id={router.route.id} builtin={router.route.builtin} />
        {/key}
      {:else if router.route.view === "run"}
        {#key router.route.id}<RunView id={router.route.id} />{/key}
      {:else if router.route.view === "settings"}
        <SettingsView section={router.route.section} />
      {:else if router.route.view === "skills"}
        <SkillsView />
      {:else if router.route.view === "skill"}
        {#key router.route.name ?? "new"}<SkillView name={router.route.name} imported={router.route.imported} />{/key}
      {:else if router.route.view === "apps"}
        <AppsView />
      {:else if router.route.view === "automations"}
        <AutomationsView />
      {:else if router.route.view === "inbox"}
        <InboxView />
      {:else if router.route.view === "edit-automation"}
        {#key `${router.route.name ?? ""}/${router.route.agent ?? ""}`}<AutomationEditView name={router.route.name} agent={router.route.agent} />{/key}
      {:else if router.route.view === "automation"}
        {#key router.route.name}<AutomationView name={router.route.name} />{/key}
      {:else if router.route.view === "project"}
        {#key router.route.id}<ProjectView id={router.route.id} />{/key}
      {:else if router.route.view === "edit-project"}
        {#key router.route.id ?? router.route.knowledge ?? "new"}
          <ProjectEditView id={router.route.id} knowledge={router.route.knowledge} />
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
