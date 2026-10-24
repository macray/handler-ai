<script lang="ts">
  // Harness and addon images (contracts D.4, G.4): whether this computer can run agents (A.8: each
  // problem with its fix), automatic updates, the network filter (handler's own image: the egress proxy,
  // never called so here, docs/dev/ui-ux.md), what each image installed, build or update one (from
  // the files on disk: latest release, checked before agents switch to it), the shared toolbox
  // (advanced: its Containerfile edited in place), and the running build's progress and log, shown
  // above the lists (where a Build click is seen). The log is shown as text, never as markup.
  import When from "./When.svelte";
  import Box from "@lucide/svelte/icons/box";
  import Check from "@lucide/svelte/icons/check";
  import Pencil from "@lucide/svelte/icons/pencil";
  import Shield from "@lucide/svelte/icons/shield";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import RefreshCw from "@lucide/svelte/icons/refresh-cw";
  import X from "@lucide/svelte/icons/x";
  import { Button } from "$lib/components/ui/button";
  import * as NativeSelect from "$lib/components/ui/native-select";
  import { Skeleton } from "$lib/components/ui/skeleton";
  import { api } from "../lib/api";
  import type { AddonInfo, Build, HarnessInfo, ImageUpdates, NetworkFilterInfo, ToolboxInfo } from "../lib/contracts.gen";
  import { runtime } from "../lib/runtime.svelte";
  import StatusBadge from "./StatusBadge.svelte";
  import ToolboxEditor from "./ToolboxEditor.svelte";

  let harnesses = $state<HarnessInfo[]>([]);
  let addons = $state<AddonInfo[]>([]); // those with an image (the others have nothing to build)
  let toolbox = $state<ToolboxInfo | null>(null);
  let networkFilter = $state<NetworkFilterInfo | null>(null);
  let loaded = $state(false); // the first answer came (listing images inspects each one: slow)
  let build = $state<Build | null>(null); // the build shown in the panel
  let log = $state("");
  let error = $state<string | null>(null);
  let busy = $state(false); // a request of ours is in flight
  let logElement = $state<HTMLPreElement | null>(null);
  let offset = 0;
  let editing = $state(false); // the toolbox Containerfile editor is open
  const host = $derived(runtime.check); // what the container runtime finds missing (A.8)
  let updates = $state<ImageUpdates | null>(null); // automatic updates (D.4)

  const running = $derived(build?.state === "running");

  async function load(): Promise<void> {
    try {
      let all: AddonInfo[];
      [harnesses, toolbox, networkFilter, all, updates] = await Promise.all([
        api.harnesses(),
        api.toolbox(),
        api.networkFilter(),
        api.addons(),
        api.imageUpdates(),
      ]);
      addons = all.filter((a) => a.image && !a.error);
    } catch (e) {
      error = (e as Error).message;
    } finally {
      loaded = true;
    }
  }

  $effect(() => {
    void load();
    void runtime.refresh();
    // after a reload: follow a build still running, or show how the last one ended (badly)
    api.builds().then(
      (list) => {
        const last = list[0];
        if (last && (last.state === "running" || last.state === "failed" || last.warnings?.length)) show(last);
      },
      (e: Error) => (error = e.message),
    );
  });

  function show(b: Build): void {
    build = b;
    log = "";
    offset = 0;
    void poll();
  }

  async function poll(): Promise<void> {
    if (!build) return;
    const id = build.id;
    try {
      for (;;) {
        const chunk = await api.buildLog(id, offset);
        if (build?.id !== id) return; // another build is shown now
        offset = chunk.nextOffset;
        if (chunk.text) appendLog(chunk.text);
        if (chunk.complete || !chunk.text) break;
      }
      const wasRunning = build.state === "running";
      build = await api.build(id);
      if (wasRunning && build.state !== "running") await load(); // versions changed (or not)
    } catch (e) {
      error = (e as Error).message;
    }
  }

  $effect(() => {
    if (!running) return;
    const timer = setInterval(() => void poll(), 1000);
    return () => clearInterval(timer);
  });

  function appendLog(text: string): void {
    const el = logElement;
    const atBottom = !el || el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    log += text;
    if (atBottom) requestAnimationFrame(() => el?.scrollTo({ top: el.scrollHeight }));
  }

  async function act(action: () => Promise<void>): Promise<void> {
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

  function rebuild(target: string): Promise<void> {
    if (
      target === "toolbox" &&
      !confirm(
        "Rebuild the toolbox? It updates the system packages (a large download), then rebuilds and checks every agent program and tool image on top of it.",
      )
    )
      return Promise.resolve();
    return act(async () => show(await api.rebuild(target)));
  }

  function setSchedule(schedule: string): Promise<void> {
    return act(async () => {
      updates = await api.setImageUpdates(schedule as ImageUpdates["schedule"]);
    });
  }

  function updateNow(): Promise<void> {
    return act(async () => {
      updates = await api.runImageUpdates();
      const list = await api.builds();
      if (list[0]?.state === "running") show(list[0]);
    });
  }

  function cancel(): Promise<void> {
    return act(async () => {
      if (build) build = await api.cancelBuild(build.id);
      await poll();
    });
  }
</script>

<!-- an image's line: its name, whether it is built, what it is, and its Build / Update -->
{#snippet image(o: {
  testid: string;
  versionTestid: string;
  icon: typeof Box;
  name: string;
  ref: string;
  present: boolean | undefined;
  version?: string | null;
  builtAt?: string | null;
  about?: string;
  target: string;
})}
  {@const Icon = o.icon}
  <li class="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3.5" data-testid={o.testid}>
    <span class="hidden size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground sm:flex"><Icon class="size-4" /></span>
    <div class="min-w-0 flex-1 basis-60 space-y-0.5">
      <p class="flex flex-wrap items-center gap-2">
        <span class="font-medium">{o.name}</span>
        <span data-testid={o.versionTestid}>
          {#if !o.present}
            <span class="inline-flex items-center gap-1 rounded-md bg-warn/10 px-1.5 py-0.5 text-xs text-warn"><TriangleAlert class="size-3" />not built yet</span>
          {:else}
            <span class="rounded-md bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">{o.version ?? "unknown"}</span>
          {/if}
        </span>
      </p>
      {#if o.about}<p class="text-xs text-muted-foreground">{o.about}</p>{/if}
      <p class="fact truncate">{o.ref}{#if o.builtAt}&ensp;·&ensp;built <When at={o.builtAt} />{/if}</p>
    </div>
    <Button size="sm" variant="outline" class="ml-auto" disabled={busy || running} onclick={() => rebuild(o.target)}>
      <RefreshCw />{o.present ? "Update" : "Build"}
    </Button>
  </li>
{/snippet}

{#snippet heading(title: string, text: string)}
  <div class="space-y-1">
    <h2 class="text-base font-semibold">{title}</h2>
    <p class="max-w-2xl text-sm text-muted-foreground">{text}</p>
  </div>
{/snippet}

<section class="space-y-10" data-testid="harness-images">
  <div class="space-y-4">
    <p class="max-w-2xl text-sm text-muted-foreground">
      The container images agents run in: one per agent program and addon, each built on the shared toolbox, and the network filter between agents
      and the internet. Handler builds them when needed and keeps them up to date; running sessions keep the image they started with.
    </p>
    {#if error}<p class="text-sm text-danger">{error}</p>{/if}
    {#if runtime.error}<p class="text-sm text-danger">{runtime.error}</p>{/if}
    {#if host && host.items.some((i) => !i.ok)}
      <div class="space-y-3 rounded-[10px] border px-4 py-3.5 text-sm {host.ok ? 'border-warn/40 bg-warn/5' : 'border-danger/40 bg-danger/5'}" data-testid="runtime-check">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <p class="flex items-center gap-2 font-medium {host.ok ? 'text-warn' : 'text-danger'}">
            <TriangleAlert class="size-4" />{host.ok ? "Some agents need more from this computer" : "Agents can't run on this computer yet"}
            <span class="fact">{host.runtime}</span>
          </p>
          <Button size="sm" variant="outline" onclick={() => runtime.refresh()} data-testid="runtime-recheck"><RefreshCw />Check again</Button>
        </div>
        <ul class="space-y-1">
          {#each host.items.filter((i) => !i.ok) as item (item.name)}
            <li class={item.required ? "text-danger" : "text-muted-foreground"}>
              <span class="font-medium">{item.name}</span>{item.required ? "" : " (some sandboxes only)"}: <span class="font-mono text-xs">{item.detail}</span>
            </li>
          {/each}
        </ul>
        <p class="text-xs text-muted-foreground">Fix what is listed, then check again (<code>handler setup</code> checks the same).</p>
      </div>
    {:else if host}
      <p class="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm" data-testid="runtime-check">
        <Check class="size-4 text-ok" />Agents can run on this computer <span class="fact whitespace-nowrap">{host.runtime}</span>
      </p>
    {/if}
  </div>

  {#if updates}
    <div class="space-y-3 rounded-[10px] border bg-card px-4 py-4 text-sm shadow-panel" data-testid="image-updates">
      <div class="flex flex-wrap items-center gap-x-3 gap-y-2">
        <label for="image-updates-schedule" class="font-medium">Automatic updates</label>
        <NativeSelect.Root id="image-updates-schedule" class="w-32" value={updates.schedule} disabled={busy} onchange={(e) => setSchedule(e.currentTarget.value)}>
          <NativeSelect.Option value="weekly">Weekly</NativeSelect.Option>
          <NativeSelect.Option value="daily">Daily</NativeSelect.Option>
          <NativeSelect.Option value="off">Off</NativeSelect.Option>
        </NativeSelect.Root>
        <span class="fact">
          {#if updates.running}updating…{:else}last <When at={updates.lastRun} />{#if updates.nextRun}&ensp;·&ensp;next <When at={updates.nextRun} />{/if}{/if}
        </span>
        <Button size="sm" variant="outline" class="ml-auto" disabled={busy || running || updates.running} onclick={updateNow} data-testid="update-now">
          <RefreshCw />Update now
        </Button>
      </div>
      {#if updates.lastFailed?.length}
        <p class="text-danger" data-testid="updates-failed">Failed last time: {updates.lastFailed?.join(", ")}</p>
      {/if}
      <p class="text-xs text-muted-foreground">
        New releases of the agent programs and addons Handler has built, and the network filter's security updates; each is used only once it passes a
        check. The shared toolbox changes only with <span class="font-medium">Rebuild everything</span>.
      </p>
    </div>
  {/if}

  {#if build}
    <div class="enter space-y-3 rounded-[10px] border bg-card p-4 shadow-panel" data-testid="build-panel">
      <div class="flex flex-wrap items-center gap-2 text-sm">
        <span class="font-medium">Building {build.target}</span>
        <span data-testid="build-state"><StatusBadge status={build.state} /></span>
        {#if running && build.stage}
          <span class="fact">{build.stage}{#if build.step && build.steps}: step {build.step} of {build.steps}{/if}</span>
        {/if}
        <div class="ml-auto flex gap-1">
          {#if running}
            <Button size="sm" variant="outline" disabled={busy} onclick={cancel}>Cancel</Button>
          {:else}
            <Button size="icon-sm" variant="ghost" aria-label="close" onclick={() => (build = null)}><X /></Button>
          {/if}
        </div>
      </div>
      {#if running && build.step && build.steps}
        <div class="h-1 overflow-hidden rounded bg-muted" role="progressbar" aria-valuenow={build.step} aria-valuemax={build.steps}>
          <div class="h-full bg-primary transition-all" style:width={`${(100 * build.step) / build.steps}%`}></div>
        </div>
      {/if}
      {#if build.error}<p class="text-sm text-danger" data-testid="build-error">{build.error}</p>{/if}
      {#each build.warnings ?? [] as warning (warning)}
        <p class="flex items-start gap-1.5 text-sm text-warn" data-testid="build-warning"><TriangleAlert class="mt-0.5 size-3.5 shrink-0" />{warning}</p>
      {/each}
      {#each Object.entries(build.versions ?? {}) as [name, version] (name)}
        <p class="fact">{name}: {version}</p>
      {/each}
      <pre bind:this={logElement} class="term-surface max-h-96 overflow-auto rounded-md border p-3 font-mono text-xs whitespace-pre-wrap" data-testid="build-log">{log}</pre>
    </div>
  {/if}

  {#if networkFilter}
    <div class="space-y-4">
      {@render heading("Built into Handler", "The network filter: where agents connect, checked, and your secrets added to their requests.")}
      <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
        {@render image({
          testid: "network-filter-row",
          versionTestid: "network-filter-state",
          icon: Shield,
          name: "Network filter",
          ref: networkFilter.image,
          present: networkFilter.imagePresent,
          version: "built",
          builtAt: networkFilter.builtAt,
          about: networkFilter.imagePresent ? undefined : "Agents with a network allow-list or a secret can't start without it.",
          target: "network-filter",
        })}
      </ul>
    </div>
  {/if}

  <div class="space-y-4">
    {@render heading("Agent programs", "One image per agent program, with the program itself.")}
    {#if !loaded}
      <div class="space-y-2">{#each { length: 3 }, i (i)}<Skeleton class="h-14 w-full rounded-[10px]" role="status" aria-label="Loading" data-testid="loading" />{/each}</div>
    {:else}
      <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
        {#each harnesses as h (h.name)}
          {@render image({
            testid: "harness-image-row",
            versionTestid: "harness-version",
            icon: Box,
            name: h.product,
            ref: h.image,
            present: h.imagePresent,
            version: h.version,
            builtAt: h.builtAt,
            target: h.name,
          })}
        {/each}
      </ul>
    {/if}
  </div>

  {#if addons.length}
    <div class="space-y-4">
      {@render heading("Addons", "The addons that bring programs of their own.")}
      <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
        {#each addons as a (a.name)}
          {@render image({
            testid: "addon-image-row",
            versionTestid: "addon-version",
            icon: Box,
            name: a.name,
            ref: a.image ?? "",
            present: a.imagePresent,
            version: a.version,
            builtAt: a.builtAt,
            target: `addon:${a.name}`,
          })}
        {/each}
      </ul>
    </div>
  {/if}

  {#if toolbox}
    <div class="space-y-4">
      {@render heading("Shared base (advanced)", "The toolbox: the system and tools every image starts from. Yours to change; rebuilding it rebuilds and checks every image.")}
      <div class="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-[10px] border bg-card px-4 py-3.5 text-sm shadow-panel">
        <span class="hidden size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground sm:flex"><Box class="size-4" /></span>
        <div class="min-w-0 flex-1 basis-60 space-y-0.5">
          <p class="flex flex-wrap items-center gap-2">
            <span class="font-medium">toolbox</span>
            {#if !toolbox.imagePresent}
              <span class="inline-flex items-center gap-1 rounded-md bg-warn/10 px-1.5 py-0.5 text-xs text-warn"><TriangleAlert class="size-3" />not built yet</span>
            {/if}
          </p>
          <p class="fact truncate">{toolbox.image}{#if toolbox.builtAt}&ensp;·&ensp;built <When at={toolbox.builtAt} />{/if}</p>
          <p class="fact truncate" data-testid="toolbox-directory">yours: {toolbox.directory}</p>
        </div>
        <div class="ml-auto flex gap-1.5">
          <Button size="sm" variant="ghost" disabled={editing} onclick={() => (editing = true)} data-testid="toolbox-edit"><Pencil />Edit its Containerfile</Button>
          <Button size="sm" variant="outline" disabled={busy || running} onclick={() => rebuild("toolbox")}><RefreshCw />Rebuild everything</Button>
        </div>
      </div>
      {#if editing}
        <ToolboxEditor directory={toolbox.directory} onclose={() => (editing = false)} onsaved={() => void load()} />
      {/if}
    </div>
  {/if}
</section>
