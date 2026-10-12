<script lang="ts">
  // Home: the projects, most recently used first. Open one to start a session with a request (type
  // to filter, then Enter), or create one. With no project yet, the first steps: connect a model,
  // say where your code is, open a folder (its first request is typed on its page).
  import FolderGit from "@lucide/svelte/icons/folder-git-2";
  import { contexts } from "../lib/contexts.svelte";
  import ContextTag from "../components/ContextTag.svelte";
  import When from "../components/When.svelte";
  import Plus from "@lucide/svelte/icons/plus";
  import Search from "@lucide/svelte/icons/search";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Kbd } from "$lib/components/ui/kbd";
  import PageHeader from "../components/PageHeader.svelte";
  import PageTitle from "../components/PageTitle.svelte";
  import { api } from "../lib/api";
  import type { Project } from "../lib/contracts.gen";
  import { agentLabel, byRecentUse, matches, projects } from "../lib/projects.svelte";
  import { href, navigate } from "../lib/router.svelte";
  import { sessions } from "../lib/sessions.svelte";

  let access = $state(0); // accounts and providers ready to use (logged in, key set)
  let unready = $state(0); // those there are but cannot be used yet (not logged in, no key)
  let accessLoaded = $state(false);
  let roots = $state<string[]>([]); // the work folders, as written
  let existing = $state(0); // how many of them exist
  let error = $state<string | null>(null);
  let query = $state("");
  let search: HTMLInputElement | null = $state(null);

  const listed = $derived(byRecentUse(projects.list).filter((p) => matches(p, query)));
  const loaded = $derived(projects.loaded && accessLoaded);

  $effect(() => {
    void projects.refresh();
    Promise.all([api.accounts(), api.providers()]).then(
      ([a, p]) => {
        const all = [...a, ...p];
        access = all.filter((x) => x.status === "ready").length;
        unready = all.filter((x) => x.status === "incomplete").length;
        accessLoaded = true;
      },
      (e: Error) => (error = e.message),
    );
    api.folders().then(
      (f) => {
        roots = f.folders.map((x) => x.root);
        existing = f.folders.filter((x) => x.exists).length;
      },
      (e: Error) => (error = e.message),
    );
  });

  // "/" focuses the search, from anywhere on the page but a field
  $effect(() => {
    const key = (e: KeyboardEvent) => {
      const field = e.target instanceof HTMLElement && e.target.closest("input, textarea, select, [contenteditable]");
      if (e.key === "/" && !field) {
        e.preventDefault();
        search?.focus();
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  });

  function running(p: Project): number {
    return p.agents.reduce((n, a) => n + a.connections.length, 0);
  }

  function searchKey(e: KeyboardEvent): void {
    if (e.key === "Enter" && listed[0]) navigate({ view: "project", id: listed[0].id });
    if (e.key === "Escape") query = "";
  }
  void contexts.load();
</script>

<PageHeader titled title="Projects">
  {#snippet actions()}
    <Button size="sm" href={href({ view: "edit-project" })} data-testid="new-project"><Plus />New project</Button>
  {/snippet}
</PageHeader>
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-4xl space-y-6 px-8 py-10">
    <PageTitle title="Projects" description="What you work on: a code folder, and the agents you work on it with." />
    {#if error || projects.error}<p class="text-sm text-danger">{error ?? projects.error}</p>{/if}

    {#if loaded && projects.list.length === 0}
      <section class="space-y-4 rounded-lg border bg-card p-5" data-testid="get-started">
        <div class="space-y-1">
          <h2 class="text-base font-semibold">Get started</h2>
          <p class="text-sm text-muted-foreground">
            Three steps to your first request.
          </p>
        </div>
        <ol class="space-y-4 text-sm">
          <li class="flex gap-3" data-testid="step-model">
            <span class="mt-0.5 size-5 shrink-0 rounded-full border text-center text-xs leading-5 {access ? 'border-ok text-ok' : ''}">{access ? "✓" : "1"}</span>
            <div class="space-y-1">
              <p class="font-medium">Connect a model</p>
              <p class="text-xs text-muted-foreground">
                A subscription you log in with (an account), an API key or a local server (a provider): how an agent's harness (Claude Code,
                Codex, Vibe, pi…) reaches a model.
                {#if !access && unready}<span class="text-warn">Not ready yet: log in to your account, or set your provider's key.</span>{/if}
              </p>
              <Button size="sm" variant={access ? "outline" : "default"} href={href({ view: "settings", section: "models" })}>
                {access ? "Model access" : unready ? "Finish connecting" : "Connect a model"}
              </Button>
            </div>
          </li>
          <li class="flex gap-3" data-testid="step-folders">
            <span class="mt-0.5 size-5 shrink-0 rounded-full border text-center text-xs leading-5 {existing ? 'border-ok text-ok' : ''}">{existing ? "✓" : "2"}</span>
            <div class="space-y-1">
              <p class="font-medium">Say where your code is</p>
              <p class="text-xs text-muted-foreground">
                Agents only work inside these folders: <span class="font-mono">{roots.join(", ") || "…"}</span>.
                {#if roots.length && !existing}<span class="text-warn">None of them exists yet: create one, or choose another.</span>{/if}
              </p>
              <Button size="sm" variant="outline" href={href({ view: "settings", section: "folders" })}>Folders</Button>
            </div>
          </li>
          <li class="flex gap-3" data-testid="step-project">
            <span class="mt-0.5 size-5 shrink-0 rounded-full border text-center text-xs leading-5">3</span>
            <div class="space-y-1">
              <p class="font-medium">Open a folder</p>
              <p class="text-xs text-muted-foreground">It becomes a project with a first agent; type your first request on its page.</p>
              <Button size="sm" href={href({ view: "edit-project" })} disabled={!access} data-testid="get-started-project"><Plus />New project</Button>
            </div>
          </li>
        </ol>
      </section>
    {:else if loaded}
      <div class="relative">
        <Search class="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          bind:ref={search}
          bind:value={query}
          onkeydown={searchKey}
          class="pl-8"
          placeholder="Filter by name, folder or agent; Enter opens the first"
          aria-label="filter projects"
          data-testid="project-search"
        />
        <Kbd class="absolute top-1/2 right-2 -translate-y-1/2">/</Kbd>
      </div>

      <ul class="divide-y overflow-hidden rounded-lg border bg-card" aria-label="projects">
        {#each listed as p (p.id)}
          {@const live = running(p)}
          {@const waiting = sessions.list.filter((s) => s.info.projectId === p.id && s.status === "needs-you").length}
          <li data-testid="project-row">
            <a class="flex items-center gap-3 px-4 py-3 no-underline hover:bg-accent/50" href={href({ view: "project", id: p.id })} title={p.folder}>
              <FolderGit class="mt-1 size-4 shrink-0 self-start {p.context ? `ctx-icon ${contexts.colorClass(p.context)}` : 'text-muted-foreground'}" />
              <span class="min-w-0 flex-1">
                <span class="flex items-center gap-2">
                  <span class="truncate font-medium text-foreground" data-testid="project-name">{p.name}</span>
                  {#if p.context}<ContextTag name={p.context} />{/if}
                  {#if waiting}
                    <span class="shrink-0 text-xs font-medium text-warn">{waiting} {waiting === 1 ? "needs" : "need"} you</span>
                  {:else if live}
                    <span class="shrink-0 text-xs text-muted-foreground">{live} open session{live === 1 ? "" : "s"}</span>
                  {/if}
                </span>
                {#if p.description}<span class="block truncate text-sm text-muted-foreground">{p.description}</span>{/if}
                <span class="block truncate font-mono text-xs text-muted-foreground">{p.folder}</span>
              </span>
              <span class="hidden max-w-64 shrink truncate text-xs text-muted-foreground sm:block" data-testid="project-agents">
                {p.agents.map(agentLabel).join(" · ")}
              </span>
              <span class="hidden w-24 shrink-0 text-right text-xs text-muted-foreground md:block" title={p.lastUsedAt ?? ""}>
                <When at={p.lastUsedAt ?? p.createdAt} />
              </span>
            </a>
          </li>
        {:else}
          <li class="px-4 py-6 text-center text-sm text-muted-foreground">No project matches “{query}”.</li>
        {/each}
      </ul>
    {/if}
  </div>
</div>
