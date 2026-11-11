<script lang="ts">
  // The Library's Tools shelf (G; in the files and the API, addons): what agents are given to
  // reach a system (a store, a browser), with your connections to them (D.15, bindings). Yours: a
  // row each (its connections and the sites it reaches, who uses it, its state in a word: a broken
  // one says so in amber with Fix, its message in the dialog), Handler's own folded, then what you
  // could get. Get more: what the sources offer (SourceShelf), and a tool from a folder or an
  // archive (AddonInstaller, which previews before anything is installed). Installed, a tool's
  // page opens (ToolView), where it is connected. `install`: that source's preview open (G.5).
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import FolderInput from "@lucide/svelte/icons/folder-input";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import Wrench from "@lucide/svelte/icons/wrench";
  import { Button } from "$lib/components/ui/button";
  import AddonInstaller from "../components/AddonInstaller.svelte";
  import Dialog from "../components/Dialog.svelte";
  import LoadingCards from "../components/LoadingCards.svelte";
  import SourceShelf from "../components/SourceShelf.svelte";
  import { api } from "../lib/api";
  import type { AddonInfo, BindingInfo, Source } from "../lib/contracts.gen";
  import { LIBRARY_WIDTH } from "../lib/library";
  import { href, navigate } from "../lib/router.svelte";
  import { offered } from "../lib/sources";
  import { brokenBecause, sitesWords, TOOL_STATE, toolState } from "../lib/tools";

  let { more = false, install }: { more?: boolean; install?: string } = $props();

  let tools = $state<AddonInfo[]>([]);
  let connections = $state<BindingInfo[]>([]);
  let usedBy = $state<Record<string, string[]>>({});
  let sources = $state<Source[]>([]);
  let loaded = $state(false);
  let error = $state<string | null>(null);
  let installer = $state<AddonInstaller | null>(null);
  // what is broken, its message shown: a tool (or one of its connections), or a connection
  // whose tool is not installed
  type Fixing = { name: string; messages: string[]; tool?: AddonInfo; connection?: string };
  let fixing = $state<Fixing | null>(null);
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
          (u) => (usedBy = { ...usedBy, [t.name]: [...new Set((u.usedBy ?? []).filter((r) => r.kind === "agent" || r.kind === "project").map((r) => r.label))] }),
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

  const yours = $derived(tools.filter((t) => !t.builtin));
  const handlers = $derived(tools.filter((t) => t.builtin));
  const toGet = $derived(offered(sources, "addon").filter((o) => !o.item.installed));
  const of = (t: AddonInfo) => connections.filter((c) => c.addon === t.name);
  const orphans = $derived(connections.filter((c) => !tools.some((t) => t.name === c.addon)));

  /** Installed: its page, its first connection's form open when it has settings. Updated: the
   *  shelf again, its connections kept. */
  async function installed(_message: string, name: string, updated: boolean): Promise<void> {
    if (updated) await load();
    else navigate({ view: "tool", name, connect: true });
  }

  function retry(t: AddonInfo): void {
    fixing = null;
    void installer?.look(t.source ?? "");
  }

  async function forget(connection: string): Promise<void> {
    if (!confirm(`Delete the connection ${connection} and its secrets?`)) return;
    try {
      await api.deleteBinding(connection);
      fixing = null;
      await load();
    } catch (e) {
      error = (e as Error).message;
    }
  }

  const TONE = { broken: "text-warn", "not-set-up": "text-warn", "not-ready": "text-warn", preparing: "text-muted-foreground", ready: "text-ok" } as const;
</script>

{#snippet row(t: AddonInfo)}
  {@const mine = of(t)}
  {@const state = toolState(t, mine)}
  {@const users = usedBy[t.name] ?? []}
  <li class="flex flex-wrap items-center gap-3 px-4 py-3" data-testid="addon-card">
    <span class="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground"><Wrench class="size-4" /></span>
    <a class="min-w-0 flex-1 basis-56 text-foreground no-underline" href={href({ view: "tool", name: t.name })} data-testid="tool-open">
      <span class="block font-medium hover:underline">{t.name}</span>
      <span class="fact block truncate" data-testid="addon-contents"
        >{#if mine.length}{mine.map((c) => `${t.name}: ${c.name}`).join(", ")} · {/if}{#if !mine.length && t.description}<span class="font-sans">{t.description}</span> · {/if}{sitesWords(t)}</span
      >
    </a>
    <span class="hidden max-w-48 truncate text-xs text-muted-foreground md:block" title={users.join(", ")} data-testid="tool-used-by">{users.length ? users.join(", ") : "nobody yet"}</span>
    {#if state === "broken"}
      <span class="inline-flex w-24 items-center gap-1 text-xs text-warn" data-testid="addon-state"><TriangleAlert class="size-3" />Broken</span>
      <Button size="sm" variant="outline" onclick={() => (fixing = { name: t.name, messages: brokenBecause(t, mine), tool: t })} data-testid="tool-fix">Fix</Button>
    {:else}
      <span class="inline-flex w-24 items-center gap-1.5 text-xs {TONE[state]}" data-testid="addon-state"><span class="size-1.5 rounded-full bg-current"></span>{TOOL_STATE[state]}</span>
      {#if state === "not-set-up"}
        <Button size="sm" variant="outline" href={href({ view: "tool", name: t.name })} data-testid="tool-set-up">Set up</Button>
      {:else}
        <Button size="sm" variant="ghost" href={href({ view: "tool", name: t.name })} data-testid="tool-edit">Edit</Button>
      {/if}
    {/if}
  </li>
{/snippet}

<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full {LIBRARY_WIDTH} space-y-5 px-8 py-6" data-testid="addons-page">
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
      {#if yours.length || orphans.length}
        <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel" data-testid="addons">
          {#each yours as t (t.name)}{@render row(t)}{/each}
          {#each orphans as c (c.name)}
            <li class="flex flex-wrap items-center gap-3 px-4 py-3" data-testid="binding-row">
              <span class="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground"><Wrench class="size-4" /></span>
              <span class="min-w-0 flex-1 basis-56">
                <span class="block font-medium">{c.name}</span>
                <span class="fact block truncate">a connection to {c.addon ?? "a tool"}, not installed</span>
              </span>
              <span class="inline-flex w-24 items-center gap-1 text-xs text-warn"><TriangleAlert class="size-3" />Broken</span>
              <Button size="sm" variant="outline" onclick={() => (fixing = { name: c.name, messages: [c.error ?? `its tool ${c.addon} is not installed`], connection: c.name })} data-testid="tool-fix">Fix</Button>
            </li>
          {/each}
        </ul>
      {:else}
        <div class="rounded-[10px] border border-dashed px-6 py-8 text-center text-sm text-muted-foreground" data-testid="addons-steps">
          No tool yet: a tool gives your agents a program and how to use it (a browser, a store's command), and only the sites it needs.
        </div>
      {/if}

      {#if handlers.length}
        <details class="group rounded-[10px] bg-muted/50" data-testid="tools-from-handler">
          <summary class="flex cursor-pointer list-none items-center gap-2 px-4 py-2.5 text-sm text-muted-foreground">
            <ChevronRight class="size-4 transition-transform group-open:rotate-90" />From Handler
            <span class="fact ml-auto">{handlers.map((t) => t.name).join(", ")}</span>
          </summary>
          <ul class="divide-y overflow-hidden rounded-b-[10px] border-t bg-card text-sm">
            {#each handlers as t (t.name)}{@render row(t)}{/each}
          </ul>
        </details>
      {/if}

      {#if toGet.length}
        <div class="flex flex-wrap items-center gap-2.5 rounded-[10px] border border-dashed px-4 py-3 text-sm" data-testid="tools-more">
          <Wrench class="size-4 text-muted-foreground" />
          <span>{toGet.length} more tool{toGet.length === 1 ? "" : "s"}</span>
          {#each toGet.slice(0, 3) as { item } (item.name)}<span class="rounded-md border px-1.5 py-0.5 text-xs">{item.name}</span>{/each}
          <Button size="sm" variant="outline" class="ml-auto" href={href({ view: "library", shelf: "tools", more: true })}>Get more</Button>
        </div>
      {/if}
    {/if}
  </div>
</div>

<AddonInstaller bind:this={installer} oninstalled={installed} />

<Dialog bind:open={() => fixing !== null, (v) => (v ? null : (fixing = null))} title={fixing ? `${fixing.name} is broken` : ""} testid="tool-fix-dialog">
  {#if fixing}
    {@const f = fixing}
    <div class="space-y-4 text-sm">
      <ul class="space-y-1.5 rounded-lg bg-muted px-3 py-2.5 font-mono text-xs leading-5 break-words" data-testid="tool-fix-message">
        {#each f.messages as m (m)}<li>{m}</li>{/each}
      </ul>
      <div class="flex flex-wrap justify-end gap-2 border-t pt-4">
        {#if f.connection}
          <Button size="sm" variant="ghost" class="text-destructive hover:text-destructive" onclick={() => forget(f.connection ?? "")} data-testid="binding-delete">Delete the connection</Button>
        {/if}
        {#if f.tool?.source}<Button size="sm" variant="outline" onclick={() => f.tool && retry(f.tool)} data-testid="tool-reinstall">Install it again</Button>{/if}
        {#if f.tool}<Button size="sm" href={href({ view: "tool", name: f.tool.name })} onclick={() => (fixing = null)}>Its page</Button>{/if}
      </div>
    </div>
  {/if}
</Dialog>
