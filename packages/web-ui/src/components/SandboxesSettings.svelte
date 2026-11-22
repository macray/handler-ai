<script lang="ts">
  // Settings → Sandboxes (D.2, D.4, A.8): where agents run (the runtime in use and its version,
  // Ready, Change: the runtimes installed, each with Handler's check of this computer, amber when
  // switching would give less; what switching needs), a problem on this computer one row with its
  // fix, no memory and CPU limits a neutral fact with its Why folded (E1); Updates (automatic,
  // Update now, each program's version and when it was built; one whose
  // update failed its check is held back, See why opens that build); Under the hood, folded: the
  // images (the network filter, the agent programs, the tools that bring programs; each built or
  // updated here) and the toolbox (ToolboxSettings). A build's progress and log show above the
  // updates while it runs or after it failed; the log is shown as text, never as markup. One
  // started from here (an image's Build or Update, the toolbox's, Update now, See why) is brought
  // into view: those buttons are below it, the panel would open out of sight.
  import When from "./When.svelte";
  import Box from "@lucide/svelte/icons/box";
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import Info from "@lucide/svelte/icons/info";
  import Shield from "@lucide/svelte/icons/shield";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import RefreshCw from "@lucide/svelte/icons/refresh-cw";
  import X from "@lucide/svelte/icons/x";
  import { Button } from "$lib/components/ui/button";
  import * as NativeSelect from "$lib/components/ui/native-select";
  import { Skeleton } from "$lib/components/ui/skeleton";
  import { tick } from "svelte";
  import { api } from "../lib/api";
  import type { AddonInfo, Build, HarnessImage, HarnessInfo, ImageUpdates, NetworkFilterInfo, SandboxRuntime, ToolboxInfo } from "../lib/contracts.gen";
  import { runtime } from "../lib/runtime.svelte";
  import Popover from "./Popover.svelte";
  import StatusBadge from "./StatusBadge.svelte";
  import ToolboxSettings from "./ToolboxSettings.svelte";

  let harnesses = $state<HarnessInfo[]>([]);
  let images = $state<HarnessImage[]>([]); // the harnesses' images (D.4)
  // each harness with its image's state
  const programs = $derived(harnesses.map((h) => ({ ...h, ...images.find((i) => i.name === h.name) })));
  let addons = $state<AddonInfo[]>([]); // those with an image (the others have nothing to build)
  let toolbox = $state<ToolboxInfo | null>(null);
  let networkFilter = $state<NetworkFilterInfo | null>(null);
  let loaded = $state(false); // the first answer came (listing images inspects each one: slow)
  let build = $state<Build | null>(null); // the build shown in the panel
  let log = $state("");
  let error = $state<string | null>(null);
  let busy = $state(false); // a request of ours is in flight
  let logElement = $state<HTMLPreElement | null>(null);
  let panelElement = $state<HTMLDivElement | null>(null);
  let offset = 0;
  const host = $derived(runtime.check); // what the container runtime finds missing (A.8)
  let updates = $state<ImageUpdates | null>(null); // automatic updates (D.4)
  let runtimes = $state<SandboxRuntime[]>([]); // the sandbox runtimes installed (D.2), each with its check
  let builds = $state<Build[]>([]); // the builds kept, newest first: why an update was held back
  let changeOpen = $state(false);

  const running = $derived(build?.state === "running");

  // Loads may overlap (a change made here, a build that ended) and end in any order: only the
  // latest one shows, never an older one that ends after it with what was before.
  let latestLoad = 0;

  async function load(): Promise<void> {
    const mine = ++latestLoad;
    try {
      // each installed runtime's own check may take a while: apart, not holding the rest
      api.runtimes().then(
        (list) => {
          if (mine === latestLoad) runtimes = list;
        },
        (e: Error) => (error = e.message),
      );
      const results = await Promise.all([
        api.harnesses(),
        api.harnessImages(),
        api.toolbox(),
        api.networkFilter(),
        api.addons(),
        api.imageUpdates(),
        api.builds(),
      ]);
      if (mine !== latestLoad) return;
      let all: AddonInfo[];
      [harnesses, images, toolbox, networkFilter, all, updates, builds] = results;
      addons = all.filter((a) => a.image && !a.error);
    } catch (e) {
      error = (e as Error).message;
    } finally {
      loaded = true;
    }
  }

  async function chooseRuntime(name: string): Promise<void> {
    busy = true;
    await runtime.choose(name);
    busy = false;
    await load(); // its images: built or not, there
  }

  $effect(() => {
    void load();
    void runtime.refresh();
    // after a reload: follow a build still running, or show how the last one ended (badly)
    api.builds().then(
      (list) => {
        builds = list;
        const last = list[0];
        if (last && (last.state === "running" || last.state === "failed")) show(last);
      },
      (e: Error) => (error = e.message),
    );
  });

  // `reveal`: asked from here, the panel scrolled into view (only if out of it) and focused
  function show(b: Build, reveal = false): void {
    build = b;
    log = "";
    offset = 0;
    void poll();
    if (reveal) void tick().then(() => {
      const still = !matchMedia("(prefers-reduced-motion: reduce)").matches;
      panelElement?.scrollIntoView({ block: "nearest", behavior: still ? "smooth" : "auto" });
      panelElement?.focus({ preventScroll: true });
    });
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

  function rebuild(target: string, update = false): Promise<void> {
    return act(async () => show(await api.rebuild(target, update), true));
  }

  function setSchedule(schedule: string): Promise<void> {
    return act(async () => {
      updates = await api.setImageUpdates(schedule as ImageUpdates["schedule"]);
    });
  }

  function updateNow(): Promise<void> {
    return act(async () => {
      updates = await api.runImageUpdates();
      const list = (builds = await api.builds());
      if (list[0]?.state === "running") show(list[0], true);
    });
  }

  // the version a program's image installed, in short: "2.1.280"
  const short = (v: string | null | undefined) => v?.match(/\d+\.\d+(\.\d+)?/)?.[0] ?? v ?? "";
  const current = $derived(runtimes.find((r) => r.current));
  const others = $derived(runtimes.filter((r) => !r.current));
  // what another runtime would give less than this one, in words
  function consequence(r: SandboxRuntime): string | null {
    if (!r.check) return "Handler cannot check it here";
    if (!r.check.ok) return `cannot run here: ${r.check.items.find((i) => i.required && !i.ok)?.name ?? "see its check"} missing`;
    const have = host?.supports?.abilities ?? [];
    const lacks = have.filter((a) => !r.check?.supports?.abilities.includes(a));
    const WORDS: Record<string, string> = { nested: "containers", privileged: "privileged", display: "window" };
    return lacks.length ? `no ${lacks.map((a) => WORDS[a] ?? a).join(", ")} sandboxes` : null;
  }
  // what this computer lacks: memory and CPU limits are a fact of the machine (E1: neutral, its
  // why folded), the rest a problem with its fix
  const LIMITS = "memory and CPU limits";
  const noLimits = $derived(host?.items.find((i) => i.name === LIMITS && !i.ok && !i.required));
  const problems = $derived(host?.items.filter((i) => !i.ok && i !== noLimits) ?? []);
  let limitsWhy = $state(false);
  // what an update covers: the network filter and the images already built (D.4)
  type Update = { target: string; name: string; version: string; at?: string | null };
  const updated = $derived<Update[]>([
    ...programs.filter((h) => h.imagePresent).map((h) => ({ target: h.name, name: h.product, version: short(h.version), at: h.builtAt })),
    ...(networkFilter?.imagePresent ? [{ target: "network-filter", name: "Network filter", version: "", at: networkFilter.builtAt }] : []),
    ...addons.filter((a) => a.imagePresent).map((a) => ({ target: `addon:${a.name}`, name: a.name, version: a.version ?? "", at: a.builtAt })),
  ]);
  const heldBack = (target: string) => updates?.lastFailed?.includes(target) ?? false;
  const failedBuild = (target: string) => builds.find((b) => b.state === "failed" && (b.target === target || b.harnesses?.includes(target) || b.addons?.includes(target.replace(/^addon:/, ""))));
  const notBuilt = $derived(programs.filter((h) => !h.imagePresent).length + addons.filter((a) => !a.imagePresent).length + (networkFilter && !networkFilter.imagePresent ? 1 : 0) + (toolbox && !toolbox.imagePresent ? 1 : 0));
  const imageCount = $derived(programs.filter((h) => h.imagePresent).length + addons.filter((a) => a.imagePresent).length + (networkFilter?.imagePresent ? 1 : 0));

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

{#snippet group(title: string)}
  <h3 class="text-sm font-medium text-muted-foreground">{title}</h3>
{/snippet}

<section class="space-y-8" data-testid="sandboxes">
  {#if error}<p class="text-sm text-danger">{error}</p>{/if}
  {#if runtime.error}<p class="text-sm text-danger">{runtime.error}</p>{/if}

  <!-- where agents run, and what this computer lacks -->
  <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel" data-testid="runtime-check">
    <li class="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3.5">
      <span class="flex w-36 shrink-0 items-center gap-2 font-medium"><Box class="size-4 text-muted-foreground" />Runs in</span>
      <span class="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1" title={host?.supports ? `Each sandbox is ${host.supports.isolation}.` : undefined} data-testid="runtime-isolation">
        <span class="font-medium">{host?.runtime ?? current?.name ?? "…"}</span>
        {#if host}
          {#if !host.ok}
            <span class="flex items-center gap-1.5 text-xs text-danger"><span class="size-2 rounded-full bg-danger"></span>Agents can't run here yet</span>
          {:else}
            <span class="flex items-center gap-1.5 text-xs text-ok"><span class="size-2 rounded-full bg-ok"></span>Ready</span>
          {/if}
        {/if}
      </span>
      {#if others.length}
        <Popover bind:open={changeOpen} label="Runtimes installed here" width="24rem" align="end" testid="runtime-choice">
          {#snippet trigger(props)}
            <Button size="sm" variant="ghost" {...props} disabled={busy} data-testid="runtime-change">Change<ChevronDown /></Button>
          {/snippet}
          {#snippet children(close)}
            <p class="px-2.5 pt-2 pb-1 text-xs font-semibold text-muted-foreground">Installed here</p>
            {#each runtimes as r (r.name)}
              {@const why = r.current ? null : consequence(r)}
              <button
                type="button"
                class="flex w-full items-start gap-2.5 rounded-md px-2.5 py-2 text-left text-sm hover:bg-muted disabled:cursor-default {r.current ? 'bg-muted' : 'disabled:opacity-60'}"
                title={r.check?.items.filter((i) => !i.ok).map((i) => `${i.name}: ${i.detail}`).join("\n") || undefined}
                disabled={busy || r.current || (r.check ? !r.check.ok : false)}
                onclick={() => (close(), void chooseRuntime(r.name))}
                data-testid="runtime-option"
              >
                <span class="mt-0.5 size-3.5 shrink-0 rounded-full {r.current ? 'border-[4.5px] border-primary' : 'border-[1.5px] border-muted-foreground'}"></span>
                <span class="min-w-0">
                  <span class="block font-medium">{r.check?.runtime ?? r.name}</span>
                  {#if why}<span class="flex items-center gap-1 text-xs text-warn"><TriangleAlert class="size-3 shrink-0" />{why}</span>{/if}
                </span>
              </button>
            {/each}
            <p class="mt-1 flex items-start gap-2 border-t px-2.5 pt-2 pb-1 text-xs text-muted-foreground">
              <Info class="mt-0.5 size-3.5 shrink-0" />Stop what runs to switch; each runtime has its own images, built again after a switch.
            </p>
          {/snippet}
        </Popover>
      {/if}
    </li>
    {#if noLimits}
      <li class="px-4 py-3.5" data-testid="runtime-limits">
        <div class="flex flex-wrap items-center gap-x-4 gap-y-2">
          <span class="w-36 shrink-0 font-medium">Memory and CPU limits</span>
          <span class="min-w-0 flex-1 text-muted-foreground"
            >Not available on this computer ·
            <button type="button" class="text-link hover:underline" aria-expanded={limitsWhy} onclick={() => (limitsWhy = !limitsWhy)} data-testid="runtime-limits-why">Why</button></span
          >
        </div>
        {#if limitsWhy}
          <div class="mt-3 flex flex-wrap items-start gap-x-4 gap-y-2 rounded-md bg-muted/40 p-3 text-xs text-muted-foreground" data-testid="runtime-limits-detail">
            <p class="min-w-0 flex-1 basis-64 space-y-1">
              <span class="block">Agents still run sandboxed; one could use all of this computer's memory.</span>
              <span class="block font-mono [overflow-wrap:anywhere]">{noLimits.detail}</span>
            </p>
            <Button size="sm" variant="ghost" onclick={() => runtime.refresh()} data-testid="runtime-recheck"><RefreshCw />Check again</Button>
          </div>
        {/if}
      </li>
    {/if}
    {#each problems as item (item.name)}
      <li class="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3.5 {item.required ? 'bg-danger/5' : 'bg-warn/5'}" data-testid="runtime-problem">
        <span class="flex w-36 shrink-0 items-center gap-2 font-medium {item.required ? 'text-danger' : 'text-warn'}"><TriangleAlert class="size-4 shrink-0" />{item.name}</span>
        <span class="min-w-0 flex-1 basis-64 font-mono text-xs [overflow-wrap:anywhere]">{item.detail}</span>
        <Button size="sm" variant="ghost" onclick={() => runtime.refresh()} data-testid="runtime-recheck"><RefreshCw />Check again</Button>
      </li>
    {/each}
  </ul>

  {#if build}
    <div
      bind:this={panelElement}
      tabindex="-1"
      role="region"
      aria-label="Build of {build.target}"
      class="enter scroll-mt-4 space-y-3 rounded-[10px] border bg-card p-4 shadow-panel outline-none"
      data-testid="build-panel"
    >
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
      {#each Object.entries(build.versions ?? {}) as [name, version] (name)}
        <p class="fact">{name}: {version}</p>
      {/each}
      <pre bind:this={logElement} class="term-surface max-h-96 overflow-auto rounded-md border p-3 font-mono text-xs whitespace-pre-wrap" data-testid="build-log">{log}</pre>
    </div>
  {/if}


  <!-- updates: what is built, its version and when; one held back after failing its check -->
  {#if updates}
    <div class="space-y-3" data-testid="image-updates">
      <div class="flex flex-wrap items-center gap-2">
        <h2 class="mr-auto text-sm font-semibold">Updates</h2>
        <label class="flex items-center gap-1.5 text-sm text-muted-foreground" for="image-updates-schedule">Automatic:
          <NativeSelect.Root id="image-updates-schedule" class="w-28" value={updates.schedule} disabled={busy} onchange={(e) => setSchedule(e.currentTarget.value)}>
            <NativeSelect.Option value="weekly">weekly</NativeSelect.Option>
            <NativeSelect.Option value="daily">daily</NativeSelect.Option>
            <NativeSelect.Option value="off">off</NativeSelect.Option>
          </NativeSelect.Root>
        </label>
        <Button size="sm" variant="outline" disabled={busy || running || updates.running} onclick={updateNow} data-testid="update-now"><RefreshCw />{updates.running ? "Updating…" : "Update now"}</Button>
      </div>
      {#if updated.length}
        <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
          {#each updated as u (u.target)}
            {@const held = heldBack(u.target)}
            {@const failed = held ? failedBuild(u.target) : undefined}
            <li class="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 {held ? 'bg-warn/5' : ''}" data-testid="update-row">
              <span class="w-36 shrink-0 font-medium">{u.name}</span>
              <span class="fact">{u.version}</span>
              {#if held}
                <span class="flex items-center gap-1 text-xs text-warn" data-testid="updates-failed"
                  ><TriangleAlert class="size-3" />{failed?.versions?.[u.target] ? `${short(failed.versions[u.target])} held back` : "update held back"}: failed its check</span
                >
              {/if}
              <span class="ml-auto text-xs text-muted-foreground">{#if u.at}<When at={u.at} />{/if}</span>
              {#if failed}<Button size="sm" variant="ghost" class="text-primary" onclick={() => show(failed, true)} data-testid="update-see-why">See why</Button>{/if}
            </li>
          {/each}
        </ul>
      {/if}
    </div>
  {/if}

  <!-- under the hood: the images and the toolbox -->
  <details class="group rounded-[10px] border bg-muted/40" open={notBuilt > 0} data-testid="under-the-hood">
    <summary class="flex cursor-pointer items-center gap-2 px-4 py-3 text-sm select-none">
      <ChevronDown class="size-4 -rotate-90 text-muted-foreground transition-transform group-open:rotate-0" />Under the hood
      <span class="fact ml-auto">toolbox · {imageCount} image{imageCount === 1 ? "" : "s"}{#if notBuilt}{" · "}{notBuilt} not built{/if}</span>
    </summary>
    <div class="space-y-8 border-t bg-background px-4 py-6">
      {#if networkFilter}
        <div class="space-y-3">
          {@render group("Built into Handler")}
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
              about: networkFilter.imagePresent ? "Where agents connect, checked, and your secrets added to their requests." : "Agents with a network allow-list or a secret can't start without it.",
              target: "network-filter",
            })}
          </ul>
        </div>
      {/if}

      <div class="space-y-3">
        {@render group("Agent programs")}
        {#if !loaded}
          <div class="space-y-2">{#each { length: 3 }, i (i)}<Skeleton class="h-14 w-full rounded-[10px]" role="status" aria-label="Loading" data-testid="loading" />{/each}</div>
        {:else}
          <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
            {#each programs as h (h.name)}
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
        <div class="space-y-3">
          {@render group("Tools that bring programs")}
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
        <ToolboxSettings {toolbox} {harnesses} disabled={busy || running} onchanged={() => void load()} onbuild={(update) => void rebuild("toolbox", update)} />
      {/if}
    </div>
  </details>
</section>
