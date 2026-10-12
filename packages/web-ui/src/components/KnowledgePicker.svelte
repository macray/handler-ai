<script lang="ts">
  // Pick the knowledge folders (D.5) an agent gets, read-only at /knowledge/<name>: folders of the
  // daemon's knowledge root (HANDLER_KNOWLEDGE_DIR). Used by the agent form.
  // Hidden when the root does not exist, so it costs nothing to people who do not use it.
  import PickRow from "./PickRow.svelte";
  import { Label } from "$lib/components/ui/label";
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

{#if error || listing?.folders.length}
  <div class="space-y-2" data-testid="knowledge-picker">
    <Label>Knowledge</Label>
    <p class="text-xs text-muted-foreground">
      Folders of <code>{listing?.root}</code> the agent can read, at <code>/knowledge/&lt;name&gt;</code>.
    </p>
    {#if error}<p class="text-sm text-danger">{error}</p>{/if}
    <div class="max-h-72 divide-y overflow-y-auto rounded-lg border bg-card">
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
    </div>
  </div>
{/if}
