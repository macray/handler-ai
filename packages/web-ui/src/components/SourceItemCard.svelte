<script lang="ts">
  // One thing a source offers (D.26), as Discover shows it: its kind, where it comes from (Handler's
  // in the accent, a source you added in grey), what it does in a few words (what weakens the
  // sandbox in amber, first), and its button: Install, Get it (a new version of one you have),
  // Set up… (agents), or Installed. Its name opens its page.
  import AppWindow from "@lucide/svelte/icons/app-window";
  import Bot from "@lucide/svelte/icons/bot";
  import CircleCheck from "@lucide/svelte/icons/circle-check";
  import GitFork from "@lucide/svelte/icons/git-fork";
  import Puzzle from "@lucide/svelte/icons/puzzle";
  import ShieldCheck from "@lucide/svelte/icons/shield-check";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import { Button } from "$lib/components/ui/button";
  import type { Source, SourceItem } from "../lib/contracts.gen";
  import { href } from "../lib/router.svelte";
  import { actionWords, fromWords, itemRoute, type OfferedKind } from "../lib/sources";

  let { source, item, busy, ontake }: { source: Source; item: SourceItem; busy: boolean; ontake: () => void } = $props();

  const KIND = { app: { icon: AppWindow, tile: "bg-primary/10 text-primary" }, agents: { icon: Bot, tile: "bg-sky-500/10 text-sky-700 dark:text-sky-300" }, addon: { icon: Puzzle, tile: "bg-muted text-muted-foreground" } };
  const kind = $derived(KIND[item.kind as OfferedKind]);
  const action = $derived(actionWords(item));
  const label = $derived(item.kind === "app" ? `App · ${item.version}` : item.kind === "agents" ? `Agents · version ${item.version}` : "Tool");
</script>

<li class="flex flex-col gap-3 rounded-xl border bg-card p-4 shadow-panel" data-testid="discover-item">
  <a class="flex items-center gap-3 text-foreground no-underline" href={href(itemRoute(source, item))} data-testid="discover-item-open">
    <span class="flex size-11 shrink-0 items-center justify-center rounded-xl {kind.tile}"><kind.icon class="size-5" /></span>
    <span class="min-w-0">
      <span class="block truncate font-semibold">{item.name}</span>
      <span class="fact block">{label}</span>
    </span>
  </a>
  {#if item.description}<p class="text-sm text-muted-foreground">{item.description}</p>{/if}
  <div class="flex flex-wrap gap-1.5">
    {#if source.official}
      <span class="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-xs text-primary"><ShieldCheck class="size-3" />from Handler</span>
    {:else}
      <span class="inline-flex items-center gap-1 rounded-full border bg-muted px-2 py-0.5 text-xs text-muted-foreground" title="A source you added: Handler does not check it"><GitFork class="size-3" />{fromWords(source)}</span>
    {/if}
    {#each (item.notes ?? []).slice(0, 2) as n (n.text)}
      {#if n.weakens}
        <span class="inline-flex items-center gap-1 rounded-full bg-warn/10 px-2 py-0.5 text-xs text-warn"><TriangleAlert class="size-3" />{n.text}</span>
      {:else}
        <span class="rounded-full border px-2 py-0.5 text-xs text-muted-foreground">{n.text}</span>
      {/if}
    {/each}
  </div>
  <div class="mt-auto flex items-center justify-end gap-2">
    {#if item.update}<span class="mr-auto rounded-md bg-primary/10 px-1.5 py-0.5 text-xs text-primary">a new version of yours</span>{/if}
    {#if action}
      <Button size="sm" variant="outline" disabled={busy} onclick={ontake} data-testid="discover-item-take">{action}</Button>
    {:else}
      <span class="inline-flex items-center gap-1 text-xs text-ok" data-testid="discover-item-installed"><CircleCheck class="size-3.5" />Installed</span>
    {/if}
  </div>
</li>
