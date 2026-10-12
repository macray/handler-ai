<script lang="ts">
  // The top bar of every page (Linear-style): sidebar toggle, breadcrumb, title, actions.
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import type { Snippet } from "svelte";
  import * as Sidebar from "$lib/components/ui/sidebar";
  import { Separator } from "$lib/components/ui/separator";

  let {
    title,
    parent,
    meta,
    actions,
    titled = false,
  }: {
    title: string;
    parent?: { label: string; href: string };
    meta?: Snippet; // next to the title (status, badges)
    actions?: Snippet; // right-aligned
    titled?: boolean; // the content opens with its PageTitle, the heading: here the title is only the breadcrumb's end
  } = $props();
</script>

<header class="flex h-12 shrink-0 items-center gap-2 border-b px-3">
  <Sidebar.Trigger class="text-muted-foreground" />
  <Separator orientation="vertical" class="mr-1 data-vertical:h-4 data-vertical:self-center" />
  {#if parent}
    <a href={parent.href} class="text-muted-foreground hover:text-foreground truncate text-sm no-underline max-sm:hidden">{parent.label}</a>
    <ChevronRight class="text-muted-foreground size-3.5 shrink-0 max-sm:hidden" />
  {/if}
  {#if titled}
    <span class="truncate text-sm font-medium">{title}</span>
  {:else}
    <h1 class="truncate text-sm font-medium">{title}</h1>
  {/if}
  {@render meta?.()}
  <div class="ml-auto flex shrink-0 items-center gap-1.5">{@render actions?.()}</div>
</header>
