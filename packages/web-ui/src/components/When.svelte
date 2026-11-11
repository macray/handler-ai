<script lang="ts">
  // A time as everywhere in the UI: how long ago (or how soon), the exact time on hover.
  import { ago, exactTime } from "../lib/agents";

  let { at }: { at: string | null | undefined } = $props();
</script>

{#if at}<time datetime={at} title={exactTime(at)}>{ago(at)}</time>{:else}never{/if}
