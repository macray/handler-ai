<script lang="ts">
  // The caches (D.8), disk first. The total on this computer, one bar by cache (each cache's
  // total across its folders) and what removed caches left, freed apart. Then where they are: the
  // global folder (the projects that chose it, and agents outside projects) and each project's
  // own, each row opened to show its caches and emptied apart or all at once (refused while a
  // session uses it); every project's choice (its own, the global ones, none) changed from its
  // chip. Last, what is kept for every project: the toolbox's caches (its toolbox.toml, saved
  // from here), added in a dialog. A cache has one name everywhere, the start of its `about`
  // (before ": "), and one colour. Sizes are measured after the page shows: it may take seconds.
  import Ban from "@lucide/svelte/icons/ban";
  import Check from "@lucide/svelte/icons/check";
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import Database from "@lucide/svelte/icons/database";
  import Folder from "@lucide/svelte/icons/folder";
  import Plus from "@lucide/svelte/icons/plus";
  import RefreshCw from "@lucide/svelte/icons/refresh-cw";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import { Button } from "$lib/components/ui/button";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import { Skeleton } from "$lib/components/ui/skeleton";
  import Dialog from "./Dialog.svelte";
  import Popover from "./Popover.svelte";
  import { api } from "../lib/api";
  import type { CacheDeclaration, CacheInfo, CachesInfo, Project } from "../lib/contracts.gen";
  import { projectBody, projectSpec } from "../lib/projects.svelte";
  import { formatBytes } from "../lib/text";

  type Mode = NonNullable<Project["caches"]>;
  // a folder of caches, as a row: the global one or a project's own
  type Place = {
    key: string;
    title: string;
    folder: string;
    caches: Record<string, string>; // cache → its folder
    removed: Record<string, string>; // removed cache → what it left
    project: Project | null; // null: the global one
    emptyAll: () => Promise<void>;
    emptyOne: (cache: string) => Promise<void>;
  };
  // what a confirmation lists: a cache (its colour; none: what a removed one left) and its size
  type Line = { name: string; color: string | null; size: number };
  type Ask = { title: string; lines: Line[]; note: string; label: string; danger: boolean; action: () => Promise<void> };

  // one colour per cache, in the toolbox's order (the dataviz reference palette's)
  const PALETTE = ["#2a78d6", "#1baf7a", "#eda100", "#e87ba4", "#6250d6", "#0e9fb3", "#c4532b", "#7a8a1e"];
  const HATCH = "repeating-linear-gradient(135deg, color-mix(in srgb, var(--muted-foreground) 55%, transparent) 0 2px, transparent 2px 5px)";
  const MODES: { value: Mode; label: string; chip: string }[] = [
    { value: "project", label: "Its own caches", chip: "Own caches" },
    { value: "global", label: "The global caches", chip: "Global" },
    { value: "off", label: "No caches", chip: "No caches" },
  ];

  let info = $state<CachesInfo | null>(null);
  let projects = $state<Project[]>([]);
  let sizes = $state<Record<string, number> | null>(null);
  let measuring = $state(false);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let target = $state("~/.");
  let about = $state("");
  let general = $state(false);
  let adding = $state(false); // the Add dialog open
  let ask = $state<Ask | null>(null); // a confirmation shown
  let asking = $state(false);
  let askError = $state<string | null>(null);
  // the folders opened to show their caches one by one
  let open = $state<Record<string, boolean>>({});

  async function measure(): Promise<void> {
    measuring = true;
    try {
      sizes = (await api.cacheSizes()).sizes;
    } catch (e) {
      error = (e as Error).message;
    } finally {
      measuring = false;
    }
  }

  async function load(): Promise<void> {
    [info, projects] = await Promise.all([api.caches(), api.projects()]);
  }

  load().then(
    () => void measure(),
    (e: Error) => (error = e.message),
  );

  async function run(action: () => Promise<void>): Promise<void> {
    busy = true;
    error = null;
    try {
      await action();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  // a cache's name: its `about` up to ": "; what follows says more
  const nameOf = (about: string) => about.split(": ")[0] ?? about;
  const moreOf = (about: string) => about.split(": ").slice(1).join(": ");
  const cacheName = (key: string) => {
    const c = info?.caches.find((x) => x.name === key);
    return c ? nameOf(c.about) : key;
  };
  const colorOf = (key: string): string | null => {
    const i = info?.caches.findIndex((c) => c.name === key) ?? -1;
    return i < 0 ? null : (PALETTE[i % PALETTE.length] ?? null);
  };
  const swatch = (color: string | null) => `background:${color ?? HATCH}`;
  const sizeOf = (folder: string) => sizes?.[folder] ?? 0;

  const byId = $derived(Object.fromEntries(projects.map((p) => [p.id, p])));
  const byName = $derived(Object.fromEntries(projects.map((p) => [p.name, p])));
  const places = $derived.by((): Place[] => {
    if (!info) return [];
    const global: Place = {
      key: "global",
      title: "Global",
      folder: info.global.folder,
      caches: info.global.caches,
      removed: info.global.removed ?? {},
      project: null,
      emptyAll: () => api.emptyGlobalCaches(),
      emptyOne: (cache) => api.emptyCache(cache),
    };
    const own = (info.own ?? []).map(
      (p): Place => ({
        key: p.projectId,
        title: p.name,
        folder: p.folder,
        caches: p.caches,
        removed: p.removed ?? {},
        project: byId[p.projectId] ?? null,
        emptyAll: () => api.emptyProjectCaches(p.projectId),
        emptyOne: (cache) => api.emptyProjectCache(p.projectId, cache),
      }),
    );
    return [global, ...own];
  });
  const totalOf = (p: Place) => [...Object.values(p.caches), ...Object.values(p.removed)].reduce((n, f) => n + sizeOf(f), 0);
  const total = $derived(places.reduce((n, p) => n + totalOf(p), 0));
  const biggest = $derived(Math.max(1, ...places.map(totalOf)));
  // each cache's total across its folders
  const byCache = $derived(
    (info?.caches ?? []).map((c) => ({ key: c.name, size: places.reduce((n, p) => n + sizeOf(p.caches[c.name] ?? ""), 0) })),
  );
  // what each removed cache left, folder by folder
  const leftovers = $derived.by(() => {
    const found: Record<string, { place: Place; size: number }[]> = {};
    for (const p of places) for (const [cache, folder] of Object.entries(p.removed)) (found[cache] ??= []).push({ place: p, size: sizeOf(folder) });
    return Object.entries(found).map(([cache, where]) => ({ cache, where, size: where.reduce((n, w) => n + w.size, 0) }));
  });
  // the projects using the global caches; those with none; a project's own folder kept after it chose otherwise
  const onGlobal = $derived(projects.filter((p) => p.caches === "global").sort((a, b) => a.name.localeCompare(b.name)));
  const ownIds = $derived(new Set((info?.own ?? []).map((p) => p.projectId)));
  const without = $derived(projects.filter((p) => p.caches === "off" && !ownIds.has(p.id)));
  const onPath = $derived((info?.caches ?? []).filter((c) => c.bin || c.target === "~/.local").map((c) => nameOf(c.about)));
  const valid = $derived(about.trim() !== "" && /^(\/|~\/)./.test(target.trim()));
  // the projects named on the Global row but not known (yet) as projects
  const unknownOnGlobal = $derived((info?.global.projects ?? []).filter((n) => !byName[n]));

  // the user's own: the only ones saved from here
  const own = (): CacheDeclaration[] =>
    (info?.caches ?? []).filter((c) => c.declaredBy.includes("user")).map((c) => ({ target: c.target, about: c.about, general: c.general }));

  function add(): void {
    void run(async () => {
      info = await api.setCaches([...own(), { target: target.trim(), about: about.trim(), general }]);
      target = "~/.";
      about = "";
      general = false;
      adding = false;
      void measure();
    });
  }

  function confirm(a: Ask): void {
    askError = null;
    ask = a;
    asking = true;
  }

  async function confirmed(): Promise<void> {
    if (!ask) return;
    busy = true;
    askError = null;
    try {
      await ask.action();
      asking = false;
    } catch (e) {
      askError = (e as Error).message;
    } finally {
      busy = false;
    }
    await measure();
  }

  function remove(c: CacheInfo): void {
    const left = places.reduce((n, p) => n + sizeOf(p.caches[c.name] ?? ""), 0);
    confirm({
      title: `Stop keeping ${nameOf(c.about)}?`,
      lines: [],
      note: `New sessions start without ${c.target}.${left ? ` Its files (${formatBytes(left)}) stay until freed.` : ""}`,
      label: "Stop keeping",
      danger: true,
      action: async () => {
        info = await api.setCaches(own().filter((d) => d.target !== c.target));
      },
    });
  }

  function emptyAll(p: Place): void {
    const lines: Line[] = [
      ...Object.entries(p.caches).map(([k, f]) => ({ name: cacheName(k), color: colorOf(k), size: sizeOf(f) })),
      ...Object.entries(p.removed).map(([k, f]) => ({ name: `${k} · no longer kept`, color: null, size: sizeOf(f) })),
    ].filter((l) => l.size);
    confirm({
      title: p.project ? `Empty ${p.title}'s caches?` : "Empty the global caches?",
      lines,
      note: "Tools download and build them again when needed.",
      label: `Empty ${formatBytes(totalOf(p))}`,
      danger: true,
      action: p.emptyAll,
    });
  }

  function emptyOne(p: Place, cache: string): void {
    confirm({
      title: `Empty ${cacheName(cache)}${p.project ? ` of ${p.title}` : " (global)"}?`,
      lines: [],
      note: "Tools download and build it again when needed.",
      label: `Empty ${formatBytes(sizeOf(p.caches[cache] ?? ""))}`,
      danger: true,
      action: () => p.emptyOne(cache),
    });
  }

  function free(cache: string, where: { place: Place; size: number }[]): void {
    const size = where.reduce((n, w) => n + w.size, 0);
    confirm({
      title: `Free what ${cache} left?`,
      lines: where.filter((w) => w.size).map((w) => ({ name: w.place.title, color: null, size: w.size })),
      note: `${cache} is no longer kept. Other caches stay.`,
      label: `Free ${formatBytes(size)}`,
      danger: false,
      action: async () => {
        for (const w of where) await w.place.emptyOne(cache);
        info = await api.caches();
      },
    });
  }

  function setMode(p: Project, mode: Mode): void {
    if (p.caches === mode) return;
    void run(async () => {
      const spec = projectSpec(await api.project(p.id));
      await api.updateProject(p.id, projectBody({ ...spec, caches: mode }));
      await load();
      void measure();
    });
  }

  // who declares a cache, in a word; an addon's is kept for the agents using it
  function source(c: CacheInfo): string {
    return c.declaredBy
      .map((by) => {
        const [kind, name] = [by.split(":")[0], by.slice(by.indexOf(":") + 1)];
        return kind === "base" ? "Handler" : kind === "user" ? "You" : name;
      })
      .join(", ");
  }
  const sourceHint = (c: CacheInfo) => (c.declaredBy.every((by) => by.startsWith("addon:")) ? "for the agents using this tool" : undefined);

  function toggle(key: string, e: MouseEvent): void {
    // a click on the row's own controls does what they do
    if ((e.target as HTMLElement).closest("button, a, input")) return;
    open[key] = !open[key];
  }
</script>

<!-- a bar split by its parts, each as wide as its share -->
{#snippet bar(parts: { key: string; color: string | null; size: number }[], cls: string, width = 1)}
  <div class="flex gap-0.5 {cls}" style="width:{Math.max(2, width * 100)}%">
    {#each parts.filter((x) => x.size > 0) as x (x.key)}
      <i class="block h-full min-w-[3px] rounded-[2px]" style="{swatch(x.color)};flex:{x.size} 1 0" title="{x.key} · {formatBytes(x.size)}"></i>
    {/each}
  </div>
{/snippet}

<!-- a project's choice, as a chip opening its menu -->
{#snippet modeChip(p: Project, label: string)}
  <Popover label={`${p.name}'s caches`} width="15rem" testid="cache-mode-menu">
    {#snippet trigger(props)}
      <button
        type="button"
        {...props}
        disabled={busy}
        class="inline-flex h-6 items-center gap-1 rounded-md border bg-background px-2 text-xs text-foreground shadow-xs hover:bg-muted aria-expanded:bg-muted"
        data-testid="cache-mode">{label}<ChevronDown class="size-3 text-muted-foreground" /></button
      >
    {/snippet}
    {#snippet children(close)}
      {#each MODES as m (m.value)}
        <button
          type="button"
          class="menu-item"
          style={m.value === "global" ? "color: var(--warn)" : undefined}
          onclick={() => (close(), setMode(p, m.value))}
          data-testid={`cache-mode-${m.value}`}
        >
          {#if m.value === "project"}<Folder />{:else if m.value === "global"}<Database />{:else}<Ban />{/if}
          <span class="flex-1">{m.label}</span>
          {#if (p.caches ?? "project") === m.value}<Check class="text-foreground!" />{/if}
        </button>
      {/each}
      <p class="border-t px-2.5 pt-2 pb-1 text-xs text-muted-foreground">{p.name} · applies to new sessions</p>
    {/snippet}
  </Popover>
{/snippet}

{#snippet sized(n: number)}
  {#if sizes}{n ? formatBytes(n) : "empty"}{:else if measuring}<Skeleton class="inline-block h-3 w-12 align-middle" />{/if}
{/snippet}

{#snippet place(p: Place)}
  {@const size = totalOf(p)}
  {@const isOpen = !!open[p.key]}
  {@const mode = p.project?.caches ?? "project"}
  {@const biggestCache = Math.max(1, ...Object.values(p.caches).map(sizeOf))}
  <li data-testid="cache-folders">
    <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions: the chevron is the keyboard's -->
    <div class="grid cursor-pointer grid-cols-[1.75rem_2.25rem_minmax(0,1fr)_12rem_5rem_auto] items-center gap-3 py-3 pr-4 pl-2 hover:bg-muted/40" onclick={(e) => toggle(p.key, e)}>
      <Button
        variant="ghost"
        size="icon-xs"
        class="text-muted-foreground"
        aria-expanded={isOpen}
        aria-label={`${isOpen ? "Close" : "Open"} ${p.title}`}
        onclick={() => (open[p.key] = !isOpen)}
        data-testid="cache-folders-toggle"><ChevronRight class="transition-transform {isOpen ? 'rotate-90' : ''}" /></Button
      >
      <span class="flex size-9 items-center justify-center rounded-lg bg-muted text-muted-foreground"
        >{#if p.project}<Folder class="size-4" />{:else}<Database class="size-4" />{/if}</span
      >
      <div class="min-w-0 space-y-1">
        <p class="flex items-center gap-1.5">
          <span class="truncate font-medium" data-testid="cache-folders-title">{p.title}</span>
          {#if !p.project}<span title="Shared between projects"><TriangleAlert class="size-3.5 text-warn" aria-label="Shared between projects" /></span>{/if}
        </p>
        <div class="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
          {#if p.project}
            {@render modeChip(p.project, MODES.find((m) => m.value === mode)?.chip ?? mode)}
            {#if mode !== "project"}<span>unused: its files from before</span>{/if}
          {:else}
            {#each onGlobal as g (g.id)}{@render modeChip(g, g.name)}{/each}
            {#each unknownOnGlobal as n (n)}<span>{n}</span>{/each}
            <span>agents outside projects</span>
          {/if}
        </div>
      </div>
      <div class="flex items-center">
        {#if sizes}
          {@render bar(
            [
              ...Object.entries(p.caches).map(([k, f]) => ({ key: cacheName(k), color: colorOf(k), size: sizeOf(f) })),
              ...Object.entries(p.removed).map(([k, f]) => ({ key: k, color: null, size: sizeOf(f) })),
            ],
            `h-2 ${mode === "project" || !p.project ? "" : "opacity-50"}`,
            size / biggest,
          )}
          <span class="sr-only">{formatBytes(size)}</span>
        {:else if measuring}<Skeleton class="h-2 w-32" />{/if}
      </div>
      <span class="text-right text-sm font-medium tabular-nums" data-testid="cache-folders-size">{@render sized(size)}</span>
      <Button variant="outline" size="sm" disabled={busy || !size} onclick={() => emptyAll(p)} data-testid="cache-folders-empty">Empty…</Button>
    </div>
    {#if isOpen}
      <div class="space-y-0.5 border-t bg-muted/30 pt-2 pr-4 pb-3 pl-[5.75rem]">
        {#if !p.project}
          <p class="mb-2 flex items-start gap-2 rounded-lg border border-warn/40 bg-warn/5 px-3 py-2 text-xs text-warn" data-testid="caches-global-warning">
            <TriangleAlert class="mt-px size-3.5 shrink-0" />
            <span>
              Shared: what one project's agent leaves here, another's may run{#if onPath.length}, including the commands {onPath.join(" and ")} put on PATH{/if}.
            </span>
          </p>
        {/if}
        {#each Object.entries(p.caches) as [cache, folder] (cache)}
          {@const c = info?.caches.find((x) => x.name === cache)}
          <div class="grid grid-cols-[minmax(0,1fr)_10rem_5rem_4.5rem] items-center gap-3 py-1" data-testid="cache-folder">
            <div class="flex min-w-0 items-center gap-2" title={c?.about}>
              <i class="size-2.5 shrink-0 rounded-[3px]" style={swatch(colorOf(cache))}></i>
              <span class="shrink-0" data-testid="cache-folder-name">{cacheName(cache)}</span>
              <span class="fact truncate">{c?.target}</span>
            </div>
            <div>
              {#if sizeOf(folder)}<div class="h-1.5 rounded-full opacity-85" style="{swatch(colorOf(cache))};width:{Math.max(3, (sizeOf(folder) / biggestCache) * 100)}%"></div>{/if}
            </div>
            <span class="text-right text-xs text-muted-foreground tabular-nums" data-testid="cache-size">{@render sized(sizeOf(folder))}</span>
            <span class="text-right">
              {#if sizeOf(folder)}
                <Button variant="ghost" size="xs" class="text-muted-foreground" disabled={busy} onclick={() => emptyOne(p, cache)} data-testid="cache-empty">Empty</Button>
              {/if}
            </span>
          </div>
        {/each}
        {#each Object.entries(p.removed) as [cache, folder] (cache)}
          <div class="grid grid-cols-[minmax(0,1fr)_10rem_5rem_4.5rem] items-center gap-3 py-1 text-muted-foreground" data-testid="cache-removed">
            <div class="flex min-w-0 items-center gap-2">
              <i class="size-2.5 shrink-0 rounded-[3px]" style={swatch(null)}></i>
              <span class="shrink-0">{cache}</span>
              <span class="fact truncate">no longer kept</span>
            </div>
            <div>
              {#if sizeOf(folder)}<div class="h-1.5 rounded-full" style="{swatch(null)};width:{Math.max(3, Math.min(100, (sizeOf(folder) / biggestCache) * 100))}%"></div>{/if}
            </div>
            <span class="text-right text-xs tabular-nums">{@render sized(sizeOf(folder))}</span>
            <span class="text-right">
              <Button variant="outline" size="xs" disabled={busy} onclick={() => free(cache, [{ place: p, size: sizeOf(folder) }])} data-testid="cache-free">Free</Button>
            </span>
          </div>
        {/each}
        <p class="flex items-center gap-1.5 pt-2 text-xs text-muted-foreground" title={p.folder}>
          <Folder class="size-3.5 shrink-0" /><span class="fact truncate" data-testid="cache-folders-path">{p.folder}</span>
        </p>
      </div>
    {/if}
  </li>
{/snippet}

<section class="space-y-10" data-testid="caches">
  {#if info}
    <!-- the disk: the total, by cache, and what removed caches left -->
    <div class="overflow-hidden rounded-[14px] border bg-card shadow-panel" data-testid="caches-summary">
      <div class="space-y-4 px-5 pt-5 pb-4">
        <p class="flex items-baseline gap-2.5">
          {#if sizes}
            <span class="text-[1.75rem] leading-none font-semibold tracking-tight tabular-nums" data-testid="caches-total">{formatBytes(total)}</span>
            <span class="text-sm text-muted-foreground">on this computer</span>
          {:else}
            <Skeleton class="h-7 w-32" />
            <span class="inline-flex items-center gap-1.5 text-sm text-muted-foreground"
              >{#if measuring}<RefreshCw class="size-3.5 animate-spin" />Measuring{/if}</span
            >
          {/if}
        </p>
        {#if sizes}
          {@render bar(
            [
              ...byCache.map((c) => ({ key: cacheName(c.key), color: colorOf(c.key), size: c.size })),
              ...leftovers.map((l) => ({ key: l.cache, color: null, size: l.size })),
            ],
            "h-3.5",
          )}
        {:else}
          <Skeleton class="h-3.5 w-full" />
        {/if}
        <ul class="flex flex-wrap gap-x-5 gap-y-1.5 text-[0.8125rem] text-muted-foreground" data-testid="caches-legend">
          {#each byCache as c (c.key)}
            <li class="flex items-center gap-1.5" title={info.caches.find((x) => x.name === c.key)?.about}>
              <i class="size-2.5 rounded-[3px]" style={swatch(colorOf(c.key))}></i>{cacheName(c.key)}
              <span class="font-medium text-foreground tabular-nums">{@render sized(c.size)}</span>
            </li>
          {/each}
        </ul>
      </div>
      {#each leftovers.filter((l) => l.size || !sizes) as l (l.cache)}
        <div class="flex items-center gap-2.5 border-t bg-muted/40 px-5 py-2.5 text-[0.8125rem] text-muted-foreground" data-testid="caches-leftover">
          <i class="size-2.5 rounded-[3px]" style={swatch(null)}></i>
          <span><span class="font-medium text-foreground">{l.cache}</span> · no longer kept</span>
          <span class="flex-1"></span>
          {#if sizes}<span class="tabular-nums">{formatBytes(l.size)} in {l.where.filter((w) => w.size).length === 1 ? "1 folder" : `${l.where.filter((w) => w.size).length} folders`}</span>{/if}
          <Button variant="outline" size="sm" disabled={busy || !sizes} onclick={() => free(l.cache, l.where)} data-testid="caches-free">Free {sizes ? formatBytes(l.size) : ""}</Button>
        </div>
      {/each}
    </div>

    <!-- where: the global folder, each project's own, and the projects without -->
    <ul class="divide-y overflow-hidden rounded-[14px] border bg-card text-sm shadow-panel" data-testid="caches-places">
      {#each places as p (p.key)}{@render place(p)}{/each}
      {#each without as p (p.id)}
        <li class="grid grid-cols-[1.75rem_2.25rem_minmax(0,1fr)_auto] items-center gap-3 py-3 pr-4 pl-2" data-testid="caches-off">
          <span></span>
          <span class="flex size-9 items-center justify-center rounded-lg border text-muted-foreground"><Folder class="size-4" /></span>
          <div class="min-w-0 space-y-1">
            <p class="truncate font-medium">{p.name}</p>
            <div class="text-xs">{@render modeChip(p, "No caches")}</div>
          </div>
          <span class="text-sm text-muted-foreground">—</span>
        </li>
      {/each}
    </ul>
    {#if error && !adding && !asking}<p class="text-sm text-danger" data-testid="caches-error">{error}</p>{/if}

    <!-- what is kept, for every project -->
    <div class="space-y-3">
      <div class="flex items-end justify-between gap-3">
        <div class="space-y-1">
          <h2 class="text-base font-semibold">Kept for every project</h2>
          <p class="text-sm text-muted-foreground">Changes apply to new sessions.</p>
        </div>
        <Button variant="outline" size="sm" onclick={() => ((adding = true), (error = null))} data-testid="cache-new"><Plus />Add a cache</Button>
      </div>
      {#if info.caches.length}
        <ul class="divide-y overflow-hidden rounded-[14px] border bg-card text-sm shadow-panel" data-testid="caches-kept">
          {#each info.caches as c (c.name)}
            <li class="flex items-center gap-3 px-4 py-2.5" data-testid="cache">
              <i class="size-2.5 shrink-0 rounded-[3px]" style={swatch(colorOf(c.name))}></i>
              <div class="flex min-w-0 flex-1 items-baseline gap-2">
                <span class="shrink-0 font-medium" data-testid="cache-name">{nameOf(c.about)}</span>
                <span class="fact shrink-0">{c.target}</span>
                {#if moreOf(c.about)}<span class="truncate text-xs text-muted-foreground" title={moreOf(c.about)}>{moreOf(c.about)}</span>{/if}
              </div>
              {#if c.bin}<span class="shrink-0 rounded-md border px-1.5 py-px text-[0.6875rem] text-muted-foreground" title={`${c.target}/${c.bin}`}>on PATH</span>{/if}
              <span class="shrink-0 text-xs text-muted-foreground" title={sourceHint(c)} data-testid="cache-declared-by">{source(c)}</span>
              {#if c.declaredBy.includes("user")}
                <Button variant="ghost" size="xs" class="text-muted-foreground hover:text-destructive" disabled={busy} onclick={() => remove(c)} data-testid="cache-remove"
                  >Remove</Button
                >
              {/if}
            </li>
          {/each}
        </ul>
      {:else}
        <p class="rounded-[10px] border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
          No caches: every session downloads and builds everything again.
        </p>
      {/if}
    </div>
  {:else if error}
    <p class="text-sm text-danger" data-testid="caches-error">{error}</p>
  {:else}
    <div class="space-y-3">
      <Skeleton class="h-36 w-full rounded-[14px]" role="status" aria-label="Loading" />
      <Skeleton class="h-48 w-full rounded-[14px]" />
    </div>
  {/if}

  <Dialog bind:open={asking} title={ask?.title ?? ""} testid="cache-confirm">
    {#if ask}
      <div class="space-y-3">
        {#if ask.lines.length}
          <ul class="divide-y rounded-lg border" data-testid="cache-confirm-lines">
            {#each ask.lines as l (l.name)}
              <li class="flex items-center gap-2.5 px-3 py-2">
                <i class="size-2.5 shrink-0 rounded-[3px]" style={swatch(l.color)}></i>
                <span class="flex-1 {l.color ? '' : 'text-muted-foreground'}">{l.name}</span>
                <span class="text-muted-foreground tabular-nums">{formatBytes(l.size)}</span>
              </li>
            {/each}
          </ul>
        {/if}
        <p class="text-muted-foreground">{ask.note}</p>
        {#if askError}<p class="text-danger" data-testid="caches-error">{askError}</p>{/if}
        <div class="flex justify-end gap-2 border-t pt-4">
          <Button variant="ghost" size="sm" onclick={() => (asking = false)}>Cancel</Button>
          <Button variant={ask.danger ? "destructive" : "default"} size="sm" disabled={busy} onclick={() => void confirmed()} data-testid="cache-confirm-button"
            >{ask.label}</Button
          >
        </div>
      </div>
    {/if}
  </Dialog>

  <Dialog bind:open={adding} title="Add a cache" description="A folder of the agents' home kept between sessions." testid="cache-dialog">
    <form class="space-y-5" onsubmit={(e) => (e.preventDefault(), add())}>
      <div class="space-y-1.5">
        <Label for="cache-about-input">What it holds</Label>
        <Input id="cache-about-input" placeholder="Gradle's packages" bind:value={about} data-testid="cache-about-input" />
      </div>
      <div class="space-y-1.5">
        <Label for="cache-target-input">Where agents find it</Label>
        <Input id="cache-target-input" class="font-mono text-sm" placeholder="~/.gradle" bind:value={target} data-testid="cache-target-input" />
        <p class="text-xs text-muted-foreground">In their home: <span class="font-mono">~/…</span></p>
      </div>
      <label class="flex items-start gap-2.5">
        <Checkbox class="mt-0.5" bind:checked={general} data-testid="cache-general-input" />
        <span>
          A general folder <span class="block text-xs text-muted-foreground">Any tool writes there (like <span class="font-mono">~/.cache</span>), not one tool's own.</span>
        </span>
      </label>
      {#if error}<p class="text-danger" data-testid="caches-error">{error}</p>{/if}
      <div class="flex justify-end gap-2 border-t pt-4">
        <Button type="button" variant="ghost" size="sm" onclick={() => (adding = false)}>Cancel</Button>
        <Button type="submit" size="sm" disabled={busy || !valid} data-testid="cache-add">Add</Button>
      </div>
    </form>
  </Dialog>
</section>
