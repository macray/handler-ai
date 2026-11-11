<script lang="ts">
  // What a picker holds, as chips on one line (the agent form's Tools, Skills, Notes): each picked
  // one removable (×), those given by its project locked, then + Add, opening the picker's list.
  import Lock from "@lucide/svelte/icons/lock";
  import Plus from "@lucide/svelte/icons/plus";
  import X from "@lucide/svelte/icons/x";
  import type { Snippet } from "svelte";
  import Popover from "./Popover.svelte";

  export type Chip = { key: string; name: string; as?: string; locked?: string };

  let {
    chips,
    onremove,
    label,
    testid,
    list,
  }: {
    chips: Chip[];
    onremove: (key: string) => void;
    label: string; // what the list adds, for its panel: "Add a tool"
    testid: string;
    list: Snippet; // the picker's rows
  } = $props();

  let open = $state(false);
</script>

<div class="flex min-h-8 flex-wrap items-center gap-1.5" data-testid={testid}>
  {#each chips as c (c.key)}
    <span class="inline-flex h-7 items-center gap-1.5 rounded-md border bg-card px-2 text-xs" title={c.locked} data-testid="{testid}-chip">
      {#if c.locked}<Lock class="size-3 text-muted-foreground" />{/if}
      <span class="font-medium">{c.name}</span>
      {#if c.as}<span class="text-muted-foreground">as</span><span class="font-mono">{c.as}</span>{/if}
      {#if !c.locked}
        <button type="button" class="-mr-0.5 cursor-pointer rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground" aria-label="Remove {c.name}" onclick={() => onremove(c.key)}>
          <X class="size-3" />
        </button>
      {/if}
    </span>
  {/each}
  <Popover bind:open {label} width="26rem" testid="{testid}-list">
    {#snippet trigger(props)}
      <button type="button" class="inline-flex h-7 cursor-pointer items-center gap-1 rounded-md px-1.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground" {...props} data-testid="{testid}-add">
        <Plus class="size-3.5" />Add
      </button>
    {/snippet}
    {#snippet children()}
      <div class="max-h-80 overflow-y-auto">{@render list()}</div>
    {/snippet}
  </Popover>
</div>
