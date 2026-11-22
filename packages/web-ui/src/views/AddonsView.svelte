<script lang="ts">
  // The Library's Tools shelf (G; in the files and the API, addons): what agents are given to
  // reach a system (a store, a browser), with your connections to them (D.15, bindings). Yours: a
  // card each, its state in a word (a broken one says so in amber with Fix, its message in the
  // dialog), its connections under it (what each holds, who it is given to; Connect another, the
  // tool's page with a new connection's form open), or who it is given to when it needs no
  // connection; a connection whose tool is gone listed apart (Get <tool>, Delete); Handler's own
  // folded, then what you could get. Community: what the sources offer (SourceShelf), and a tool
  // from a folder or an archive (AddonInstaller, which previews before anything is installed).
  // Installed, a tool's page opens (ToolView), where it is connected. `install`: that source's
  // preview open (G.5).
  import { ask } from "../lib/ask.svelte";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import FolderInput from "@lucide/svelte/icons/folder-input";
  import Link from "@lucide/svelte/icons/link";
  import Plus from "@lucide/svelte/icons/plus";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import Wrench from "@lucide/svelte/icons/wrench";
  import { Button } from "$lib/components/ui/button";
  import AddonInstaller from "../components/AddonInstaller.svelte";
  import Dialog from "../components/Dialog.svelte";
  import LoadingCards from "../components/LoadingCards.svelte";
  import ShelfBar from "../components/ShelfBar.svelte";
  import SourceShelf from "../components/SourceShelf.svelte";
  import { api } from "../lib/api";
  import type { AddonInfo, BindingInfo, Source } from "../lib/contracts.gen";
  import { LIBRARY_WIDTH, type ShelfLists } from "../lib/library";
  import { href, navigate } from "../lib/router.svelte";
  import { hasSlots } from "../lib/setup";
  import { offered } from "../lib/sources";
  import { brokenBecause, connectionFacts, connectionUsers, givenWords, shelfOf, sitesWords, TOOL_STATE, toolOrigin, toolState, toolUsers } from "../lib/tools";

  let { more = false, install, lists }: { more?: boolean; install?: string; lists?: ShelfLists } = $props();

  let tools = $state<AddonInfo[]>([]);
  let connections = $state<BindingInfo[]>([]);
  let usedBy = $state<Record<string, string[]>>({});
  let sources = $state<Source[]>([]);
  let loaded = $state(false);
  let error = $state<string | null>(null);
  let installer = $state<AddonInstaller | null>(null);
  // a broken tool (or one of its connections), its messages shown
  let fixing = $state<{ tool: AddonInfo; messages: string[] } | null>(null);
  let looked: string | undefined;

  $effect(() => {
    if (install && installer && looked !== install) {
      looked = install;
      void installer.look(install);
    }
  });

  async function load(): Promise<void> {
    try {
      [tools, connections] = await Promise.all([api.addons(), api.bindings()]);
      error = null;
      for (const t of tools)
        api.uses("addon", t.name).then(
          (u) => (usedBy = { ...usedBy, [t.name]: toolUsers(u.usedBy) }),
          () => undefined,
        );
    } catch (e) {
      error = (e as Error).message;
    } finally {
      loaded = true;
    }
  }

  $effect(() => {
    void load();
    api.sources().then(
      (s) => (sources = s),
      () => undefined,
    );
  });

  const shelf = $derived(shelfOf(tools, connections));
  const yours = $derived(shelf.tools.filter((t) => !t.tool.builtin));
  const handlers = $derived(shelf.tools.filter((t) => t.tool.builtin));
  const orphans = $derived(shelf.orphans);
  const toGet = $derived(offered(sources, "addon").filter((o) => !o.item.installed));

  /** Installed: its page, a new connection's form open when it has settings and no connection
   *  yet (one kept from before is its again). Updated: the shelf again, its connections kept. */
  async function installed(_message: string, name: string, updated: boolean): Promise<void> {
    if (updated) await load();
    else navigate({ view: "tool", name, connect: !connections.some((c) => c.addon === name) });
  }

  function retry(t: AddonInfo): void {
    fixing = null;
    void installer?.look(t.source ?? "");
  }

  /** A connection's tool, got again: its preview from the source offering it, else Community. */
  function getTool(tool: string): void {
    const found = offered(sources, "addon").find((o) => o.item.name === tool);
    if (found) void installer?.look(`source:${found.source.id}/${found.item.name}`);
    else navigate({ view: "library", shelf: "tools", more: true });
  }

  async function forget(connection: string): Promise<void> {
    if (!(await ask({ title: `Delete the connection ${connection} and its secrets?`, yes: "Delete", danger: true }))) return;
    try {
      await api.deleteBinding(connection);
      await load();
    } catch (e) {
      error = (e as Error).message;
    }
  }

  const TONE = { broken: "text-warn", "not-set-up": "text-warn", "not-ready": "text-warn", preparing: "text-muted-foreground", ready: "text-ok" } as const;
</script>

{#snippet card(t: AddonInfo, mine: BindingInfo[])}
  {@const state = toolState(t, mine)}
  {@const slots = hasSlots(t)}
  <li class="overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel" data-testid="addon-card">
    <div class="flex flex-wrap items-center gap-3 px-4 py-3">
      <span class="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground"><Wrench class="size-4" /></span>
      <a class="min-w-0 flex-1 basis-56 text-foreground no-underline" href={href({ view: "tool", name: t.name })} data-testid="tool-open">
        <span class="block font-medium hover:underline">{t.name}</span>
        <span class="block truncate text-xs text-muted-foreground" title={t.egress?.join(", ")} data-testid="addon-contents"
          >{[t.description, `reaches ${sitesWords(t)}`, !slots && !t.error && "no settings, no connection needed", toolOrigin(t)].filter(Boolean).join(" · ")}</span
        >
      </a>
      {#if state === "broken"}
        <span class="inline-flex w-24 items-center gap-1 text-xs text-warn" data-testid="addon-state"><TriangleAlert class="size-3" />Broken</span>
        <Button size="sm" variant="outline" onclick={() => (fixing = { tool: t, messages: brokenBecause(t, mine) })} data-testid="tool-fix">Fix</Button>
      {:else}
        <span class="inline-flex w-24 items-center gap-1.5 text-xs {TONE[state]}" data-testid="addon-state"><span class="size-1.5 rounded-full bg-current"></span>{TOOL_STATE[state]}</span>
        {#if state === "not-set-up"}
          <Button size="sm" variant="outline" href={href({ view: "tool", name: t.name })} data-testid="tool-set-up">Set up</Button>
        {:else}
          <Button size="sm" variant="ghost" href={href({ view: "tool", name: t.name })} data-testid="tool-edit">Open</Button>
        {/if}
      {/if}
    </div>
    {#if mine.length || (slots && !t.error)}
      <div class="border-t bg-muted/30 px-4 py-2.5" data-testid="tool-connections">
        <p class="pb-1 text-xs font-medium text-muted-foreground">Its connections</p>
        <ul>
          {#each mine as c (c.name)}
            {@const facts = connectionFacts(c)}
            <li class="flex flex-wrap items-center gap-x-2.5 gap-y-0.5 py-1.5" data-testid="tool-connection">
              <Link class="size-3.5 shrink-0 text-muted-foreground" />
              <span class="font-medium">{c.name}</span>
              {#if c.error}
                <span class="min-w-0 flex-1 truncate text-xs text-danger" title={c.error}>Broken: {c.error}</span>
              {:else}
                {#if facts.length}<span class="min-w-0 truncate text-xs text-muted-foreground" title={Object.entries(c.settings ?? {}).map(([k, v]) => `${k}=${v}`).join("  ")}>{facts.join(" · ")}</span>{/if}
                <span class="ml-auto text-xs text-muted-foreground" data-testid="connection-given">{givenWords(connectionUsers(c.usedBy))}</span>
              {/if}
            </li>
          {/each}
        </ul>
        {#if slots && !t.error}
          <a class="mt-1 inline-flex items-center gap-1.5 py-1 text-sm font-medium text-link no-underline hover:underline" href={href({ view: "tool", name: t.name, connect: true })} data-testid="tool-connect"
            ><Plus class="size-3.5" />{mine.length ? "Connect another" : "Connect"}</a
          >
        {/if}
      </div>
    {:else if !slots && !t.error}
      <p class="border-t bg-muted/30 px-4 py-2.5 text-xs text-muted-foreground first-letter:uppercase" data-testid="tool-used-by">{givenWords(usedBy[t.name] ?? [])}</p>
    {/if}
  </li>
{/snippet}

<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full {LIBRARY_WIDTH} space-y-5 px-8 py-6" data-testid="addons-page">
    <ShelfBar {lists} />
    {#if error}<p class="text-sm text-danger" data-testid="binding-error">{error}</p>{/if}

    {#if more}
      <SourceShelf kind="addon" what="tools">
        {#snippet extra()}
          <li class="flex flex-col gap-3 rounded-xl border border-dashed bg-muted/40 p-4">
            <span class="flex items-center gap-3">
              <span class="flex size-11 shrink-0 items-center justify-center rounded-xl bg-muted text-muted-foreground"><FolderInput class="size-5" /></span>
              <span class="min-w-0"><span class="block font-semibold">From a folder or an archive</span><span class="fact block">your own, or one shared with you</span></span>
            </span>
            <p class="text-sm text-muted-foreground">You see what it brings and the sites it reaches before it is installed.</p>
            <div class="mt-auto flex justify-end">
              <Button size="sm" variant="outline" onclick={() => installer?.open()} data-testid="addon-elsewhere">Choose…</Button>
            </div>
          </li>
        {/snippet}
      </SourceShelf>
    {:else if !loaded}
      <LoadingCards />
    {:else}
      {#if yours.length}
        <ul class="space-y-3" data-testid="addons">
          {#each yours as { tool, connections: mine } (tool.name)}{@render card(tool, mine)}{/each}
        </ul>
      {:else}
        <div class="rounded-[10px] border border-dashed px-6 py-8 text-center text-sm text-muted-foreground" data-testid="addons-steps">
          No tool yet: a tool gives your agents a program and how to use it (a browser, a store's command), and only the sites it needs.
        </div>
      {/if}

      {#if orphans.length}
        <section data-testid="connections-without-tool">
          <h2 class="mb-1.5 text-sm font-semibold text-muted-foreground">{orphans.length === 1 ? "A connection without its tool" : "Connections without their tool"}</h2>
          <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
            {#each orphans as c (c.name)}
              <li class="flex flex-wrap items-center gap-3 px-4 py-3" data-testid="binding-row">
                <Link class="size-4 shrink-0 text-muted-foreground" />
                <span class="min-w-0 flex-1 basis-56">
                  <span class="block font-medium">{c.name}</span>
                  <span class="block text-xs break-words text-danger" title={c.error ?? undefined} data-testid="binding-error-message"
                    >{c.addon ? `Its tool "${c.addon}" isn't installed any more: agents given it don't get it.` : c.error}</span
                  >
                </span>
                {#if c.addon}<Button size="sm" variant="outline" onclick={() => getTool(c.addon ?? "")} data-testid="connection-get">Get {c.addon}</Button>{/if}
                <Button size="sm" variant="ghost" onclick={() => forget(c.name)} data-testid="binding-delete">Delete</Button>
              </li>
            {/each}
          </ul>
        </section>
      {/if}

      {#if handlers.length}
        <details class="group rounded-[10px] bg-muted/50" data-testid="tools-from-handler">
          <summary class="flex cursor-pointer list-none items-center gap-2 px-4 py-2.5 text-sm text-muted-foreground">
            <ChevronRight class="size-4 transition-transform group-open:rotate-90" />From Handler
            <span class="fact ml-auto">{handlers.map((t) => t.tool.name).join(", ")}</span>
          </summary>
          <ul class="space-y-3 px-2 pb-2">
            {#each handlers as { tool, connections: mine } (tool.name)}{@render card(tool, mine)}{/each}
          </ul>
        </details>
      {/if}

      {#if toGet.length}
        <div class="flex flex-wrap items-center gap-2.5 rounded-[10px] border border-dashed px-4 py-3 text-sm" data-testid="tools-more">
          <Wrench class="size-4 text-muted-foreground" />
          <span>{toGet.length} more tool{toGet.length === 1 ? "" : "s"}</span>
          {#each toGet.slice(0, 3) as { item } (item.name)}<span class="rounded-md border px-1.5 py-0.5 text-xs">{item.name}</span>{/each}
          <Button size="sm" variant="outline" class="ml-auto" href={href({ view: "library", shelf: "tools", more: true })}>Community</Button>
        </div>
      {/if}
    {/if}
  </div>
</div>

<AddonInstaller bind:this={installer} oninstalled={installed} />

<Dialog bind:open={() => fixing !== null, (v) => (v ? null : (fixing = null))} title={fixing ? `${fixing.tool.name} is broken` : ""} testid="tool-fix-dialog">
  {#if fixing}
    {@const f = fixing}
    <div class="space-y-4 text-sm">
      <ul class="space-y-1.5 rounded-lg bg-muted px-3 py-2.5 font-mono text-xs leading-5 break-words" data-testid="tool-fix-message">
        {#each f.messages as m (m)}<li>{m}</li>{/each}
      </ul>
      <div class="flex flex-wrap justify-end gap-2 border-t pt-4">
        {#if f.tool.source}<Button size="sm" variant="outline" onclick={() => retry(f.tool)} data-testid="tool-reinstall">Install it again</Button>{/if}
        <Button size="sm" href={href({ view: "tool", name: f.tool.name })} onclick={() => (fixing = null)}>Its page</Button>
      </div>
    </div>
  {/if}
</Dialog>
