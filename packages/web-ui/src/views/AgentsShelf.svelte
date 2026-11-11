<script lang="ts">
  // The Library's Agents shelf: get agents and see the ones you have; they work in their
  // projects. Yours: every agent of your projects and outside projects, grouped by where it
  // works, each saying where it came from (an agents file's name, D.23, or made here), with All /
  // From others / Made here and a search; a row opens the agent where it works. Get more: what
  // the sources offer (D.26, SourceShelf) and an agents file (an export, D.23); either goes on to
  // the set-up page, which asks where they go. `project` (a project's Get agents…): they go there,
  // said above the cards, until "Not for a project".
  import Bot from "@lucide/svelte/icons/bot";
  import FileUp from "@lucide/svelte/icons/file-up";
  import Folder from "@lucide/svelte/icons/folder";
  import X from "@lucide/svelte/icons/x";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import LoadingCards from "../components/LoadingCards.svelte";
  import SourceShelf from "../components/SourceShelf.svelte";
  import { api } from "../lib/api";
  import { areas } from "../lib/areas.svelte";
  import type { Agent, Project } from "../lib/contracts.gen";
  import { productName } from "../lib/harnesses.svelte";
  import { agentGroups, LIBRARY_WIDTH, yourAgents, type AgentFilter, type ShelfAgent } from "../lib/library";
  import { agentLabel } from "../lib/projects.svelte";
  import { href, navigate } from "../lib/router.svelte";

  let { more = false, project: into }: { more?: boolean; project?: string } = $props();

  let agents = $state<ShelfAgent[] | null>(null);
  let projectList = $state<Project[]>([]);
  let target = $state<Project | null>(null); // the project they go to
  let error = $state<string | null>(null);
  let filter = $state<AgentFilter>("all");
  let query = $state("");
  let reading = $state(false);
  let picker = $state<HTMLInputElement>(); // the agents file to read

  $effect(() => {
    void areas.load();
    Promise.all([api.agents(), api.projects()]).then(
      ([all, list]) => ((agents = yourAgents(all)), (projectList = list)),
      (e: Error) => (error = e.message),
    );
  });

  $effect(() => {
    target = null;
    if (into) api.project(into).then((p) => (target = p), () => undefined);
  });

  const words = $derived(query.trim().toLowerCase());
  const searched = $derived((agents ?? []).filter((a) => !words || agentLabel(a.agent).toLowerCase().includes(words)));
  const groups = $derived(agentGroups(searched, projectList, filter));
  const counts = $derived({ all: searched.length, others: searched.filter((a) => a.from).length, here: searched.filter((a) => !a.from).length });
  const FILTERS: { id: AgentFilter; label: string }[] = [
    { id: "all", label: "All" },
    { id: "others", label: "From others" },
    { id: "here", label: "Made here" },
  ];

  function who(agent: Agent): string {
    const m = agent.model;
    return [productName(m.harness ?? ""), m.model ?? m.account ?? m.provider].filter(Boolean).join(" · ");
  }

  /** An agents file chosen: read, then its set-up page (into the project, if one). */
  async function readFile(file: File | undefined): Promise<void> {
    if (!file) return;
    error = null;
    reading = true;
    try {
      const read = await api.importAgents(file);
      navigate({ view: "setup", file: read.name, ...(into ? { project: into } : {}) });
    } catch (e) {
      error = `${file.name}: ${(e as Error).message}`;
    } finally {
      reading = false;
      if (picker) picker.value = "";
    }
  }
</script>

<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full {LIBRARY_WIDTH} space-y-5 px-8 py-6" data-testid="agents-shelf">
    {#if error}<p class="text-sm text-danger" data-testid="agents-error">{error}</p>{/if}

    {#if more}
      {#if into}
        <div class="flex items-center gap-2.5 rounded-[10px] bg-accent-soft px-3.5 py-2 text-sm text-accent-soft-foreground" data-testid="agents-into">
          <Folder class="size-4" />Setting up in <b class="font-semibold text-foreground">{target?.name ?? "the project"}</b>
          <Button size="sm" variant="ghost" class="ml-auto" href={href({ view: "library", shelf: "agents", more: true })} data-testid="agents-into-clear"><X />Not for a project</Button>
        </div>
      {/if}
      <SourceShelf kind="agents" what="agents" project={into}>
        {#snippet extra()}
          <li class="flex flex-col gap-3 rounded-xl border border-dashed bg-muted/40 p-4">
            <span class="flex items-center gap-3">
              <span class="flex size-11 shrink-0 items-center justify-center rounded-xl bg-muted text-muted-foreground"><FileUp class="size-5" /></span>
              <span class="min-w-0"><span class="block font-semibold">From a file</span><span class="fact block">agents exported from a project</span></span>
            </span>
            <p class="text-sm text-muted-foreground">Here or on another computer. You choose their models next, and see what they may do.</p>
            <div class="mt-auto flex justify-end">
              <input bind:this={picker} type="file" accept=".zip,application/zip" class="hidden" onchange={(e) => readFile(e.currentTarget.files?.[0])} data-testid="agents-file-input" />
              <Button size="sm" variant="outline" disabled={reading} onclick={() => picker?.click()} data-testid="agents-file">Choose…</Button>
            </div>
          </li>
        {/snippet}
      </SourceShelf>
    {:else if !agents}
      <LoadingCards />
    {:else if !agents.length}
      <div class="rounded-[10px] border border-dashed px-6 py-8 text-center text-sm text-muted-foreground" data-testid="agents-none">
        <p>No agent yet: get one someone wrote for a job (a marketer, a reviewer), and set it up in a project.</p>
        <Button size="sm" class="mt-3" href={href({ view: "library", shelf: "agents", more: true })} data-testid="agents-get">Get agents</Button>
      </div>
    {:else}
      <div class="flex flex-wrap items-center gap-2">
        <Input class="min-w-64 flex-1" placeholder="Search agents" bind:value={query} data-testid="agents-search" />
        <div class="inline-flex rounded-lg bg-muted p-0.5 text-sm" role="group" aria-label="which agents">
          {#each FILTERS as f (f.id)}
            <button
              type="button"
              class="rounded-md px-3 py-1 {filter === f.id ? 'bg-background font-medium text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}"
              aria-pressed={filter === f.id}
              onclick={() => (filter = f.id)}
              data-testid="agents-filter-{f.id}">{f.label} <span class="fact">{counts[f.id]}</span></button
            >
          {/each}
        </div>
      </div>
      {#each groups as g (g.project?.id ?? "outside")}
        <section class="space-y-2" data-testid="agents-group">
          <h2 class="flex items-center gap-2 text-sm font-semibold">
            <Folder class="size-4 {g.project?.area ? `area-icon ${areas.colorClass(g.project.area)}` : 'text-muted-foreground'}" />
            {#if g.project}<a class="text-foreground no-underline hover:underline" href={href({ view: "project", id: g.project.id })}>{g.project.name}</a>{:else}<a class="text-foreground no-underline hover:underline" href={href({ view: "agents" })}>Agents outside projects</a>{/if}
            <span class="fact font-normal">{g.agents.length}</span>
          </h2>
          <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
            {#each g.agents as { agent, from } (agent.id)}
              <li data-testid="library-agent">
                <a
                  class="flex items-center gap-3 px-4 py-2 text-foreground no-underline hover:bg-muted/60"
                  href={href(agent.projectId ? { view: "project", id: agent.projectId, agent: agent.id } : { view: "agents", agent: agent.id })}
                >
                  <span class="flex size-7 shrink-0 items-center justify-center rounded-md bg-sky-500/10 text-sky-700 dark:text-sky-300"><Bot class="size-3.5" /></span>
                  <span class="min-w-0 flex-1 truncate"><span class="font-medium">{agentLabel(agent)}</span> <span class="fact">{who(agent)}</span></span>
                  <span class="shrink-0 text-xs {from ? 'text-primary' : 'text-muted-foreground'}" data-testid="agent-from">{from ? `from ${from}` : "made here"}</span>
                </a>
              </li>
            {/each}
          </ul>
        </section>
      {:else}
        <p class="rounded-[10px] border border-dashed px-4 py-4 text-center text-sm text-muted-foreground" data-testid="agents-nothing">Nothing here matches.</p>
      {/each}
    {/if}
  </div>
</div>
