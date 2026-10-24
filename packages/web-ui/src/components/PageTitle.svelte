<script lang="ts">
  // The title a page's content opens with (the top bar only places it): its name, what it is for.
  let { title, description }: { title: string; description?: string } = $props();
</script>

<div class="space-y-1.5">
  <h1 class="text-[1.75rem] leading-tight font-semibold tracking-[-0.022em]">{title}</h1>
  {#if description}<p class="max-w-2xl text-sm text-muted-foreground">{description}</p>{/if}
</div>
