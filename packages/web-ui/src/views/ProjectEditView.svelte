<script lang="ts">
  // A new project (no `id`), or an existing one's settings, with Delete.
  import PageHeader from "../components/PageHeader.svelte";
  import PageTitle from "../components/PageTitle.svelte";
  import ProjectEditor from "../components/ProjectEditor.svelte";
  import { api } from "../lib/api";
  import type { Project } from "../lib/contracts.gen";
  import { accessOf, type ModelAccess } from "../lib/access";
  import { byRecentUse, projects } from "../lib/projects.svelte";
  import { href, navigate } from "../lib/router.svelte";

  let { id, knowledge, folder }: { id?: string; knowledge?: string; folder?: string } = $props();

  let project = $state<Project | null>(null);
  let lastAccess = $state<ModelAccess | undefined>(); // a new project's first agent: the last one used
  let error = $state<string | null>(null);
  let loaded = $state(false);

  $effect(() => {
    Promise.all([id ? api.project(id) : null, api.projects()]).then(
      ([current, all]) => {
        project = current;
        const latest = byRecentUse(all)[0];
        const used = latest?.agents.find((a) => a.id === latest.defaultAgent);
        lastAccess = used ? accessOf(used.model) : undefined;
        loaded = true;
      },
      (e: Error) => (error = e.message),
    );
  });

  function back(): void {
    if (history.length > 1) history.back();
    else navigate(id ? { view: "project", id } : { view: "home" });
  }

  function saved(p: Project): void {
    void projects.refresh();
    navigate({ view: "project", id: p.id }, true);
  }

  async function remove(): Promise<void> {
    if (!project) return;
    const running = project.agents.reduce((n, a) => n + a.connections.length, 0);
    const also = running ? ` Its ${running} running agent(s) are stopped.` : "";
    if (!confirm(`Delete the project ${project.name} and its agents? The folder is not touched.${also}`)) return;
    try {
      await api.deleteProject(project.id);
      void projects.refresh();
      navigate({ view: "home" }, true);
    } catch (e) {
      error = (e as Error).message;
    }
  }
</script>

<PageHeader
  titled
  title={project ? "Settings" : id ? "Project" : "New project"}
  parent={project ? { label: project.name, href: href({ view: "project", id: project.id }) } : { label: "Projects", href: href({ view: "home" }) }}
/>
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-3xl space-y-8 px-8 pt-10 pb-10">
    <PageTitle
      title={project ? "Settings" : "New project"}
      description={project
        ? `${project.name}'s folder and name, and what all its agents get. Each agent's own settings are on its page.`
        : "A code folder, and the agents you work on it with."}
    />
    {#if error}<p class="text-sm text-danger">{error}</p>{/if}
    {#if loaded && (project || !id)}
      {#key project?.id}
        <ProjectEditor project={project ?? undefined} initialAccess={lastAccess} initialKnowledge={knowledge} initialFolder={folder} onsaved={saved} oncancel={back} ondelete={remove} />
      {/key}
    {:else if !error}
      <p class="text-sm text-muted-foreground">Loading…</p>
    {/if}
  </div>
</div>
