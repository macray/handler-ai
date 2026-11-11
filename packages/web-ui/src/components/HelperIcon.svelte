<script lang="ts">
  // The icon of a feature that needs a helper (lib/helpers.ts), on its tile.
  import Eye from "@lucide/svelte/icons/eye";
  import ListChecks from "@lucide/svelte/icons/list-checks";
  import RefreshCw from "@lucide/svelte/icons/refresh-cw";
  import Route from "@lucide/svelte/icons/route";
  import Sparkle from "@lucide/svelte/icons/sparkle";
  import WandSparkles from "@lucide/svelte/icons/wand-sparkles";
  import type { HelperIcon } from "../lib/helpers";

  let { icon, small = false }: { icon: HelperIcon; small?: boolean } = $props();
  const ICONS = { plans: ListChecks, ask: Route, improve: RefreshCw, apps: WandSparkles, "skill-write": Sparkle, "skill-review": Eye };
  const Icon = $derived(ICONS[icon]);
</script>

{#if small}
  <Icon class="size-3.5 shrink-0" />
{:else}
  <span class="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><Icon class="size-4" /></span>
{/if}
