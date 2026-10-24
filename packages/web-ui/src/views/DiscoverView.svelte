<script lang="ts">
  // Discover (D.26): everything the sources offer, on one shelf, by kind: apps (they work for
  // you), agents (set up in a project), tools for agents (addons). A search, a kind and a source
  // to narrow it. Each card says where it comes from and what it does; its name opens its page
  // (DiscoverItemView), its button goes to its kind's own install page (lib/sources.ts). Sources
  // are managed in Settings → Sources.
  import Settings from "@lucide/svelte/icons/settings";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import LoadingCards from "../components/LoadingCards.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import PageTitle from "../components/PageTitle.svelte";
  import SourceItemCard from "../components/SourceItemCard.svelte";
  import { api } from "../lib/api";
  import type { Source, SourceItem } from "../lib/contracts.gen";
  import { href } from "../lib/router.svelte";
  import { offered, takeItem } from "../lib/sources";

  type Kind = SourceItem["kind"];
  const SECTIONS: { kind: Kind; title: string; about: string; label: string }[] = [
    { kind: "app", title: "Apps", about: "they work for you: you open them, ask them, or they run by themselves", label: "Apps" },
    { kind: "agents", title: "Agents", about: "set up in one of your projects, on your models: yours afterwards", label: "Agents" },
    { kind: "addon", title: "Tools for your agents", about: "addons: a program, how to use it, the sites it needs", label: "Tools" },
  ];

  let sources = $state<Source[] | null>(null);
  let error = $state<string | null>(null);
  let query = $state("");
  let kind = $state<Kind | "all">("all");
  let from = $state("all"); // a source's id
  let busy = $state(false);

  api.sources().then(
    (s) => (sources = s),
    (e: Error) => (error = e.message),
  );

  const words = $derived(query.trim().toLowerCase());
  const shown = (k: Kind) =>
    offered(sources ?? [], k).filter(
      ({ source, item }) => (from === "all" || source.id === from) && (!words || `${item.name} ${item.description ?? ""}`.toLowerCase().includes(words)),
    );
  const counts = $derived(Object.fromEntries(SECTIONS.map((s) => [s.kind, shown(s.kind).length])) as Record<Kind, number>);
  const unread = $derived((sources ?? []).filter((s) => s.error && !s.commit));

  async function take(source: Source, item: SourceItem): Promise<void> {
    busy = true;
    error = null;
    try {
      await takeItem(source.id, item);
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

<PageHeader titled title="Discover">
  {#snippet actions()}
    <Button variant="ghost" size="sm" href={href({ view: "settings", section: "sources" })} data-testid="discover-sources"><Settings />Sources</Button>
  {/snippet}
</PageHeader>
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-5xl space-y-8 px-8 py-10" data-testid="discover-page">
    <PageTitle title="Discover" description="Apps that work for you, agents to set up in a project, and tools your agents can use. Each one shows what it may touch before you install it." />
    <div class="flex flex-wrap items-center gap-2">
      <Input class="min-w-64 flex-1" placeholder="Search" bind:value={query} data-testid="discover-search" />
      <div class="inline-flex rounded-lg border bg-muted p-0.5 text-sm" role="group" aria-label="kind">
        {#each [{ kind: "all" as const, label: "All" }, ...SECTIONS] as k (k.kind)}
          <button
            type="button"
            class="rounded-md px-3 py-1 {kind === k.kind ? 'bg-card font-medium text-foreground shadow-sm' : 'text-muted-foreground'}"
            onclick={() => (kind = k.kind)}
            data-testid="discover-kind-{k.kind}"
            >{k.label}{#if k.kind !== "all"}<span class="fact ml-1.5">{counts[k.kind]}</span>{/if}</button
          >
        {/each}
      </div>
      {#if (sources?.length ?? 0) > 1}
        <select class="h-9 rounded-lg border bg-card px-2.5 text-sm" aria-label="source" bind:value={from} data-testid="discover-source">
          <option value="all">Every source</option>
          {#each sources ?? [] as s (s.id)}<option value={s.id}>{s.official ? "Handler" : (s.name ?? s.id)}</option>{/each}
        </select>
      {/if}
    </div>
    {#if error}<p class="text-sm text-danger" data-testid="discover-error">{error}</p>{/if}
    {#each unread as s (s.id)}
      <p class="text-sm text-muted-foreground" title={s.error ?? undefined} data-testid="discover-unread">
        {s.official ? "Handler's source" : (s.name ?? s.id)} cannot be read now: <a href={href({ view: "settings", section: "sources" })}>Settings → Sources</a>
      </p>
    {/each}
    {#if !sources && !error}
      <div class="grid gap-4 sm:grid-cols-3"><LoadingCards count={3} height="h-44" /></div>
    {:else if sources}
      {#each SECTIONS.filter((s) => kind === "all" || kind === s.kind) as section (section.kind)}
        {@const list = shown(section.kind)}
        <section class="space-y-3" data-testid="discover-{section.kind}">
          <h2 class="flex flex-wrap items-baseline gap-2 font-semibold">{section.title} <span class="text-xs font-normal text-muted-foreground">{section.about}</span></h2>
          {#if list.length}
            <ul class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {#each list as { source, item } (`${source.id}/${item.name}`)}
                <SourceItemCard {source} {item} {busy} ontake={() => take(source, item)} />
              {/each}
            </ul>
          {:else}
            <p class="rounded-[10px] border border-dashed px-4 py-4 text-center text-sm text-muted-foreground">{words || from !== "all" ? "Nothing here matches." : "No source offers any yet."}</p>
          {/if}
        </section>
      {/each}
    {/if}
  </div>
</div>
