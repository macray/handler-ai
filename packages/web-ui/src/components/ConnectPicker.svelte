<script lang="ts">
  // Every way to connect a model of a kind, or of both (a first run): the subscriptions the
  // harnesses log in to, then the APIs and the local model servers (hosted first), each a line
  // opening its form (AccountsSettings' start, ProvidersSettings' start). Model access shows it on
  // its page on a first run and in its Connect dialogs; ConnectDialogs over any page (E1).
  import type { Snippet } from "svelte";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import CreditCard from "@lucide/svelte/icons/credit-card";
  import KeyRound from "@lucide/svelte/icons/key-round";
  import Plus from "@lucide/svelte/icons/plus";
  import { Skeleton } from "$lib/components/ui/skeleton";
  import type { HarnessInfo, ProviderTemplate } from "../lib/contracts.gen";

  let {
    which,
    harnesses,
    templates,
    onaccount,
    onprovider,
  }: {
    which: "both" | "account" | "provider";
    harnesses: HarnessInfo[] | null; // null: not loaded yet
    templates: ProviderTemplate[];
    onaccount: (harness: string) => void; // a subscription picked: a new account of this harness
    onprovider: (template: ProviderTemplate | null) => void; // an API picked; null: another, by its address
  } = $props();

  const subscriptions = $derived((harnesses ?? []).filter((h) => h.login));
  // hosted APIs first, then the servers on this computer
  const apis = $derived([...templates].sort((a, b) => Number(!a.needsKey) - Number(!b.needsKey)));
  /** The harnesses that can use a provider made from it: the ones speaking one of its protocols. */
  const usedBy = (t: ProviderTemplate) =>
    (harnesses ?? [])
      .filter((h) => h.providerProtocols?.some((p) => p in t.endpoints))
      .map((h) => h.name)
      .join(", ");
</script>

{#snippet option(label: string, detail: string, mono: boolean, onclick: () => void, testid?: string)}
  <button type="button" class="group flex w-full items-center gap-3 px-3.5 py-2.5 text-left transition-colors hover:bg-muted/60" {onclick} data-testid={testid}>
    <span class="min-w-0 flex-1 truncate">{label}</span>
    {#if detail}<span class="min-w-0 max-w-[60%] truncate text-xs text-muted-foreground {mono ? 'font-mono' : ''}">{detail}</span>{/if}
    <ChevronRight class="size-4 shrink-0 text-muted-foreground/60 transition-transform group-hover:translate-x-0.5" />
  </button>
{/snippet}

{#snippet group(icon: typeof CreditCard, title: string, text: string, list: Snippet, headed: boolean)}
  {@const Icon = icon}
  <div class="space-y-3">
    {#if headed}
    <div class="flex items-start gap-3">
      <span class="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground"><Icon class="size-4" /></span>
      <div class="space-y-0.5">
        <h3 class="text-sm font-medium">{title}</h3>
        <p class="text-xs text-muted-foreground">{text}</p>
      </div>
    </div>
    {/if}
    <div class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm">{@render list()}</div>
  </div>
{/snippet}

<div class="grid gap-8 {which === 'both' ? 'sm:grid-cols-2' : ''}" data-testid="model-picker">
  {#snippet subscriptionList()}
    {#if harnesses === null}
      <div class="space-y-2 p-3"><Skeleton class="h-6 rounded-md" /><Skeleton class="h-6 rounded-md" /></div>
    {:else}
      {#each subscriptions as h (h.name)}
        {@render option(h.login?.subscription ?? h.name, h.product, false, () => onaccount(h.name), "connect-subscription")}
      {/each}
    {/if}
  {/snippet}
  {#snippet apiList()}
    {#each apis as t (t.name)}
      {@render option(t.description ?? t.name, usedBy(t), true, () => onprovider(t), "connect-api")}
    {/each}
    <button type="button" class="flex w-full items-center gap-2 px-3.5 py-2.5 text-left text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground" onclick={() => onprovider(null)}>
      <Plus class="size-4" />Another API: enter its address
    </button>
  {/snippet}
  {#if which !== "provider"}
    {@render group(CreditCard, "With a subscription you pay for", "A flat monthly price, with its usage limits. For your own use.", subscriptionList, which === "both")}
  {/if}
  {#if which !== "account"}
    {@render group(KeyRound, "With an API key or a local model", "Pay per use, or free with a model server on this computer.", apiList, which === "both")}
  {/if}
</div>
