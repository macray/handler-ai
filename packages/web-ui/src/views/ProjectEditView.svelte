<script lang="ts">
  // A new project: the project alone (ProjectEditor), then its page, where its first agent is
  // added. An existing one's settings are its page's Settings tab (ProjectView).
  import PageHeader from "../components/PageHeader.svelte";
  import ProjectEditor from "../components/ProjectEditor.svelte";
  import type { Project } from "../lib/contracts.gen";
  import { projects } from "../lib/projects.svelte";
  import { href, navigate } from "../lib/router.svelte";

  let { folder }: { folder?: string } = $props();

  function back(): void {
    if (history.length > 1) history.back();
    else navigate({ view: "projects" });
  }

  function saved(p: Project): void {
    void projects.refresh();
    navigate({ view: "project", id: p.id }, true);
  }
</script>

<PageHeader width="max-w-3xl" title="New project" parent={{ label: "Projects", href: href({ view: "projects" }) }} />
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-3xl space-y-8 px-8 pt-4 pb-10">
    <ProjectEditor initialFolder={folder} onsaved={saved} oncancel={back} />
  </div>
</div>
