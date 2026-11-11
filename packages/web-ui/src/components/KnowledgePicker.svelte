<script lang="ts">
  // Pick the knowledge folders (D.5) an agent gets, read-only at /notes/<name>: folders of the
  // daemon's knowledge root (HANDLER_KNOWLEDGE_DIR). The agent form's Notes row: the folders as
  // chips, the list behind + Add.
  import PickRow from "./PickRow.svelte";
  import PickerChips from "./PickerChips.svelte";
  import { api } from "../lib/api";
  import type { KnowledgeListing } from "../lib/contracts.gen";

  let {
    value = $bindable([]),
  }: {
    value?: string[]; // the selected folders, relative to the knowledge root
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

  // a selected folder includes its sub-folders: they cannot be selected on their own
  function covered(folder: string): boolean {
    return value.some((v) => v !== folder && folder.startsWith(v + "/"));
  }

  function toggle(folder: string, checked: boolean): void {
    const rest = value.filter((v) => v !== folder && !v.startsWith(folder + "/"));
    value = checked ? [...rest, folder] : rest;
  }
</script>

{#snippet options()}
  {#each listing?.folders ?? [] as folder (folder)}
    <PickRow
      name={folder.split("/").at(-1) ?? folder}
      badge={covered(folder) ? "with its parent" : ""}
      depth={depth(folder)}
      checked={value.includes(folder) || covered(folder)}
      disabled={covered(folder)}
      onchange={(checked) => toggle(folder, checked)}
      testid="knowledge-option"
    />
  {/each}
{/snippet}

<PickerChips chips={value.map((f) => ({ key: f, name: f }))} onremove={(f) => (value = value.filter((v) => v !== f))} label="Add notes" testid="knowledge-picker">
  {#snippet list()}
    <div class="divide-y">
      {@render options()}
      {#if listing && !listing.folders.length}<p class="px-3 py-2 text-xs text-muted-foreground">No notes yet: folders of <code>{listing.root}</code>.</p>{/if}
    </div>
  {/snippet}
</PickerChips>
{#if error}<p class="text-sm text-danger">{error}</p>{/if}
