<script lang="ts">
  // Harness and addon images (contracts D.4, G.4): whether this computer can run agents (A.8: each
  // problem with its fix), automatic updates, the network filter (handler's own image: the egress proxy,
  // never called so here, docs/dev/ui-ux.md), what each image installed, build or update one (from
  // the files on disk: latest release, checked before agents switch to it), the shared toolbox
  // (advanced: its Containerfile edited in place), and the running build's progress and log. The
  // log is shown as text, never as markup.
  import When from "./When.svelte";
  import Pencil from "@lucide/svelte/icons/pencil";
  import RefreshCw from "@lucide/svelte/icons/refresh-cw";
  import X from "@lucide/svelte/icons/x";
  import { Button } from "$lib/components/ui/button";
  import * as NativeSelect from "$lib/components/ui/native-select";
  import { Skeleton } from "$lib/components/ui/skeleton";
  import * as Table from "$lib/components/ui/table";
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
    // after a reload: follow a build still running, or show how the last one ended
    api.builds().then(
      (list) => {
        if (list[0] && (list[0].state === "running" || list[0].state === "failed")) show(list[0]);
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

{#snippet group(label: string)}
  <Table.Row class="bg-muted/40 hover:bg-muted/40">
    <Table.Cell colspan={4} class="py-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">{label}</Table.Cell>
  </Table.Row>
{/snippet}

<section class="space-y-4" data-testid="harness-images">
  <p class="max-w-2xl text-sm text-muted-foreground">
    The container images agents run in: one per agent program and addon, each built on the shared toolbox, and the network
    filter between agents and the internet. Handler builds them when needed and keeps them up to date; running sessions keep the
    image they started with.
  </p>
  {#if error}<p class="text-sm text-danger">{error}</p>{/if}
  {#if runtime.error}<p class="text-sm text-danger">{runtime.error}</p>{/if}
  {#if host && host.items.some((i) => !i.ok)}
    <div class="space-y-2 rounded-lg border p-3.5 text-sm {host.ok ? 'border-warn/60' : 'border-danger'}" data-testid="runtime-check">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <span class="font-medium">
          {host.ok ? "Some agents need more from this computer" : "Agents can't run on this computer yet"}
          <span class="font-normal text-muted-foreground">({host.runtime})</span>
        </span>
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
    <p class="text-sm text-muted-foreground" data-testid="runtime-check"><span class="text-ok">✓</span> {host.runtime}: agents can run on this computer</p>
  {/if}
  {#if updates}
    <div class="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm" data-testid="image-updates">
      <label for="image-updates-schedule" class="font-medium">Automatic updates</label>
      <NativeSelect.Root
        id="image-updates-schedule"
        class="w-36"
        value={updates.schedule}
        disabled={busy}
        onchange={(e) => setSchedule(e.currentTarget.value)}
      >
        <NativeSelect.Option value="weekly">Weekly</NativeSelect.Option>
        <NativeSelect.Option value="daily">Daily</NativeSelect.Option>
        <NativeSelect.Option value="off">Off</NativeSelect.Option>
      </NativeSelect.Root>
      <span class="text-muted-foreground">
        {#if updates.running}updating…{:else}last <When at={updates.lastRun} />{#if updates.nextRun} · next <When at={updates.nextRun} />{/if}{/if}
      </span>
      <Button size="sm" variant="outline" disabled={busy || running || updates.running} onclick={updateNow} data-testid="update-now">
        <RefreshCw />Update now
      </Button>
      {#if updates.lastFailed?.length}
        <span class="text-danger" data-testid="updates-failed">failed last time: {updates.lastFailed?.join(", ")}</span>
      {/if}
      <p class="w-full text-xs text-muted-foreground">
        Handler installs the new releases of the agent programs and addons it has built, and the network filter's security updates,
        and switches to one only once it passes a check; also after a Handler upgrade. The shared toolbox changes only with <span class="font-medium">Rebuild everything</span>.
      </p>
    </div>
  {/if}
  <div class="overflow-hidden rounded-lg border bg-card">
    <Table.Root>
      <Table.Header>
        <Table.Row>
          <Table.Head>Image</Table.Head><Table.Head>Installed</Table.Head><Table.Head>Built</Table.Head><Table.Head></Table.Head>
        </Table.Row>
      </Table.Header>
      <Table.Body>
        {#if networkFilter}
          {@render group("Built into Handler")}
          <Table.Row data-testid="network-filter-row">
            <Table.Cell class="whitespace-normal">
              <div class="font-medium">Network filter</div>
              <div class="font-mono text-xs text-muted-foreground">{networkFilter.image}</div>
              <div class="text-xs text-muted-foreground">checks where agents connect and adds your secrets to their requests</div>
            </Table.Cell>
            <Table.Cell class="text-sm whitespace-normal" data-testid="network-filter-state">
              {#if !networkFilter.imagePresent}
                <span class="text-warn">not built yet</span>
                <div class="text-xs text-muted-foreground">agents with a network allow-list or a secret can't start without it</div>
              {:else}built{/if}
            </Table.Cell>
            <Table.Cell class="text-muted-foreground"><When at={networkFilter.builtAt} never="—" /></Table.Cell>
            <Table.Cell class="text-right">
              <Button size="sm" variant="outline" disabled={busy || running} onclick={() => rebuild("network-filter")}>
                <RefreshCw />{networkFilter.imagePresent ? "Update" : "Build"}
              </Button>
            </Table.Cell>
          </Table.Row>
        {/if}
        {@render group("Agent programs")}
        {#if !loaded}
          {#each { length: 3 }, i (i)}
            <Table.Row data-testid="loading">
              <Table.Cell colspan={4}><Skeleton class="h-9 w-full" role="status" aria-label="Loading" /></Table.Cell>
            </Table.Row>
          {/each}
        {/if}
        {#each harnesses as h (h.name)}
          <Table.Row data-testid="harness-image-row">
            <Table.Cell>
              <div class="font-medium">{h.product}</div>
              <div class="font-mono text-xs text-muted-foreground">{h.image}</div>
            </Table.Cell>
            <Table.Cell class="text-sm whitespace-normal" data-testid="harness-version">
              {#if !h.imagePresent}<span class="text-warn">not built yet</span>{:else}{h.version ?? "unknown"}{/if}
            </Table.Cell>
            <Table.Cell class="text-muted-foreground"><When at={h.builtAt} never="—" /></Table.Cell>
            <Table.Cell class="text-right">
              <Button size="sm" variant="outline" disabled={busy || running} onclick={() => rebuild(h.name)}>
                <RefreshCw />{h.imagePresent ? "Update" : "Build"}
              </Button>
            </Table.Cell>
          </Table.Row>
        {/each}
        {#if addons.length}{@render group("Addons")}{/if}
        {#each addons as a (a.name)}
          <Table.Row data-testid="addon-image-row">
            <Table.Cell>
              <div class="font-medium">{a.name}</div>
              <div class="font-mono text-xs text-muted-foreground">{a.image}</div>
            </Table.Cell>
            <Table.Cell class="text-sm whitespace-normal" data-testid="addon-version">
              {#if !a.imagePresent}<span class="text-warn">not built yet</span>{:else}{a.version ?? "unknown"}{/if}
            </Table.Cell>
            <Table.Cell class="text-muted-foreground"><When at={a.builtAt} never="—" /></Table.Cell>
            <Table.Cell class="text-right">
              <Button size="sm" variant="outline" disabled={busy || running} onclick={() => rebuild(`addon:${a.name}`)}>
                <RefreshCw />{a.imagePresent ? "Update" : "Build"}
              </Button>
            </Table.Cell>
          </Table.Row>
        {/each}
        {#if toolbox}
          {@render group("Shared base (advanced)")}
          <Table.Row>
            <Table.Cell>
              <div class="font-medium">toolbox</div>
              <div class="font-mono text-xs text-muted-foreground">{toolbox.image}</div>
            </Table.Cell>
            <Table.Cell class="text-sm text-muted-foreground whitespace-normal">
              {#if !toolbox.imagePresent}<span class="text-warn">not built yet</span>{:else}the system and tools every image starts from{/if}
              <div class="font-mono text-xs" data-testid="toolbox-directory">yours: {toolbox.directory}</div>
            </Table.Cell>
            <Table.Cell class="text-muted-foreground"><When at={toolbox.builtAt} never="—" /></Table.Cell>
            <Table.Cell class="text-right">
              <div class="flex justify-end gap-1">
                <Button size="sm" variant="ghost" disabled={editing} onclick={() => (editing = true)} data-testid="toolbox-edit">
                  <Pencil />Edit its Containerfile
                </Button>
                <Button size="sm" variant="outline" disabled={busy || running} onclick={() => rebuild("toolbox")}>
                  <RefreshCw />Rebuild everything
                </Button>
              </div>
            </Table.Cell>
          </Table.Row>
          {#if editing}
            <Table.Row class="hover:bg-transparent">
              <Table.Cell colspan={4} class="whitespace-normal">
                <ToolboxEditor directory={toolbox.directory} onclose={() => (editing = false)} onsaved={() => void load()} />
              </Table.Cell>
            </Table.Row>
          {/if}
        {/if}
      </Table.Body>
    </Table.Root>
  </div>

  {#if build}
    <div class="space-y-3 rounded-lg border bg-card p-4" data-testid="build-panel">
      <div class="flex flex-wrap items-center gap-2 text-sm">
        <span class="font-medium">Building {build.target}</span>
        <span data-testid="build-state"><StatusBadge status={build.state} /></span>
        {#if running && build.stage}
          <span class="text-muted-foreground">
            {build.stage}{#if build.step && build.steps}: step {build.step} of {build.steps}{/if}
          </span>
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
        <p class="text-sm">{name}: {version}</p>
      {/each}
      <pre
        bind:this={logElement}
        class="term-surface max-h-96 overflow-auto rounded-md border p-3 font-mono text-xs whitespace-pre-wrap"
        data-testid="build-log">{log}</pre>
    </div>
  {/if}
</section>
