<script lang="ts">
  // The menu's button in a narrow window (below md the menu is a sheet, closed): on every page's
  // first line (PageHeader). It carries the bell's count, the bell itself being in the menu.
  import PanelLeft from "@lucide/svelte/icons/panel-left";
  import { useSidebar } from "$lib/components/ui/sidebar";
  import { bell } from "../lib/bell.svelte";

  let { class: className = "" }: { class?: string } = $props();
  const sidebar = useSidebar();
</script>

<button
  type="button"
  class="relative -ml-2.5 inline-flex size-11 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground md:hidden {className}"
  aria-label={bell.count ? `Open the menu, ${bell.count} waiting for you` : "Open the menu"}
  aria-expanded={sidebar.openMobile}
  onclick={() => sidebar.setOpenMobile(true)}
  data-testid="menu-button"
>
  <PanelLeft class="size-[18px]" />
  {#if bell.count}
    <span class="absolute top-1.5 right-1 min-w-4 rounded-full bg-warn px-1 font-mono text-[10px] leading-4 font-semibold text-background tabular-nums" aria-hidden="true">{bell.count}</span>
  {/if}
</button>
