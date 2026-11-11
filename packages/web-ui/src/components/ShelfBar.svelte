<script lang="ts">
  // A Library shelf's first line: its filters, and its actions on the right. (Yours or Get more
  // is in the Library's header, at the right of the tabs.) Nothing when it has neither.
  import type { Snippet } from "svelte";

  let { filters, actions }: { filters?: Snippet; actions?: Snippet } = $props();
</script>

{#if filters || actions}
  <div class="flex flex-wrap items-center gap-2" data-testid="shelf-bar">
    {@render filters?.()}
    {#if actions}<div class="ml-auto flex flex-wrap items-center gap-1.5">{@render actions()}</div>{/if}
  </div>
{/if}
