<script lang="ts">
  // Pick the notes folders (D.5; knowledge in the code) an agent gets at /notes/<name>: folders
  // of the notes root. The agent form's Notes row: the folders as chips, the list behind + Add;
  // then, for an agent program, each folder's Can write switch, amber: read-write weakens the
  // sandbox (the agent can change or delete any file there). The model alone only reads.
  import PickRow from "./PickRow.svelte";
  import PickerChips from "./PickerChips.svelte";
  import Switch from "./Switch.svelte";
  import { api } from "../lib/api";
  import type { KnowledgeFolderUse, KnowledgeListing } from "../lib/contracts.gen";

  let {
    value = $bindable([]),
    readOnly = false,
  }: {
    value?: KnowledgeFolderUse[]; // the selected folders, relative to the notes root
    readOnly?: boolean; // the model alone: no sandbox to write from
  } = $props();

  let listing = $state<KnowledgeListing | null>(null);
  let error = $state<string | null>(null);

  $effect(() => {
    api.knowledge().then(
      (l) => (listing = l),
      (e: Error) => (error = e.message),
    );
  });

  const depth = (folder: string) => folder.split("/").length - 1;
  const picked = $derived(value.map((u) => u.folder));
  const writes = (u: KnowledgeFolderUse) => u.access === "write";

  // a selected folder includes its sub-folders: they cannot be selected on their own
  function covered(folder: string): boolean {
    return picked.some((v) => v !== folder && folder.startsWith(v + "/"));
  }

  function toggle(folder: string, checked: boolean): void {
    const rest = value.filter((u) => u.folder !== folder && !u.folder.startsWith(folder + "/"));
    value = checked ? [...rest, { folder, access: "read" }] : rest;
  }

  function setAccess(folder: string, write: boolean): void {
    value = value.map((u) => (u.folder === folder ? { ...u, access: write ? "write" : "read" } : u));
  }
</script>

{#snippet options()}
  {#each listing?.folders ?? [] as folder (folder)}
    <PickRow
      name={folder.split("/").at(-1) ?? folder}
      badge={covered(folder) ? "with its parent" : ""}
      depth={depth(folder)}
      checked={picked.includes(folder) || covered(folder)}
      disabled={covered(folder)}
      onchange={(checked) => toggle(folder, checked)}
      testid="knowledge-option"
    />
  {/each}
{/snippet}

<div class="space-y-2">
  <PickerChips
    chips={value.map((u) => ({ key: u.folder, name: u.folder }))}
    onremove={(f) => (value = value.filter((u) => u.folder !== f))}
    label="Add notes"
    testid="knowledge-picker"
  >
    {#snippet list()}
      <div class="divide-y">
        {@render options()}
        {#if listing && !listing.folders.length}<p class="px-3 py-2 text-xs text-muted-foreground">No notes yet: folders of <code>{listing.root}</code>.</p>{/if}
      </div>
    {/snippet}
  </PickerChips>
  {#if !readOnly && value.length}
    <ul class="space-y-1.5" data-testid="knowledge-access">
      {#each value as u (u.folder)}
        <li class="flex items-center gap-3 text-sm {writes(u) ? 'text-warn' : ''}">
          <span class="min-w-0 truncate font-medium">{u.folder}</span>
          <span class="text-xs {writes(u) ? '' : 'text-muted-foreground'}">{writes(u) ? "can change or delete any file there" : "reads only"}</span>
          <span class="ml-auto"></span>
          <span class="text-xs text-muted-foreground">Can write</span>
          <Switch checked={writes(u)} onchange={(on) => setAccess(u.folder, on)} warn label="Can write in {u.folder}" testid="knowledge-write" />
        </li>
      {/each}
    </ul>
  {/if}
</div>
{#if error}<p class="text-sm text-danger">{error}</p>{/if}
