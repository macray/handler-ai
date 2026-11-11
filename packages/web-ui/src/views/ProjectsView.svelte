<script lang="ts">
  // Projects, where Handler opens the first time and on the logo: every project, by name, so each
  // keeps its place; an area to show only its projects, a filter on what the rows show. A row opens
  // its project: its name and area, its description or its folder (short, whole in the tooltip),
  // what its sessions do only when they do something, when it was last used, its pin (D.28: only
  // the first project is pinned by itself; the outline only on hover). One waiting for you is
  // amber, and its Open session goes to the session waiting longest: the row and the session are
  // two ways in. With no project yet (no header: the first run's title is the page's), the first
  // steps side by side, the next one marked: connect a model, say where your code is, a new
  // project. Under the projects, Agents outside projects: one row, the place of the agents of no
  // project (but Chat's and apps'), counted, never listed; always there.
  import Check from "@lucide/svelte/icons/check";
  import Folder from "@lucide/svelte/icons/folder";
  import FolderOpen from "@lucide/svelte/icons/folder-open";
  import PinOff from "@lucide/svelte/icons/pin-off";
  import PinButton from "../components/PinButton.svelte";
  import Plus from "@lucide/svelte/icons/plus";
  import Search from "@lucide/svelte/icons/search";
  import ShieldCheck from "@lucide/svelte/icons/shield-check";
  import Smartphone from "@lucide/svelte/icons/smartphone";
  import Workflow from "@lucide/svelte/icons/workflow";
  import type { Snippet } from "svelte";
  import { areas } from "../lib/areas.svelte";
  import AreaTag from "../components/AreaTag.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import MenuButton from "../components/MenuButton.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import { ago, exactTime } from "../lib/agents";
  import { api } from "../lib/api";
  import type { Agent, Project } from "../lib/contracts.gen";
  import { byName, matches, projects, shortFolder } from "../lib/projects.svelte";
  import { pins } from "../lib/pins.svelte";
  import { href } from "../lib/router.svelte";
  import { sessions, type LiveSession } from "../lib/sessions.svelte";

  const NO_AREA = ""; // the area filter's value for projects without one

  let ready = $state<string[]>([]); // accounts and providers ready to use (logged in, key set)
  let unready = $state(0); // those there are but cannot be used yet (not logged in, no key)
  let accessLoaded = $state(false);
  let roots = $state<string[]>([]); // the work folders, as written
  let existing = $state(0); // how many of them exist
  let outside = $state<Agent[]>([]); // the agents of no project, most recently used first
  let error = $state<string | null>(null);
  let query = $state("");
  let area = $state<string | null>(null); // null: all
  let unpinned = $state<Project | null>(null); // just taken off the menu: the toast offers Undo
  let toastTimer: ReturnType<typeof setTimeout> | undefined;

  const loaded = $derived(projects.loaded && accessLoaded);
  // the areas the projects are in, and "No area" when some are in one and some in none
  const usedAreas = $derived([...new Set(projects.list.flatMap((p) => (p.area ? [p.area] : [])))].sort());
  const filters = $derived(
    usedAreas.length ? [...usedAreas, ...(projects.list.some((p) => !p.area) ? [NO_AREA] : [])] : [],
  );
  const inArea = (p: Project, a: string | null) => a === null || (p.area ?? NO_AREA) === a;
  const listed = $derived(byName(projects.list).filter((p) => inArea(p, area) && matches(p, query)));
  // the steps: done ones say what is ready, the first one not done is the next
  const steps = $derived({ model: ready.length > 0, folders: existing > 0 });
  const next = $derived(!steps.model ? "model" : !steps.folders ? "folders" : "project");

  $effect(() => {
    void projects.refresh();
    Promise.all([api.accounts(), api.providers()]).then(
      ([a, p]) => {
        const all = [...a, ...p];
        ready = all.filter((x) => x.status === "ready").map((x) => x.name);
        unready = all.filter((x) => x.status === "incomplete").length;
        accessLoaded = true;
      },
      (e: Error) => (error = e.message),
    );
    api.agents().then(
      (all) => (outside = all.filter((a) => !a.projectId && !a.app && !a.chat).sort((a, b) => (b.lastUsedAt ?? b.createdAt).localeCompare(a.lastUsedAt ?? a.createdAt))),
      (e: Error) => (error = e.message),
    );
    api.folders().then(
      (f) => {
        roots = f.folders.map((x) => x.root);
        existing = f.folders.filter((x) => x.exists).length;
      },
      (e: Error) => (error = e.message),
    );
    return () => clearTimeout(toastTimer);
  });

  /** What its sessions do, said only when they do something: one waits for you, or one works. */
  function activity(p: Project): Activity | null {
    return activityOf(
      sessions.list.filter((s) => s.info.projectId === p.id),
      p.agents.reduce((n, a) => n + a.connections.length, 0),
    );
  }

  // waiting: the session waiting longest (the oldest last activity), what Open session opens
  type Activity = { tone: "warn" | "ok" | "idle"; label: string; waiting?: LiveSession };
  function activityOf(mine: LiveSession[], open: number): Activity | null {
    const waiting = mine.filter((s) => s.status === "needs-you");
    if (waiting.length) {
      const longest = waiting.reduce((a, b) => (b.info.lastActivityAt < a.info.lastActivityAt ? b : a));
      return { tone: "warn", label: waiting.length === 1 ? "needs you" : `${waiting.length} need you`, waiting: longest };
    }
    if (mine.some((s) => s.status === "working")) return { tone: "ok", label: "working" };
    return open ? { tone: "idle", label: `${open} open` } : null;
  }
  const outsideIds = $derived(new Set(outside.map((a) => a.id)));
  const outsideActivity = $derived(
    activityOf(
      sessions.list.filter((s) => !s.info.projectId && outsideIds.has(s.info.agentId)),
      outside.reduce((n, a) => n + a.connections.length, 0),
    ),
  );
  // the command line's agents (no name: called by their folder), counted on the row
  const fromCommandLine = $derived(outside.filter((a) => !a.name).length);
  const outsideCount = $derived(
    outside.length
      ? `${outside.length === 1 ? "1 agent" : `${outside.length} agents`}${fromCommandLine ? ` · ${fromCommandLine} from the command line` : ""}`
      : "No agent yet",
  );

  /** A step's card: the next one ringed, the last one flat (an outline, no lift) until it is
   *  next; its text stays readable: it says why it waits. */
  function card(id: "model" | "folders" | "project"): string {
    const look = next === id ? "shadow-panel ring-2 ring-primary" : id === "project" ? "ring-1 ring-border ring-inset" : "shadow-panel";
    return `flex min-h-56 flex-col gap-2.5 rounded-xl bg-card p-4.5 ${look}`;
  }

  /** Taken off the menu: the toast offers Undo for a while. */
  function wasUnpinned(p: Project): void {
    clearTimeout(toastTimer);
    unpinned = p;
    toastTimer = setTimeout(() => (unpinned = null), 6000);
  }

  async function undo(p: Project): Promise<void> {
    clearTimeout(toastTimer);
    unpinned = null;
    await pins.pin("project", p.id).catch(() => {});
  }
  void areas.load();
</script>

{#snippet state(s: Activity)}
  <!-- one state element: a dot and a word; amber only for needs you; open alone, a hollow dot -->
  {#if s.tone === "warn"}
    <span class="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-warn/12 px-2 py-px text-xs font-semibold text-warn ring-1 ring-warn/30 ring-inset" data-testid="project-state"
      ><span class="size-1.5 rounded-full bg-warn"></span>{s.label}</span
    >
  {:else if s.tone === "ok"}
    <span class="inline-flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground" data-testid="project-state"><span class="size-1.5 rounded-full bg-ok"></span>{s.label}</span>
  {:else}
    <span class="size-2 shrink-0 rounded-full border-[1.5px] border-muted-foreground" title={s.label} aria-label={s.label} data-testid="project-state"></span>
  {/if}
{/snippet}

{#snippet openSession(s: Activity | null)}
  {#if s?.waiting}
    <Button
      variant="outline"
      size="sm"
      class="relative z-10 h-7 shrink-0 border-warn/40 bg-card font-semibold text-warn hover:bg-warn/10 hover:text-warn"
      href={href({ view: "session", key: s.waiting.key })}
      data-testid="open-session">Open session</Button
    >
  {/if}
{/snippet}

{#snippet row(s: Activity | null, testid: string, body: Snippet, end: Snippet)}
  <!-- 64px, airy; the whole row is its link (`after:inset-0`), its buttons stay apart above it -->
  <div
    class="group relative flex min-h-16 items-center gap-4 px-5 py-3 transition-colors {s?.tone === 'warn'
      ? 'bg-warn/[0.07] before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:bg-warn hover:bg-warn/10'
      : 'hover:bg-muted/40'}"
    data-testid={testid}
  >
    {@render body()}
    {@render openSession(s)}
    {@render end()}
  </div>
{/snippet}

{#snippet step(id: "model" | "folders" | "project", n: number, done: boolean)}
  <span
    class="grid size-6.5 place-items-center rounded-full font-mono text-xs {done
      ? 'bg-ok text-white'
      : next === id
        ? 'bg-primary text-primary-foreground'
        : 'text-muted-foreground ring-[1.5px] ring-border ring-inset'}">{#if done}<Check class="size-3.5" />{:else}{n}{/if}</span
  >
{/snippet}

{#if !(loaded && projects.list.length === 0)}
  <!-- one column, Apps' width; its controls one line, staying with the title -->
  <PageHeader title="Projects" width="max-w-[944px]">
    {#snippet actions()}
      {#if filters.length}
        <!-- one area at a time, or all -->
        <div class="inline-flex rounded-[9px] bg-muted p-0.5 ring-1 ring-border ring-inset" role="group" aria-label="area" data-testid="project-areas">
          {#each [null, ...filters] as a (a ?? "all")}
            <button
              type="button"
              class="rounded-[7px] px-3 py-1 text-[0.8125rem] transition-colors {area === a ? 'bg-card text-foreground shadow-xs' : 'text-muted-foreground hover:text-foreground'}"
              aria-pressed={area === a}
              onclick={() => (area = a)}>{a === null ? "All" : a === NO_AREA ? "No area" : a}</button
            >
          {/each}
        </div>
      {/if}
      <div class="relative">
        <Search class="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input bind:value={query} class="h-8 w-48 pl-8" placeholder="Filter" aria-label="filter projects" data-testid="project-search" />
      </div>
      <Button size="sm" class="ml-auto" href={href({ view: "edit-project" })} data-testid="new-project"><Plus />New project</Button>
    {/snippet}
  </PageHeader>
{/if}
<div class="flex-1 overflow-y-auto">
  {#if loaded && projects.list.length === 0}
    <!-- the first run: three steps side by side, the next one ringed and the only primary button -->
    <section class="mx-auto w-full max-w-4xl space-y-8 px-8 py-14" data-testid="get-started">
      <div class="space-y-2">
        <div class="-mt-10 mb-4 md:hidden"><MenuButton /></div>
        <h1 class="text-[1.875rem] leading-tight font-semibold tracking-[-0.022em]">Your first project</h1>
        <p class="max-w-2xl text-[0.9375rem] text-muted-foreground">
          A project is a folder and the agents you work on it with. Each agent runs in its own sandbox and sees only that folder.
        </p>
      </div>
      {#if error}<p class="text-sm text-danger">{error}</p>{/if}
      <div class="h-1 overflow-hidden rounded-full bg-muted" aria-hidden="true">
        <div class="h-full bg-ok transition-[width] duration-(--dur-3) ease-(--ease)" style="width: {(Number(steps.model) + Number(steps.folders)) * 33.3}%"></div>
      </div>
      <ol class="grid gap-3.5 sm:grid-cols-3">
        <li class={card("model")} data-testid="step-model">
          {@render step("model", 1, steps.model)}
          <h2 class="text-[0.9375rem] font-semibold">Connect a model</h2>
          <p class="text-sm text-muted-foreground">An API key, a local model, or your own subscription for your own use.</p>
          {#if steps.model}
            <p class="mt-auto flex items-center gap-1.5 text-xs text-ok"><Check class="size-3.5" /><span class="font-mono">{ready.join(", ")}</span> ready</p>
          {:else}
            {#if unready}<p class="text-xs text-warn">Not ready yet: log in to your account, or set your provider's key.</p>{/if}
            <Button class="mt-auto self-start" size="sm" href={href({ view: "settings", section: "models" })}>{unready ? "Finish connecting" : "Connect a model"}</Button>
          {/if}
        </li>
        <li class={card("folders")} data-testid="step-folders">
          {@render step("folders", 2, steps.folders)}
          <h2 class="text-[0.9375rem] font-semibold">Say where your code is</h2>
          <p class="text-sm text-muted-foreground">
            Agents only work inside these folders{#if roots.length && !existing}. None of them exists yet{/if}:
          </p>
          <!-- a path breaks only after a / or a comma, never inside a name -->
          <p class="font-mono text-xs text-foreground">
            {#each (roots.join(", ") || "…").split(/(?<=[/,])/) as part, i (i)}<span class="whitespace-nowrap">{part}</span><wbr />{/each}
          </p>
          {#if steps.folders}
            <p class="mt-auto flex items-center gap-1.5 text-xs text-ok"><Check class="size-3.5" />{existing === 1 ? "It exists" : `${existing} exist`}</p>
          {:else}
            <Button class="mt-auto self-start" size="sm" variant={next === "folders" ? "default" : "outline"} href={href({ view: "settings", section: "folders" })}>Choose a folder</Button>
          {/if}
        </li>
        <li class={card("project")} data-testid="step-project">
          {@render step("project", 3, false)}
          <h2 class="text-[0.9375rem] font-semibold">New project</h2>
          <p class="text-sm text-muted-foreground">It becomes a project with a first agent. Then type your first request on its page.</p>
          {#if !steps.model}<p class="text-xs text-muted-foreground">Connect a model first.</p>{/if}
          <Button
            class="mt-auto self-start"
            size="sm"
            variant={next === "project" ? "default" : "outline"}
            href={href({ view: "edit-project" })}
            disabled={!steps.model}
            data-testid="get-started-project"><Plus />New project</Button
          >
        </li>
      </ol>
      <div class="grid gap-6 text-sm text-muted-foreground sm:grid-cols-3">
        <p><span class="mb-1 flex items-center gap-2 font-semibold text-foreground"><ShieldCheck class="size-4" />Sandboxed</span>Each session runs in a container that reaches only its folder and the hosts you allow.</p>
        <p><span class="mb-1 flex items-center gap-2 font-semibold text-foreground"><Smartphone class="size-4" />Follow from anywhere</span>Pair your phone to answer an agent that needs you.</p>
        <p><span class="mb-1 flex items-center gap-2 font-semibold text-foreground"><Workflow class="size-4" />On its own</span>Later: agents that run at a time you set, or when a session stops.</p>
      </div>
    </section>
  {:else}
    <div class="mx-auto w-full max-w-[944px] space-y-4 px-8 pt-5 pb-8">
      {#if error || projects.error || pins.error}<p class="text-sm text-danger">{error ?? projects.error ?? pins.error}</p>{/if}

      {#if loaded}
        {#if listed.length}
          <!-- one card, a row each, by name -->
          <ul class="divide-y overflow-hidden rounded-[10px] border bg-card shadow-panel" aria-label="projects">
            {#each listed as p (p.id)}
              {@const s = activity(p)}
              <li>
                {#snippet body()}
                  <Folder class="size-4.5 shrink-0 {p.area ? `area-icon ${areas.colorClass(p.area)}` : 'text-muted-foreground'}" />
                  <span class="min-w-0 flex-1">
                    <span class="flex min-w-0 items-center gap-2">
                      <a
                        href={href({ view: "project", id: p.id })}
                        title={p.folder}
                        class="truncate leading-5 font-semibold tracking-[-0.01em] text-foreground no-underline after:absolute after:inset-0"
                        data-testid="project-name">{p.name}</a
                      >
                      <!-- the area said once: not when only its projects are shown -->
                      {#if p.area && area === null}<span class="inline-flex opacity-75"><AreaTag name={p.area} /></span>{/if}
                      {#if s}{@render state(s)}{/if}
                    </span>
                    {#if p.description}
                      <span class="mt-0.5 block truncate text-[0.8125rem] leading-[18px] text-muted-foreground">{p.description}</span>
                    {:else}
                      <span class="mt-0.5 block truncate font-mono text-xs leading-[18px] text-muted-foreground" title={p.folder}>{shortFolder(p.folder)}</span>
                    {/if}
                  </span>
                {/snippet}
                {#snippet end()}
                  <span
                    class="w-24 shrink-0 text-right text-xs {s?.tone === 'warn' ? 'text-warn' : 'text-muted-foreground'}"
                    title={p.lastUsedAt ? exactTime(p.lastUsedAt) : undefined}
                    data-testid="project-last-used">{ago(p.lastUsedAt)}</span
                  >
                  <!-- the filled pin always; the outline one on hover or focus -->
                  <span class={pins.has("project", p.id) ? "" : "opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100"}>
                    <PinButton kind="project" id={p.id} label={p.name} onunpin={() => wasUnpinned(p)} />
                  </span>
                {/snippet}
                {@render row(s, "project-row", body, end)}
              </li>
            {/each}
          </ul>
        {:else}
          <p class="rounded-[10px] border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
            No project {query ? `matches “${query}”` : "in this area"}.
          </p>
        {/if}
        <!-- the place of the agents of no project (but Chat's and apps'): one row, whatever the
             area or the filter, never hidden; its agents counted, not listed; no pin -->
        <div class="overflow-hidden rounded-[10px] border bg-card shadow-panel">
          {#snippet body()}
            <FolderOpen class="size-4.5 shrink-0 text-muted-foreground" />
            <span class="min-w-0 flex-1">
              <span class="flex min-w-0 items-center gap-2">
                <a href={href({ view: "agents" })} class="truncate leading-5 font-semibold tracking-[-0.01em] text-foreground no-underline after:absolute after:inset-0">Agents outside projects</a>
                {#if outsideActivity}{@render state(outsideActivity)}{/if}
              </span>
              <span class="mt-0.5 block truncate font-mono text-xs leading-[18px] text-muted-foreground" data-testid="outside-count">{outsideCount}</span>
            </span>
          {/snippet}
          {#snippet end()}<span class="size-8 shrink-0"></span>{/snippet}
          {@render row(outsideActivity, "outside-row", body, end)}
        </div>
      {/if}
    </div>
  {/if}
</div>

{#if unpinned}
  {@const p = unpinned}
  <div
    class="enter fixed bottom-6 left-1/2 z-50 flex -translate-x-1/2 items-center gap-3 rounded-[10px] bg-foreground py-2 pr-2 pl-4 text-sm text-background shadow-lift"
    role="status"
    data-testid="unpinned-toast"
  >
    <PinOff class="size-4" /><span><b class="font-semibold">{p.name}</b> is no longer in the menu. It stays here.</span>
    <Button variant="ghost" size="sm" class="font-semibold text-background hover:bg-background/15 hover:text-background" onclick={() => undo(p)} data-testid="unpinned-undo">Undo</Button>
  </div>
{/if}
