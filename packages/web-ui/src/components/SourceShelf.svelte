<script lang="ts">
  // What the sources offer of one kind (D.26), a shelf's Get more: a search (and a source, with
  // several), the items as cards (SourceItemCard: where each comes from, its notes, its button to
  // its kind's own install page), what cannot be read now. `extra`: the shelf's own ways to get
  // one, after the cards (an app file, a tool from a folder); `project`: agents got are set up
  // there. Sources are in Settings → Sources.
  import Settings from "@lucide/svelte/icons/settings";
  import type { Snippet } from "svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import LoadingCards from "./LoadingCards.svelte";
  import SourceItemCard from "./SourceItemCard.svelte";
  import { api } from "../lib/api";
  import type { Source, SourceItem } from "../lib/contracts.gen";
  import { href } from "../lib/router.svelte";
  import { offered, takeItem } from "../lib/sources";

  let { kind, what, extra, project }: { kind: SourceItem["kind"]; what: string; extra?: Snippet; project?: string } = $props();

  let sources = $state<Source[] | null>(null);
  let error = $state<string | null>(null);
  let query = $state("");
  let from = $state("all"); // a source's id
  let busy = $state(false);

  api.sources().then(
    (s) => (sources = s),
    (e: Error) => (error = e.message),
  );

  const words = $derived(query.trim().toLowerCase());
  const shown = $derived(
    offered(sources ?? [], kind).filter(
      ({ source, item }) => (from === "all" || source.id === from) && (!words || `${item.name} ${item.description ?? ""}`.toLowerCase().includes(words)),
    ),
  );
  const unread = $derived((sources ?? []).filter((s) => s.error && !s.commit));

  async function take(source: Source, item: SourceItem): Promise<void> {
    busy = true;
    error = null;
    try {
      await takeItem(source.id, item, project);
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

<div class="space-y-5" data-testid="get-more">
  <div class="flex flex-wrap items-center gap-2">
    <Input class="min-w-64 flex-1" placeholder="Search {what}" bind:value={query} data-testid="discover-search" />
    {#if (sources?.length ?? 0) > 1}
      <select class="h-9 rounded-lg border bg-card px-2.5 text-sm" aria-label="source" bind:value={from} data-testid="discover-source">
        <option value="all">Every source</option>
        {#each sources ?? [] as s (s.id)}<option value={s.id}>{s.official ? "Handler" : (s.name ?? s.id)}</option>{/each}
      </select>
    {/if}
    <Button variant="ghost" size="sm" href={href({ view: "settings", section: "sources" })} data-testid="discover-sources"><Settings />Sources</Button>
  </div>
  {#if error}<p class="text-sm text-danger" data-testid="discover-error">{error}</p>{/if}
  {#each unread as s (s.id)}
    <p class="text-sm text-muted-foreground" title={s.error ?? undefined} data-testid="discover-unread">
      {s.official ? "Handler's source" : (s.name ?? s.id)} cannot be read now: <a href={href({ view: "settings", section: "sources" })}>Settings → Sources</a>
    </p>
  {/each}
  {#if !sources && !error}
    <div class="grid gap-4 sm:grid-cols-3"><LoadingCards count={3} height="h-44" /></div>
  {:else}
    <ul class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {#each shown as { source, item } (`${source.id}/${item.name}`)}
        <SourceItemCard {source} {item} {busy} ontake={() => take(source, item)} />
      {/each}
      {@render extra?.()}
    </ul>
    {#if !shown.length}
      <p class="rounded-[10px] border border-dashed px-4 py-4 text-center text-sm text-muted-foreground" data-testid="discover-nothing">
        {words || from !== "all" ? "Nothing here matches." : `No source offers ${what} yet.`}
      </p>
    {/if}
  {/if}
</div>
