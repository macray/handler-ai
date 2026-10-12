<script lang="ts">
  // The caches (D.8), in two parts. What is kept: the toolbox's caches (its toolbox.toml, saved
  // from here), one tool's (~/.cargo) or a general folder any tool writes to (~/.cache), for every
  // project. Where it is kept: the global folders (projects that chose them and agents outside
  // projects) and each project's own, with their sizes, each cache emptied apart or all at once
  // (refused while a session uses it). Sizes are measured after the list shows: it may take a few
  // seconds.
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import { Button } from "$lib/components/ui/button";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import { Input } from "$lib/components/ui/input";
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
    <div class="space-y-1.5">
      <div class="flex items-baseline gap-2">
        <h4 class="text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</h4>
        <span class="text-xs text-muted-foreground">{hint}</span>
      </div>
      <ul class="divide-y rounded-lg border bg-card text-sm" data-testid={`caches-${group}`}>
        {#each caches as c (c.name)}
          <li class="flex items-center justify-between gap-3 px-3.5 py-2.5" data-testid="cache">
            <div class="min-w-0 space-y-0.5">
              <div class="flex items-baseline gap-2">
                <span class="font-medium" data-testid="cache-name">{c.name}</span>
                <span class="font-mono text-xs">{c.target}</span>
              </div>
              {#if c.about}<div class="text-xs text-muted-foreground">{c.about}</div>{/if}
            </div>
            <Button variant="ghost" size="sm" disabled={busy} onclick={() => remove(c)} data-testid="cache-remove">Remove</Button>
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
  <li class="text-sm" data-testid="cache-folders">
    <div class="flex items-center justify-between gap-3 px-3.5 py-2.5">
      <div class="min-w-0 flex-1 space-y-0.5">
        <button
          type="button"
          class="flex items-center gap-2 text-left"
          aria-expanded={!!open[key]}
          onclick={() => (open[key] = !open[key])}
          data-testid="cache-folders-toggle"
        >
          <ChevronRight class="size-4 shrink-0 text-muted-foreground transition-transform {open[key] ? 'rotate-90' : ''}" />
          <span class="font-medium" data-testid="cache-folders-title">{title}</span>
        </button>
        <div class="pl-6 text-xs text-muted-foreground">
          {note}{#if link}{" · "}<a class="underline-offset-2 hover:underline" href={link}>Open project</a>{/if}
        </div>
        <div class="truncate pl-6 font-mono text-xs text-muted-foreground" title={f.folder}>{f.folder}</div>
      </div>
      <div class="flex shrink-0 items-center gap-2">
        <span class="w-16 text-right text-xs font-medium tabular-nums" data-testid="cache-folders-size">{shownSize(sizeIn(f))}</span>
        <Button
          variant="outline"
          size="sm"
          disabled={busy || !sizeIn(f)}
          onclick={() => empty(key === "global" ? "every global cache" : `every cache of ${title}`, sizeIn(f), emptyAll)}
          data-testid="cache-folders-empty">Empty all</Button
        >
      </div>
    </div>
    {#if open[key]}
      <ul class="divide-y border-t bg-muted/30">
        {#each Object.entries(f.caches) as [cache, folder] (cache)}
          <li class="flex items-center justify-between gap-3 py-1.5 pl-10 pr-3.5" data-testid="cache-folder">
            <div class="flex min-w-0 items-baseline gap-2" title={folder}>
              <span class="shrink-0 font-medium" data-testid="cache-folder-name">{cache}</span>
              <span class="truncate font-mono text-xs text-muted-foreground">{targets[cache]}</span>
            </div>
            <div class="flex shrink-0 items-center gap-2">
              <span class="w-16 text-right text-xs tabular-nums text-muted-foreground" data-testid="cache-size">{sizeOf(folder)}</span>
              <Button
                variant="outline"
                size="sm"
                disabled={busy || !sizes?.[folder]}
                onclick={() => empty(`${cache} (${title})`, sizes?.[folder], () => emptyOne(cache))}
                data-testid="cache-empty">Empty</Button
              >
            </div>
          </li>
        {/each}
        {#each Object.entries(f.removed ?? {}) as [cache, folder] (cache)}
          <li class="flex items-center justify-between gap-3 py-1.5 pl-10 pr-3.5 text-muted-foreground" data-testid="cache-removed">
            <div class="flex min-w-0 items-baseline gap-2" title={folder}>
              <span class="shrink-0 font-medium">{cache}</span>
              <span class="truncate text-xs">no longer kept, emptied with “Empty all”</span>
            </div>
            <div class="flex shrink-0 items-center gap-2">
              <span class="w-16 text-right text-xs tabular-nums">{sizeOf(folder)}</span>
              <span class="w-[4.4rem]"></span>
            </div>
          </li>
        {/each}
      </ul>
    {/if}
  </li>
{/snippet}

<section class="space-y-8" data-testid="caches">
  <p class="max-w-2xl text-sm text-muted-foreground">
    What tools download and build is kept between sessions, so the next session does not fetch it again. Below: what is kept, then where.
  </p>

  {#if info}
    <div class="max-w-3xl space-y-3">
      <div>
        <h3 class="text-sm font-medium">What is kept</h3>
        <p class="text-xs text-muted-foreground">For every project that keeps caches, and agents outside projects. Changes apply to new sessions.</p>
      </div>
      {#if info.caches.length}
        {@render kept(
          info.caches.filter((c) => !c.general),
          "Toolchains",
          "one tool's packages and builds",
          "tools",
        )}
        {@render kept(
          info.caches.filter((c) => c.general),
          "General folders",
          "any tool writes there",
          "general",
        )}
      {:else}
        <p class="rounded-lg border bg-card px-3.5 py-2.5 text-sm text-muted-foreground">
          No caches: every session downloads and builds everything again.
        </p>
      {/if}
      <form class="space-y-2 rounded-lg border border-dashed p-3" onsubmit={(e) => (e.preventDefault(), add())}>
        <div class="flex flex-wrap gap-2">
          <Input class="h-8 w-32 text-xs" placeholder="gradle" bind:value={name} aria-label="cache name" data-testid="cache-name-input" />
          <Input class="h-8 w-48 font-mono text-xs" placeholder="~/.gradle" bind:value={target} aria-label="where agents find it" data-testid="cache-target-input" />
          <Input class="h-8 min-w-48 flex-1 text-xs" placeholder="Gradle's packages" bind:value={about} aria-label="what it holds" data-testid="cache-about-input" />
        </div>
        <div class="flex items-center justify-between gap-2">
          <label class="flex items-center gap-2 text-xs">
            <Checkbox bind:checked={general} data-testid="cache-general-input" />
            A general folder any tool writes to
          </label>
          <Button type="submit" variant="outline" size="sm" disabled={busy || !valid} data-testid="cache-add">Add</Button>
        </div>
        <p class="text-xs text-muted-foreground">
          A name (lowercase letters, digits, - and _), where the agents find it in their home (<span class="font-mono">~/…</span>) and what it
          holds. Saved at once.
        </p>
      </form>
    </div>

    <div class="max-w-3xl space-y-3">
      <div class="flex items-baseline justify-between gap-2">
        <div>
          <h3 class="text-sm font-medium">Where it is kept</h3>
          <p class="text-xs text-muted-foreground">On this computer. Each project chooses in its settings: its own, the global ones, or none.</p>
        </div>
        {#if total !== null}<span class="shrink-0 text-xs tabular-nums whitespace-nowrap text-muted-foreground" data-testid="caches-total">{bytes(total)} in all</span>{/if}
      </div>
      <ul class="divide-y rounded-lg border bg-card">
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
      <p class="text-xs text-warn [overflow-wrap:anywhere]" data-testid="caches-global-warning">
        The global caches are a way from one project to another: what one project's agent leaves there, another's may run. The commands
        tools install there (in <span class="font-mono">~/.local/bin</span>, <span class="font-mono">~/.cargo/bin</span>…) are on the PATH
        of every agent using them.
      </p>
      {#if info.off?.length}
        <p class="text-sm text-muted-foreground" data-testid="caches-off">Without caches: {info.off.join(", ")}.</p>
      {/if}
    </div>
  {/if}
  {#if error}<p class="text-sm text-danger" data-testid="caches-error">{error}</p>{/if}
</section>
