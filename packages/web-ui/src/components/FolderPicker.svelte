<script lang="ts">
  // Pick a scope inside the work folders (server-side check: /v1/directories, D.13), or create a
  // new folder there (a new project). Browsing a folder chooses it. The work folders themselves
  // are listed by their full path; `used` folders (by another project) are marked.
  import { untrack } from "svelte";
  import { api } from "../lib/api";
  import type { DirectoryListing } from "../lib/contracts.gen";
  import CornerLeftUp from "@lucide/svelte/icons/corner-left-up";
  import Folder from "@lucide/svelte/icons/folder";
  import FolderPlus from "@lucide/svelte/icons/folder-plus";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";

  let {
    value = $bindable(""),
    used = {},
    id,
  }: {
    value: string;
    id?: string; // its path field's
    used?: Record<string, string>; // folder → the project using it
  } = $props();

  let listing = $state<DirectoryListing | null>(null);
  let error = $state<string | null>(null);
  let newName = $state<string | null>(null); // null: not creating a folder

  async function browse(path?: string): Promise<void> {
    error = null;
    try {
      listing = await api.directories(path);
      if (listing.path) value = listing.path;
    } catch (e) {
      error = (e as Error).message;
    }
  }

  async function create(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    const parent = listing?.path;
    if (!parent || !newName?.trim()) return;
    error = null;
    try {
      listing = await api.createDirectory({ parent, name: newName.trim() });
      if (listing.path) value = listing.path;
      newName = null;
    } catch (e) {
      error = (e as Error).message;
    }
  }

  // offer the work folders to start from, unless a folder is already chosen (e.g. editing)
  $effect(() => {
    if (!untrack(() => value)) void browse();
  });
</script>

<div class="space-y-2">
  <div class="flex flex-wrap gap-2">
    <Input {id} class="min-w-72 flex-1 font-mono text-xs" bind:value placeholder="/absolute/path/to/folder" aria-label="folder path" />
    <Button variant="outline" onclick={() => browse(value || undefined)}>Browse</Button>
    {#if listing?.path && newName === null}
      <Button variant="outline" onclick={() => (newName = "")} data-testid="new-folder"><FolderPlus />New folder…</Button>
    {/if}
  </div>
  {#if newName !== null}
    <form class="flex flex-wrap items-center gap-2" onsubmit={create}>
      <span class="font-mono text-xs text-muted-foreground">{listing?.path}/</span>
      <!-- svelte-ignore a11y_autofocus -->
      <Input class="w-48" bind:value={newName} placeholder="folder name" aria-label="new folder name" autofocus />
      <Button type="submit" disabled={!newName.trim()}>Create folder</Button>
      <Button variant="ghost" onclick={() => (newName = null)}>Cancel</Button>
    </form>
  {/if}
  {#if error}<p class="text-sm text-danger">{error}</p>{/if}
  {#if listing}
    <ul
      class="grid max-h-56 gap-px overflow-y-auto rounded-lg border bg-card p-1 {listing.path
        ? 'grid-cols-[repeat(auto-fill,minmax(12rem,1fr))]'
        : 'grid-cols-1'}"
    >
      {#if listing.parent}
        <li>
          <button type="button" class="entry" onclick={() => browse(listing?.parent ?? undefined)}><CornerLeftUp />..</button>
        </li>
      {/if}
      {#each listing.entries as entry (entry.path)}
        <li>
          <button type="button" class="entry" title={entry.path} onclick={() => browse(entry.path)}>
            <Folder /><span>{entry.name}</span>
            {#if used[entry.path]}<em>used by {used[entry.path]}</em>{/if}
          </button>
        </li>
      {:else}
        <li class="col-span-full px-2 py-1 text-xs text-muted-foreground">No sub-folders.</li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .entry {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    width: 100%;
    padding: 0.25rem 0.5rem;
    border-radius: 0.35rem;
    text-align: left;
    font-family: var(--mono);
    font-size: 0.8rem;
    cursor: pointer;
  }
  .entry span {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .entry em {
    flex: none;
    margin-left: auto;
    font-family: var(--font-sans);
    font-style: normal;
    font-size: 0.7rem;
    color: var(--muted-foreground);
  }
  .entry:hover {
    background: var(--accent);
  }
  .entry :global(svg) {
    width: 0.9rem;
    height: 0.9rem;
    flex: none;
    color: var(--muted-foreground);
  }
</style>
