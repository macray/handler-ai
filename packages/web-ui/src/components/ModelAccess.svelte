<script lang="ts">
  // Model access: the two ways an agent's harness reaches a model, accounts (a subscription
  // logged in, D.9) and providers (an API and its key, or a model server on this computer, D.12).
  // One of either kind is enough to start. This page loads what both sections show, says whether
  // agents can run (said only when there is something to do: finish one, fix this computer, or
  // create a first project), and offers every way to connect a model: on the page on a first run,
  // then from the page's first line, one Connect per kind (never below the fold, however long the
  // lists), in a dialog. Each option opens its section's dialog for a new account or provider.
  import type { Snippet } from "svelte";
  import Check from "@lucide/svelte/icons/check";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import CreditCard from "@lucide/svelte/icons/credit-card";
  import KeyRound from "@lucide/svelte/icons/key-round";
  import Plus from "@lucide/svelte/icons/plus";
  import { Button } from "$lib/components/ui/button";
  import { Skeleton } from "$lib/components/ui/skeleton";
  import { api } from "../lib/api";
  import type { AccountInfo, HarnessInfo, ProviderInfo, ProviderTemplate } from "../lib/contracts.gen";
  import { projects } from "../lib/projects.svelte";
  import { href } from "../lib/router.svelte";
  import { runtime } from "../lib/runtime.svelte";
  import AccountsSettings from "./AccountsSettings.svelte";
  import Dialog from "./Dialog.svelte";
  import LoadingCards from "./LoadingCards.svelte";
  import ProvidersSettings from "./ProvidersSettings.svelte";

  let accounts = $state<AccountInfo[] | null>(null); // null: not loaded yet
  let providers = $state<ProviderInfo[] | null>(null);
  let harnesses = $state<HarnessInfo[] | null>(null);
  let templates = $state<ProviderTemplate[]>([]);
  let error = $state<string | null>(null);
  let adding = $state<"account" | "provider" | null>(null); // a section's Add: its picker's dialog
  let accountsSection = $state<ReturnType<typeof AccountsSettings>>();
  let providersSection = $state<ReturnType<typeof ProvidersSettings>>();

  async function loadAccounts(): Promise<void> {
    try {
      accounts = await api.accounts();
    } catch (e) {
      error = (e as Error).message;
    }
  }
  async function loadProviders(): Promise<void> {
    try {
      [providers, templates] = await Promise.all([api.providers(), api.providerTemplates()]);
    } catch (e) {
      error = (e as Error).message;
    }
  }

  $effect(() => {
    void loadAccounts();
    void loadProviders();
    // slower to list (each image is inspected) and changed only by a rebuild: loaded once, apart
    api.harnesses().then(
      (list) => (harnesses = list),
      (e: Error) => (error = e.message),
    );
  });

  const loaded = $derived(accounts !== null && providers !== null);
  const none = $derived(loaded && !accounts?.length && !providers?.length);
  const ready = $derived(
    (accounts ?? []).filter((a) => a.status === "ready").length +
      (providers ?? []).filter((p) => p.status === "ready").length,
  );

  const subscriptions = $derived((harnesses ?? []).filter((h) => h.login));
  // hosted APIs first, then the servers on this computer
  const apis = $derived([...templates].sort((a, b) => Number(!a.needsKey) - Number(!b.needsKey)));
  /** The harnesses that can use a provider made from it: the ones speaking one of its protocols. */
  const usedBy = (t: ProviderTemplate) =>
    (harnesses ?? [])
      .filter((h) => h.providerProtocols?.some((p) => p in t.endpoints))
      .map((h) => h.name)
      .join(", ");

  /** An option picked: the picker closes, its section opens the new account's or provider's dialog. */
  function connect(begin: () => void): void {
    adding = null;
    begin();
  }
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

<!-- every way to connect a model of a kind, or of both on a first run -->
{#snippet picker(which: "both" | "account" | "provider")}
  <div class="grid gap-8 {which === 'both' ? 'sm:grid-cols-2' : ''}" data-testid="model-picker">
    {#snippet subscriptionList()}
      {#if harnesses === null}
        <div class="space-y-2 p-3"><Skeleton class="h-6 rounded-md" /><Skeleton class="h-6 rounded-md" /></div>
      {:else}
        {#each subscriptions as h (h.name)}
          {@render option(h.login?.subscription ?? h.name, h.product, false, () => connect(() => accountsSection?.start(h.name)), "connect-subscription")}
        {/each}
      {/if}
    {/snippet}
    {#snippet apiList()}
      {#each apis as t (t.name)}
        {@render option(t.description ?? t.name, usedBy(t), true, () => connect(() => providersSection?.start(t)), "connect-api")}
      {/each}
      <button type="button" class="flex w-full items-center gap-2 px-3.5 py-2.5 text-left text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground" onclick={() => connect(() => providersSection?.start(null))}>
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
{/snippet}

{#if error}<p class="text-sm text-danger" data-testid="model-access-error">{error}</p>{/if}
{#if !loaded}
  <div class="grid grid-cols-[repeat(auto-fill,minmax(18rem,1fr))] gap-3"><LoadingCards /></div>
{:else if none}
  <div class="enter space-y-6">
    <div class="space-y-1">
      <h2 class="text-base font-semibold">Connect a model</h2>
      <p class="text-sm text-muted-foreground">Agents need a model to work. One is enough to start; you can add more later, of either kind.</p>
    </div>
    {@render picker("both")}
  </div>
{:else if ready && runtime.blocked}
  <p class="rounded-[10px] border border-warn/40 bg-warn/5 px-4 py-3 text-sm text-warn" data-testid="model-access-ready">
    Ready on the model side, but agents can't run on this computer yet:
    <a class="text-link hover:underline" href={href({ view: "settings", section: "sandboxes" })}>see what to fix</a>.
  </p>
{:else if !ready}
  <p class="rounded-[10px] border border-warn/40 bg-warn/5 px-4 py-3 text-sm text-warn" data-testid="model-access-ready">
    Not ready yet: finish one below (its login, its token or its key).
  </p>
{:else if projects.loaded && !projects.list.length}
  <!-- ready, and nothing to run yet: the next step -->
  <p class="enter flex flex-wrap items-center gap-x-3 gap-y-1 rounded-[10px] border bg-card px-4 py-3 text-sm shadow-panel" data-testid="model-access-ready">
    <span class="flex items-center gap-2"><Check class="size-4 text-ok" />You're ready to run agents.</span>
    <a class="text-link hover:underline" href={href({ view: "edit-project" })}>Create a project and its agents →</a>
  </p>
{/if}
{#if loaded}
  {#if !none}
    <div class="flex flex-wrap gap-2" data-testid="model-access-actions">
      <Button variant="outline" size="sm" onclick={() => (adding = "account")} data-testid="add-account"><Plus />Connect a subscription</Button>
      <Button variant="outline" size="sm" onclick={() => (adding = "provider")} data-testid="add-provider"><Plus />Connect an API key or local model</Button>
    </div>
  {/if}
  <AccountsSettings bind:this={accountsSection} listed={!none} accounts={accounts ?? []} harnesses={harnesses ?? []} onchange={loadAccounts} />
  <ProvidersSettings bind:this={providersSection} listed={!none} providers={providers ?? []} onchange={loadProviders} />
  <Dialog
    bind:open={() => adding !== null, (v) => (v ? null : (adding = null))}
    title={adding === "provider" ? "Connect an API key or a local model" : "Connect a subscription"}
    description={adding === "provider" ? "An API and its key, or a model server on this computer." : "A subscription you pay for, for your own use."}
    testid="model-picker-dialog"
  >
    {#if adding}{@render picker(adding)}{/if}
  </Dialog>
{/if}
