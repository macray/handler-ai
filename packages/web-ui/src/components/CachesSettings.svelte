<script lang="ts">
  // The caches (D.8), in two parts. What is kept: the toolbox's caches (its toolbox.toml, saved
  // from here), one tool's (~/.cargo) or a general folder any tool writes to (~/.cache), for every
  // project. Where it is kept: the global folders (projects that chose them and agents outside
  // projects) and each project's own, with their sizes, each cache emptied apart or all at once
  // (refused while a session uses it). Sizes are measured after the list shows: it may take a few
  // seconds. A cache is added in a dialog.
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import Database from "@lucide/svelte/icons/database";
  import FolderOpen from "@lucide/svelte/icons/folder-open";
  import Plus from "@lucide/svelte/icons/plus";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import { Button } from "$lib/components/ui/button";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import Dialog from "./Dialog.svelte";
  import { api } from "../lib/api";
  import type { CacheDeclaration, CacheInfo, CachesInfo, GlobalCachesInfo, ProjectCachesInfo } from "../lib/contracts.gen";
  import { href } from "../lib/router.svelte";

  // where the caches are kept: the global folder or a project's own
  type CacheFolders = GlobalCachesInfo | ProjectCachesInfo;

  let info = $state<CachesInfo | null>(null);
  let sizes = $state<Record<string, number> | null>(null);
  let measuring = $state(false);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let name = $state("");
  let target = $state("~/.");
  let about = $state("");
  let general = $state(false);
  let adding = $state(false); // the dialog open
  // the folders opened to show their caches one by one
  let open = $state<Record<string, boolean>>({});

  function bytes(n: number): string {
    const units = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    while (n >= 1000 && i < units.length - 1) (n /= 1000), i++;
    return `${i === 0 || n >= 100 ? Math.round(n) : n.toFixed(1)} ${units[i]}`;
  }

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

  api.caches().then(
    (i) => ((info = i), void measure()),
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

  const declared = (): Record<string, CacheDeclaration> =>
    Object.fromEntries((info?.caches ?? []).map((c) => [c.name, { target: c.target, about: c.about, general: c.general }]));

  function add(): void {
    void run(async () => {
      info = await api.setCaches({ ...declared(), [name.trim()]: { target: target.trim(), about: about.trim(), general } });
      name = "";
      target = "~/.";
      about = "";
      general = false;
      adding = false;
      void measure();
    });
  }

  function remove(c: CacheInfo): void {
    const left = info ? [info.global, ...(info.own ?? [])].reduce((n, f) => n + (sizes?.[f.caches[c.name] ?? ""] ?? 0), 0) : 0;
    const files = left ? ` Its files (${bytes(left)}) stay, shown as no longer kept until emptied.` : "";
    if (!confirm(`Stop keeping ${c.target} (${c.name}) between sessions? Applies to new sessions.${files}`)) return;
    void run(async () => {
      info = await api.setCaches(Object.fromEntries(Object.entries(declared()).filter(([n]) => n !== c.name)));
    });
  }

  function empty(label: string, size: number | null | undefined, action: () => Promise<void>): void {
    if (!confirm(`Empty ${label}${size ? ` (${bytes(size)})` : ""}? Tools download and build what they need again.`)) return;
    void run(async () => {
      await action();
      await measure();
    });
  }

  const sizeOf = (folder: string) => (sizes ? (sizes[folder] ? bytes(sizes[folder]) : "empty") : measuring ? "…" : "");
  // a folder's size: its caches' and what removed caches left there
  const sizeIn = (f: CacheFolders) =>
    sizes ? [...Object.values(f.caches), ...Object.values(f.removed ?? {})].reduce((n, folder) => n + (sizes?.[folder] ?? 0), 0) : null;
  const shownSize = (n: number | null) => (n === null ? (measuring ? "…" : "") : n ? bytes(n) : "empty");
  const total = $derived(info && sizes ? [info.global, ...(info.own ?? [])].reduce((n, f) => n + (sizeIn(f) ?? 0), 0) : null);
  const usedBy = $derived(
    info?.global.projects?.length ? `${info.global.projects.join(", ")} and agents outside projects` : "agents outside projects",
  );
  const targets = $derived(Object.fromEntries((info?.caches ?? []).map((c) => [c.name, c.target])));
  const valid = $derived(/^[a-z0-9][a-z0-9_-]*$/.test(name.trim()) && /^(\/|~\/)./.test(target.trim()));
</script>

{#snippet kept(caches: CacheInfo[], title: string, hint: string, group: string)}
  {#if caches.length}
    <div class="space-y-2">
      <p class="flex items-baseline gap-2"><span class="section-label">{title}</span><span class="text-xs text-muted-foreground">{hint}</span></p>
      <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel" data-testid={`caches-${group}`}>
        {#each caches as c (c.name)}
          <li class="flex items-center gap-4 px-4 py-3" data-testid="cache">
            <div class="min-w-0 flex-1 space-y-0.5">
              <p class="flex flex-wrap items-baseline gap-x-2">
                <span class="font-medium" data-testid="cache-name">{c.name}</span>
                <span class="fact">{c.target}</span>
              </p>
              {#if c.about}<p class="text-xs text-muted-foreground">{c.about}</p>{/if}
            </div>
            <Button variant="ghost" size="sm" class="text-muted-foreground hover:text-destructive" disabled={busy} onclick={() => remove(c)} data-testid="cache-remove"
              >Remove</Button
            >
          </li>
        {/each}
      </ul>
    </div>
  {/if}
{/snippet}

{#snippet where(
  key: string,
  f: CacheFolders,
  title: string,
  link: string | null,
  note: string,
  emptyAll: () => Promise<void>,
  emptyOne: (cache: string) => Promise<void>,
)}
  <li data-testid="cache-folders">
    <div class="flex items-center gap-4 px-4 py-3.5">
      <span class="hidden size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground sm:flex"
        >{#if key === "global"}<Database class="size-4" />{:else}<FolderOpen class="size-4" />{/if}</span
      >
      <div class="min-w-0 flex-1 space-y-0.5">
        <button
          type="button"
          class="group flex items-center gap-1.5 text-left"
          aria-expanded={!!open[key]}
          onclick={() => (open[key] = !open[key])}
          data-testid="cache-folders-toggle"
        >
          <span class="font-medium group-hover:underline" data-testid="cache-folders-title">{title}</span>
          <ChevronRight class="size-4 shrink-0 text-muted-foreground transition-transform {open[key] ? 'rotate-90' : ''}" />
        </button>
        <p class="text-xs text-muted-foreground">
          {note}{#if link}{" · "}<a class="text-link hover:underline" href={link}>Open the project</a>{/if}
        </p>
        <p class="fact truncate" title={f.folder}>{f.folder}</p>
      </div>
      <span class="w-16 shrink-0 text-right text-sm font-medium tabular-nums" data-testid="cache-folders-size">{shownSize(sizeIn(f))}</span>
      <Button
        variant="outline"
        size="sm"
        disabled={busy || !sizeIn(f)}
        onclick={() => empty(key === "global" ? "every global cache" : `every cache of ${title}`, sizeIn(f), emptyAll)}
        data-testid="cache-folders-empty">Empty all</Button
      >
    </div>
    {#if open[key]}
      <ul class="divide-y border-t bg-muted/30">
        {#each Object.entries(f.caches) as [cache, folder] (cache)}
          <li class="flex items-center gap-3 py-2 pr-4 pl-4 sm:pl-17" data-testid="cache-folder">
            <div class="flex min-w-0 flex-1 items-baseline gap-2" title={folder}>
              <span class="shrink-0" data-testid="cache-folder-name">{cache}</span>
              <span class="fact truncate">{targets[cache]}</span>
            </div>
            <span class="w-16 shrink-0 text-right text-xs text-muted-foreground tabular-nums" data-testid="cache-size">{sizeOf(folder)}</span>
            <Button
              variant="ghost"
              size="sm"
              disabled={busy || !sizes?.[folder]}
              onclick={() => empty(`${cache} (${title})`, sizes?.[folder], () => emptyOne(cache))}
              data-testid="cache-empty">Empty</Button
            >
          </li>
        {/each}
        {#each Object.entries(f.removed ?? {}) as [cache, folder] (cache)}
          <li class="flex items-center gap-3 py-2 pr-4 pl-4 text-muted-foreground sm:pl-17" data-testid="cache-removed">
            <div class="flex min-w-0 flex-1 items-baseline gap-2" title={folder}>
              <span class="shrink-0">{cache}</span>
              <span class="truncate text-xs">no longer kept: emptied with “Empty all”</span>
            </div>
            <span class="w-16 shrink-0 text-right text-xs tabular-nums">{sizeOf(folder)}</span>
            <span class="w-[3.9rem] shrink-0"></span>
          </li>
        {/each}
      </ul>
    {/if}
  </li>
{/snippet}

<section class="space-y-10" data-testid="caches">
  <p class="max-w-2xl text-sm text-muted-foreground">
    What tools download and build is kept between sessions, so the next session does not fetch it again.
  </p>

  {#if info}
    <div class="space-y-4">
      <div class="flex flex-wrap items-end justify-between gap-3">
        <div class="space-y-1">
          <h2 class="text-base font-semibold">What is kept</h2>
          <p class="text-sm text-muted-foreground">For every project that keeps caches, and agents outside projects. Changes apply to new sessions.</p>
        </div>
        <Button variant="outline" size="sm" onclick={() => ((adding = true), (error = null))} data-testid="cache-new"><Plus />Add a cache</Button>
      </div>
      {#if info.caches.length}
        {@render kept(
          info.caches.filter((c) => !c.general),
          "toolchains",
          "one tool's packages and builds",
          "tools",
        )}
        {@render kept(
          info.caches.filter((c) => c.general),
          "general folders",
          "any tool writes there",
          "general",
        )}
      {:else}
        <p class="rounded-[10px] border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
          No caches: every session downloads and builds everything again.
        </p>
      {/if}
    </div>

    <div class="space-y-4">
      <div class="flex flex-wrap items-end justify-between gap-3">
        <div class="space-y-1">
          <h2 class="text-base font-semibold">Where it is kept</h2>
          <p class="text-sm text-muted-foreground">On this computer. Each project chooses in its settings: its own, the global ones, or none.</p>
        </div>
        {#if total !== null}<span class="fact shrink-0 whitespace-nowrap" data-testid="caches-total">{bytes(total)} in all</span>{/if}
      </div>
      <p class="flex items-start gap-2.5 rounded-[10px] border border-warn/40 bg-warn/5 px-4 py-3 text-sm text-warn [overflow-wrap:anywhere]" data-testid="caches-global-warning">
        <TriangleAlert class="mt-0.5 size-4 shrink-0" />
        <span>
          The global caches are a way from one project to another: what one project's agent leaves there, another's may run. The commands tools
          install there (in <span class="font-mono text-xs">~/.local/bin</span>, <span class="font-mono text-xs">~/.cargo/bin</span>…) are on the
          PATH of every agent using them.
        </span>
      </p>
      <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
        {@render where(
          "global",
          info.global,
          "Global",
          null,
          `Used by ${usedBy}`,
          () => api.emptyGlobalCaches(),
          (cache) => api.emptyCache(cache),
        )}
        {#each info.own ?? [] as p (p.projectId)}
          {@render where(
            p.projectId,
            p,
            p.name,
            href({ view: "project", id: p.projectId }),
            "This project's own, removed with it",
            () => api.emptyProjectCaches(p.projectId),
            (cache) => api.emptyProjectCache(p.projectId, cache),
          )}
        {/each}
      </ul>
      {#if info.off?.length}
        <p class="fact" data-testid="caches-off">without caches: {info.off.join(", ")}</p>
      {/if}
    </div>
  {/if}
  {#if error && !adding}<p class="text-sm text-danger" data-testid="caches-error">{error}</p>{/if}

  <Dialog bind:open={adding} title="Add a cache" description="A folder of the agents' home kept between sessions." testid="cache-dialog">
    <form class="space-y-5" onsubmit={(e) => (e.preventDefault(), add())}>
      <div class="grid gap-4 sm:grid-cols-2">
        <div class="space-y-1.5">
          <Label for="cache-name-input">Name</Label>
          <Input id="cache-name-input" placeholder="gradle" bind:value={name} data-testid="cache-name-input" />
          <p class="text-xs text-muted-foreground">Lowercase letters, digits, - and _.</p>
        </div>
        <div class="space-y-1.5">
          <Label for="cache-target-input">Where agents find it</Label>
          <Input id="cache-target-input" class="font-mono text-sm" placeholder="~/.gradle" bind:value={target} data-testid="cache-target-input" />
          <p class="text-xs text-muted-foreground">In their home: <span class="font-mono">~/…</span></p>
        </div>
      </div>
      <div class="space-y-1.5">
        <Label for="cache-about-input">What it holds</Label>
        <Input id="cache-about-input" placeholder="Gradle's packages" bind:value={about} data-testid="cache-about-input" />
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
