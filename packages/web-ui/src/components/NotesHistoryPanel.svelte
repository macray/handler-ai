<script lang="ts">
  // The history of a folder others write (D.5: a read-write notes folder, an app's folder): what
  // changed, one entry per lapse (~5 min), newest first, titled by who could write then. Each
  // entry says its first files and what changed in them ("added 2 lines under Platform", from
  // handlerd), and opens (chevron, the whole row a button) to its files' lines, the raw diff
  // folded, and "Undo this change": you see what you undo. Undo puts its files back as they were
  // before it (what the folder holds now is kept in the history first, so an undo can be
  // undone). Nothing shown for a folder no agent nor app was given read-write (no history: 404).
  // `folder`: a notes folder relative to the root, or an app's folder's full path; `name` titles
  // it ("History of ~/cv"), `path` its tooltip, `says` the line under it. Each entry: NotesChange.
  import History from "@lucide/svelte/icons/history";
  import Check from "@lucide/svelte/icons/check";
  import { Button } from "$lib/components/ui/button";
  import NotesChange from "./NotesChange.svelte";
  import { api, ApiError } from "../lib/api";
  import type { NotesHistory } from "../lib/contracts.gen";

  let {
    folder,
    name = `notes/${folder}`,
    path,
    says = "Each change your agents make here is kept. Open one to see its lines or undo it.",
  }: { folder: string; name?: string; path?: string; says?: string } = $props();

  const SHOWN = 10; // entries before "Show older changes"

  let history = $state<NotesHistory | null>(null);
  let all = $state(false); // older changes shown
  let error = $state<string | null>(null);
  let told = $state<string | null>(null);

  const commits = $derived(history ? (all ? history.commits : history.commits.slice(0, SHOWN)) : []);

  async function load(f: string): Promise<void> {
    try {
      history = await api.notesHistory(f);
    } catch (e) {
      history = null;
      if (!(e instanceof ApiError && e.status === 404)) error = (e as Error).message;
    }
  }

  $effect(() => {
    const f = folder;
    error = told = null;
    void load(f);
  });
</script>

{#if history}
  <section class="space-y-2" aria-label="history" data-testid="notes-history">
    <div class="px-1">
      <h2 class="flex items-center gap-2 font-semibold" title={path}><History class="size-4 text-muted-foreground" />History of {name}</h2>
      <p class="text-[13px] text-muted-foreground">{says}</p>
    </div>
    {#if error}<p class="text-sm text-danger" data-testid="notes-history-error">{error}</p>{/if}
    {#if told}<p class="flex items-center gap-1.5 text-sm text-ok" data-testid="notes-history-told"><Check class="size-4" />{told}</p>{/if}
    <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
      {#each commits as c (c.id)}
        <li><NotesChange {folder} commit={c} ondone={(t) => ((told = t), void load(folder))} /></li>
      {/each}
    </ul>
    {#if !all && history.commits.length > SHOWN}
      <Button variant="ghost" size="sm" onclick={() => (all = true)} data-testid="notes-older">Show older changes</Button>
    {/if}
  </section>
{/if}
