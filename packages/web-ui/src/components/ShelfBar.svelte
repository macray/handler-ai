<script lang="ts">
  // A Library shelf's head: with `lists`, the segment Yours · n | Community · n (links, so the
  // browser's back goes between them) and a line saying which list you see, with a link to the
  // other (E6; not on Notes and Schemas); then its filters, and its actions on the right.
  // Nothing when it has none of them.
  import Globe from "@lucide/svelte/icons/globe";
  import User from "@lucide/svelte/icons/user";
  import type { Snippet } from "svelte";
  import { listsLine, type ShelfLists } from "../lib/library";
  import { href } from "../lib/router.svelte";

  let { lists, filters, actions }: { lists?: ShelfLists; filters?: Snippet; actions?: Snippet } = $props();

  const line = $derived(lists ? listsLine(lists.shelf, lists.more) : null);
</script>

{#if lists && line}
  <div class="flex flex-wrap items-center gap-3" data-testid="shelf-lists">
    <nav class="inline-flex shrink-0 rounded-lg bg-muted p-0.5 text-sm" aria-label="yours or community">
      {#each [{ more: false, label: "Yours", n: lists.yours, Icon: User }, { more: true, label: "Community", n: lists.community, Icon: Globe }] as o (o.label)}
        <a
          href={href({ view: "library", shelf: lists.shelf, more: o.more })}
          class="inline-flex items-center gap-1.5 rounded-md px-3 py-1 no-underline {o.more === lists.more ? 'bg-background font-medium text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}"
          aria-current={o.more === lists.more ? "page" : undefined}
          data-testid={o.more ? "shelf-more" : "shelf-yours"}><o.Icon class="size-3.5" />{o.label}{#if o.n !== undefined}&nbsp;· {o.n}{/if}</a
        >
      {/each}
    </nav>
    <p class="text-sm text-muted-foreground" data-testid="shelf-line">
      {line.text} <a class="text-link hover:underline" href={href({ view: "library", shelf: lists.shelf, more: !lists.more })} data-testid="shelf-line-link">{line.link}</a>.
    </p>
  </div>
{/if}
{#if filters || actions}
  <div class="flex flex-wrap items-center gap-2" data-testid="shelf-bar">
    {@render filters?.()}
    {#if actions}<div class="ml-auto flex flex-wrap items-center gap-1.5">{@render actions()}</div>{/if}
  </div>
{/if}
