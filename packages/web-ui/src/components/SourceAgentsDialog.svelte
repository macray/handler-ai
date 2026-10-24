<script lang="ts">
  // Agents a source offers (D.26: an agents file's content), to set up in a project: Handler's
  // first, each saying where it comes from. Picking one reads it as a file is (D.23) and goes on
  // to its set-up page (`onread`). The sources are read when the dialog opens.
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import Dialog from "./Dialog.svelte";
  import { api } from "../lib/api";
  import type { AgentsFile, Source, SourceItem } from "../lib/contracts.gen";
  import { href } from "../lib/router.svelte";
  import { fromWords, offered } from "../lib/sources";

  let { open = $bindable(false), onread }: { open: boolean; onread: (file: AgentsFile) => void } = $props();

  let sources = $state<Source[] | null>(null);
  let busy = $state(false);
  let error = $state<string | null>(null);

  const available = $derived(offered(sources ?? [], "agents"));

  $effect(() => {
    if (!open) return;
    error = null;
    api.sources().then(
      (s) => (sources = s),
      (e: Error) => (error = e.message),
    );
  });

  async function pick(source: Source, item: SourceItem): Promise<void> {
    busy = true;
    error = null;
    try {
      const read = await api.agentsFromSource(source.id, item.name);
      open = false;
      onread(read);
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

<Dialog bind:open title="Add agents from a source" description="Agents someone wrote to be set up again: you choose their models next, and see what they will be allowed to do." testid="source-agents">
  <div class="space-y-4">
    {#if !sources && !error}
      <p class="fact">Reading the sources…</p>
    {:else if available.length}
      <div class="divide-y overflow-hidden rounded-[10px] border bg-card">
        {#each available as { source, item } (`${source.id}/${item.name}`)}
          <button
            type="button"
            class="group flex w-full items-center gap-3 px-3.5 py-3 text-left transition-colors hover:bg-muted/60"
            disabled={busy}
            onclick={() => pick(source, item)}
            data-testid="source-agents-item"
          >
            <span class="min-w-0 flex-1">
              <span class="block font-medium">{item.name} <span class="fact font-normal">{fromWords(source)}</span></span>
              {#if item.description}<span class="block text-xs text-muted-foreground">{item.description}</span>{/if}
            </span>
            <ChevronRight class="size-4 shrink-0 text-muted-foreground/60 transition-transform group-hover:translate-x-0.5" />
          </button>
        {/each}
      </div>
    {:else if sources}
      <p class="rounded-[10px] border border-dashed px-4 py-4 text-center text-muted-foreground">No source offers agents yet. Sources are in Settings → Sources.</p>
    {/if}
    {#if error}<p class="text-danger" data-testid="source-agents-error">{error}</p>{/if}
    <p class="text-xs"><a href={href({ view: "discover" })} onclick={() => (open = false)}>See all in Discover</a>, with what each one does.</p>
  </div>
</Dialog>
