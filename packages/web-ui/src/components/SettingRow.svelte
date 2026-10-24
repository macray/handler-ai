<script lang="ts">
  // One setting on a settings page of rows: what it is on the left (its label, a sentence), its
  // control on the right. Rows of one group sit in one card, divided.
  import type { Snippet } from "svelte";

  let { label, hint, for: id, children, ...rest }: { label: string; hint?: string; for?: string; children: Snippet; [key: string]: unknown } = $props();
</script>

<div class="grid gap-x-5 gap-y-2 px-4 py-3.5 sm:grid-cols-[13rem_1fr]" {...rest}>
  <div>
    <label class="block text-sm font-medium" for={id}>{label}</label>
    {#if hint}<p class="mt-0.5 text-xs leading-snug text-muted-foreground">{hint}</p>{/if}
  </div>
  <div class="flex min-w-0 flex-col gap-1.5">{@render children()}</div>
</div>
