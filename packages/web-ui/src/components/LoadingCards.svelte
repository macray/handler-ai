<script lang="ts">
  // Placeholder cards while a list loads, laid out in the list's own grid, so "none yet" is only
  // said once the daemon has answered.
  import { Skeleton } from "$lib/components/ui/skeleton";

  let { count = 2, height = "h-28" }: { count?: number; height?: string } = $props();
</script>

{#each { length: count }, i (i)}
  <Skeleton class="{height} rounded-lg" role="status" aria-label="Loading" data-testid="loading" />
{/each}
