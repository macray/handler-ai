<script lang="ts">
  // Home: every project, by name, so each keeps its place; an area to show only its projects, a
  // filter. A row opens its project; its pin puts it in the menu or takes it off (new projects
  // are pinned, and the menu lists only those). With no project yet, the first steps side by
  // side, the next one marked: connect a model, say where your code is, open a folder. Under the
  // projects, Other folders: the place of the agents of no project (but Chat's), always there.
  import Check from "@lucide/svelte/icons/check";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import Folder from "@lucide/svelte/icons/folder";
  import FolderOpen from "@lucide/svelte/icons/folder-open";
  import Pin from "@lucide/svelte/icons/pin";
  import PinOff from "@lucide/svelte/icons/pin-off";
  import Plus from "@lucide/svelte/icons/plus";
  import Search from "@lucide/svelte/icons/search";
  import ShieldCheck from "@lucide/svelte/icons/shield-check";
  import Smartphone from "@lucide/svelte/icons/smartphone";
  import Workflow from "@lucide/svelte/icons/workflow";
  import { areas } from "../lib/areas.svelte";
  import AreaTag from "../components/AreaTag.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import PageHeader from "../components/PageHeader.svelte";
  import PageTitle from "../components/PageTitle.svelte";
  import { api } from "../lib/api";
  import type { Agent, Project } from "../lib/contracts.gen";
  import { agentLabel, byName, matches, projects } from "../lib/projects.svelte";
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

  type Activity = { label: string; tone: "warn" | "ok" | "idle" };
  function activityOf(mine: LiveSession[], open: number): Activity | null {
    const waiting = mine.filter((s) => s.status === "needs-you").length;
    if (waiting) return { label: waiting === 1 ? "needs you" : `${waiting} need you`, tone: "warn" };
    if (mine.some((s) => s.status === "working")) return { label: "working", tone: "ok" };
    return open ? { label: `${open} open`, tone: "idle" } : null;
  }
  const outsideActivity = $derived(
    activityOf(
      sessions.list.filter((s) => !s.info.projectId),
      outside.reduce((n, a) => n + a.connections.length, 0),
    ),
  );

  /** A step's card: the next one ringed, the last one dimmed until it is next. */
  function card(id: "model" | "folders" | "project"): string {
    const ring = next === id ? "ring-2 ring-primary" : id === "project" ? "opacity-70" : "";
    return `flex min-h-56 flex-col gap-2.5 rounded-xl bg-card p-4.5 shadow-panel ${ring}`;
  }

  async function pin(p: Project, pinned: boolean): Promise<void> {
    error = null;
    try {
      await projects.setPinned(p.id, pinned);
    } catch (e) {
      error = (e as Error).message;
      return;
    }
    clearTimeout(toastTimer);
    unpinned = pinned ? null : p;
    if (!pinned) toastTimer = setTimeout(() => (unpinned = null), 6000);
  }
  void areas.load();
</script>

{#snippet state(s: Activity)}
  <span class="fact inline-flex shrink-0 items-center gap-1.5 {s.tone === 'warn' ? 'font-semibold text-warn' : ''}" data-testid="project-state">
    <span class="size-2 rounded-full {s.tone === 'warn' ? 'bg-warn' : s.tone === 'ok' ? 'bg-ok' : 'border-[1.5px] border-muted-foreground'}"></span>{s.label}
  </span>
{/snippet}

{#snippet pinIcon(pinned: boolean)}
  <Pin class="size-4 {pinned ? 'fill-current' : ''}" />
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

<PageHeader titled title="Projects">
  {#snippet actions()}
    <Button size="sm" href={href({ view: "edit-project" })} data-testid="new-project"><Plus />New project</Button>
  {/snippet}
</PageHeader>
<div class="flex-1 overflow-y-auto">
  {#if loaded && projects.list.length === 0}
    <!-- the first run: three steps side by side, the next one ringed and the only primary button -->
    <section class="mx-auto w-full max-w-4xl space-y-8 px-8 py-14" data-testid="get-started">
      <div class="space-y-2">
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
          <p class="font-mono text-xs text-foreground">{roots.join(", ") || "…"}</p>
          {#if steps.folders}
            <p class="mt-auto flex items-center gap-1.5 text-xs text-ok"><Check class="size-3.5" />{existing === 1 ? "It exists" : `${existing} exist`}</p>
          {:else}
            <Button class="mt-auto self-start" size="sm" variant={next === "folders" ? "default" : "outline"} href={href({ view: "settings", section: "folders" })}>Choose a folder</Button>
          {/if}
        </li>
        <li class={card("project")} data-testid="step-project">
          {@render step("project", 3, false)}
          <h2 class="text-[0.9375rem] font-semibold">Open a folder</h2>
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
    <div class="mx-auto w-full max-w-3xl space-y-6 px-8 py-10">
      <div class="flex flex-wrap items-center gap-3">
        <PageTitle title="Projects" />
        <div class="ml-auto flex flex-wrap items-center gap-2.5">
          {#if filters.length}
            <!-- one area at a time, or all -->
            <div class="inline-flex rounded-[9px] bg-muted p-0.5 ring-1 ring-border ring-inset" role="group" aria-label="area" data-testid="project-areas">
              {#each [null, ...filters] as a (a ?? "all")}
                <button
                  type="button"
                  class="rounded-[7px] px-3 py-1 text-[0.8125rem] transition-colors {area === a
                    ? 'bg-card text-foreground shadow-xs'
                    : 'text-muted-foreground hover:text-foreground'}"
                  aria-pressed={area === a}
                  onclick={() => (area = a)}>{a === null ? "All" : a === NO_AREA ? "No area" : a}</button
                >
              {/each}
            </div>
          {/if}
          <div class="relative">
            <Search class="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input bind:value={query} class="h-8 w-44 pl-8" placeholder="Filter" aria-label="filter projects" data-testid="project-search" />
          </div>
        </div>
      </div>
      {#if error || projects.error}<p class="text-sm text-danger">{error ?? projects.error}</p>{/if}

      {#if loaded}
        {#if listed.length}
          <!-- one card, a row each, by name; the whole row opens the project, its pin stays apart -->
          <ul class="divide-y overflow-hidden rounded-[10px] border bg-card shadow-panel" aria-label="projects">
            {#each listed as p (p.id)}
              {@const s = activity(p)}
              <li data-testid="project-row" class="group relative flex items-center gap-3.5 px-4 py-3.5 transition-colors hover:bg-muted/40">
                <span class="grid size-9 shrink-0 place-items-center rounded-lg bg-secondary">
                  <Folder class="size-4.5 {p.area ? `area-icon ${areas.colorClass(p.area)}` : 'text-muted-foreground'}" />
                </span>
                <span class="min-w-0 flex-1">
                  <span class="flex items-center gap-2">
                    <a
                      href={href({ view: "project", id: p.id })}
                      title={p.folder}
                      class="truncate font-semibold tracking-[-0.01em] text-foreground no-underline after:absolute after:inset-0"
                      data-testid="project-name">{p.name}</a
                    >
                    {#if p.area}<AreaTag name={p.area} />{/if}
                  </span>
                  {#if p.description}
                    <span class="block truncate text-sm text-muted-foreground">{p.description}</span>
                  {:else}
                    <span class="fact block truncate">{p.folder}</span>
                  {/if}
                </span>
                {#if s}{@render state(s)}{/if}
                <Button
                  variant="ghost"
                  size="icon"
                  class="relative z-10 size-8 shrink-0 {p.pinned ? 'text-primary hover:text-primary' : 'text-muted-foreground'}"
                  title={p.pinned ? "In the menu: unpin" : "Pin to the menu"}
                  aria-label={p.pinned ? `unpin ${p.name} from the menu` : `pin ${p.name} to the menu`}
                  aria-pressed={p.pinned}
                  onclick={() => pin(p, !p.pinned)}
                  data-testid="project-pin">{@render pinIcon(p.pinned)}</Button
                >
                <ChevronRight class="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
              </li>
            {/each}
          </ul>
        {:else}
          <p class="rounded-[10px] border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
            No project {query ? `matches “${query}”` : "in this area"}.
          </p>
        {/if}
        <!-- the place of the agents of no project (but Chat's and apps'): no pin, it is always in the menu -->
        <div class="group relative flex items-center gap-3.5 rounded-[10px] border bg-card px-4 py-3.5 shadow-panel transition-colors hover:bg-muted/40" data-testid="outside-row">
          <span class="grid size-9 shrink-0 place-items-center rounded-lg bg-secondary"><FolderOpen class="size-4.5 text-muted-foreground" /></span>
          <span class="min-w-0 flex-1">
            <span class="flex items-center gap-2">
              <a href={href({ view: "agents" })} class="truncate font-semibold tracking-[-0.01em] text-foreground no-underline after:absolute after:inset-0">Other folders</a>
              <span class="fact">{outside.length === 1 ? "1 agent" : `${outside.length} agents`}</span>
            </span>
            <span class="block truncate text-sm text-muted-foreground"
              >Agents of no project, in their own folder{outside.length ? `: ${outside.slice(0, 3).map(agentLabel).join(", ")}${outside.length > 3 ? "…" : ""}` : ""}</span
            >
          </span>
          {#if outsideActivity}{@render state(outsideActivity)}{/if}
          <ChevronRight class="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
        </div>
        <p class="flex items-center gap-1.5 text-xs text-muted-foreground"><Pin class="size-3" />Pinned projects are in the menu. New ones start pinned.</p>
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
    <Button variant="ghost" size="sm" class="font-semibold text-background hover:bg-background/15 hover:text-background" onclick={() => pin(p, true)} data-testid="unpinned-undo">Undo</Button>
  </div>
{/if}
