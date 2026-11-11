<script lang="ts" module>
  import type { Component } from "svelte";
  export type PageTab = { label: string; href: string; active: boolean; count?: number; group?: string; icon?: Component; testid?: string };
</script>

<script lang="ts">
  // A page's own header, at the top of the page (there is no top bar): where it sits (a crumb line,
  // "Projects ›"; none for a place of the menu), its title, then its sections as underline tabs
  // (grouped when they are, the Library's: each group's label above its tabs, a rule between
  // groups; `tabsEnd` at the right of the tabs, the Library's Yours / Get more). The page's actions are its first
  // line, under the title or the tabs, never next to the sections; rare ones in its ⋯ (`menu`, at
  // the top right). No paragraph under the title: `sub` is a line of facts (a project's folder).
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import type { Snippet } from "svelte";
  import MenuButton from "./MenuButton.svelte";

  let {
    title,
    parent,
    meta,
    sub,
    menu,
    actions,
    tabs,
    tabsEnd,
    width = "max-w-6xl",
  }: {
    title: string;
    parent?: { label: string; href: string };
    meta?: Snippet; // next to the title (status, badges)
    sub?: Snippet; // under the title: its facts, on one line
    menu?: Snippet; // top right: the page's ⋯ (and its pin)
    actions?: Snippet; // the page's first line
    tabs?: PageTab[];
    tabsEnd?: Snippet; // at the right of the tabs
    width?: string; // the page's column, so the header lines up with it
  } = $props();

  // the tabs in runs of one group (one run, unlabelled, when they are not grouped)
  const groups = $derived(
    (tabs ?? []).reduce<{ label?: string; tabs: PageTab[] }[]>((all, tab) => {
      const last = all.at(-1);
      if (last && last.label === tab.group) last.tabs.push(tab);
      else all.push({ label: tab.group, tabs: [tab] });
      return all;
    }, []),
  );
</script>

<header class="shrink-0 {tabs?.length ? 'border-b' : ''}" data-testid="page-header">
  <div class="mx-auto w-full {width} px-8 pt-6 {tabs?.length ? '' : 'pb-2'}">
    <!-- the crumb line; in a narrow window it starts with the menu's button (there only, when the
         page has no crumb nor ⋯) -->
    <div class="{parent || menu ? 'flex' : 'flex md:hidden'} min-h-5 items-center gap-2 max-md:-my-2.5">
        <MenuButton />
        {#if parent}
          <nav class="flex min-w-0 items-center gap-1 text-[12.5px] text-muted-foreground" aria-label="breadcrumb">
            <a href={parent.href} class="min-w-0 truncate no-underline hover:text-foreground" data-testid="page-crumb">{parent.label}</a>
            <ChevronRight class="size-3 shrink-0" />
          </nav>
        {/if}
        {#if menu}<div class="-my-1 ml-auto flex items-center gap-0.5">{@render menu()}</div>{/if}
    </div>
    <div class="mt-0.5 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
      <h1 class="min-w-0 truncate text-[1.5rem] leading-tight font-semibold tracking-[-0.02em]">{title}</h1>
      {@render meta?.()}
    </div>
    {#if sub}<div class="mt-1 flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1 text-xs text-muted-foreground">{@render sub()}</div>{/if}
    {#if tabs?.length}
      <div class="-mb-px mt-3 flex flex-wrap items-end gap-x-5">
        <nav class="flex flex-wrap items-end gap-x-5" aria-label="sections">
          {#each groups as g, i (i)}
            {#if i}<span class="mb-2 h-8 w-px bg-border" aria-hidden="true"></span>{/if}
            <div class="flex flex-col gap-1">
              {#if g.label}<span class="text-[11px] font-semibold text-muted-foreground">{g.label}</span>{/if}
              <div class="flex gap-x-5">
                {#each g.tabs as tab (tab.href)}
                  <a
                    href={tab.href}
                    class="flex items-center gap-1.5 border-b-2 pb-2 text-sm no-underline {tab.active
                      ? 'border-primary font-medium text-foreground'
                      : 'border-transparent text-muted-foreground hover:text-foreground'}"
                    aria-current={tab.active ? "page" : undefined}
                    data-testid={tab.testid}
                    >{#if tab.icon}<tab.icon class="size-[15px]" />{/if}{tab.label}{#if tab.count}<span class="font-mono text-[11.5px] font-normal text-muted-foreground tabular-nums">{tab.count}</span>{/if}</a
                  >
                {/each}
              </div>
            </div>
          {/each}
        </nav>
        {#if tabsEnd}<div class="mb-2 ml-auto">{@render tabsEnd()}</div>{/if}
      </div>
    {/if}
  </div>
</header>
{#if actions}
  <div class="mx-auto flex w-full {width} shrink-0 flex-wrap items-center gap-1.5 px-8 pt-4" data-testid="page-actions">{@render actions()}</div>
{/if}
