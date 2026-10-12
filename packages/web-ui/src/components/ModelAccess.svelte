<script lang="ts">
  // Model access: the two ways an agent's harness reaches a model, accounts (a subscription
  // logged in, D.9) and providers (an API and its key, or a model server on this computer, D.12).
  // One of either kind is enough to start. This page loads what both sections show, says whether
  // agents can run, and offers every way to connect a model: open on a first run, behind a
  // button once there is one. Each option starts a new account or provider in its section.
  import Check from "@lucide/svelte/icons/check";
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
  import LoadingCards from "./LoadingCards.svelte";
  import ProvidersSettings from "./ProvidersSettings.svelte";

  let accounts = $state<AccountInfo[] | null>(null); // null: not loaded yet
  let providers = $state<ProviderInfo[] | null>(null);
  let harnesses = $state<HarnessInfo[] | null>(null);
  let templates = $state<ProviderTemplate[]>([]);
  let error = $state<string | null>(null);
  let picking = $state(false); // "Connect another model" open
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

  function connect(begin: () => void, section: string): void {
    picking = false;
    begin();
    requestAnimationFrame(() => document.getElementById(section)?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }
</script>

{#snippet picker()}
  <div class="space-y-4" data-testid="model-picker">
    <div class="space-y-1">
      <h2 class="text-base font-semibold">Connect a model</h2>
      <p class="text-sm text-muted-foreground">
        Agents need a model to work. One is enough to start; you can add more later, of either kind.
      </p>
    </div>
    <div class="grid gap-6 sm:grid-cols-2">
      <div class="space-y-3">
        <div class="space-y-0.5">
          <h3 class="flex items-center gap-2 text-sm font-medium"><CreditCard class="size-4 text-muted-foreground" />With a subscription you pay for</h3>
          <p class="text-xs text-muted-foreground">A flat monthly price, with its usage limits.</p>
        </div>
        <div class="space-y-1.5">
          {#if harnesses === null}
            <Skeleton class="h-8 rounded-md" /><Skeleton class="h-8 rounded-md" />
          {:else}
            {#each subscriptions as h (h.name)}
              <Button
                variant="outline"
                class="w-full justify-between"
                onclick={() => connect(() => accountsSection?.start(h.name), "accounts")}
                data-testid="connect-subscription"
              >
                {h.login?.subscription}<span class="text-xs text-muted-foreground">{h.product}</span>
              </Button>
            {/each}
          {/if}
        </div>
      </div>
      <div class="space-y-3">
        <div class="space-y-0.5">
          <h3 class="flex items-center gap-2 text-sm font-medium"><KeyRound class="size-4 text-muted-foreground" />With an API key or a local model</h3>
          <p class="text-xs text-muted-foreground">Pay per use, or free with a model server on this computer.</p>
        </div>
        <div class="space-y-1.5">
          {#each apis as t (t.name)}
            <Button
              variant="outline"
              class="w-full justify-between"
              onclick={() => connect(() => providersSection?.start(t), "providers")}
              data-testid="connect-api"
            >
              {t.description ?? t.name}<span class="truncate font-mono text-xs text-muted-foreground">{usedBy(t)}</span>
            </Button>
          {/each}
          <Button variant="outline" class="w-full justify-start border-dashed text-muted-foreground shadow-none" onclick={() => connect(() => providersSection?.start(null), "providers")}>
            Another API: enter its address
          </Button>
        </div>
      </div>
    </div>
  </div>
{/snippet}

{#if error}<p class="text-sm text-danger" data-testid="model-access-error">{error}</p>{/if}
{#if !loaded}
  <div class="grid grid-cols-[repeat(auto-fill,minmax(18rem,1fr))] gap-3"><LoadingCards /></div>
{:else if none}
  {@render picker()}
{:else}
  <div class="space-y-4">
    <div class="flex flex-wrap items-center justify-between gap-3">
      {#if ready && runtime.blocked}
        <p class="text-sm text-warn" data-testid="model-access-ready">
          Ready on the model side, but agents can't run on this computer yet:
          <a class="text-link hover:underline" href={href({ view: "settings", section: "images" })}>see what to fix</a>.
        </p>
      {:else if ready}
        <p class="flex items-center gap-2 text-sm" data-testid="model-access-ready">
          <Check class="size-4 text-ok" />You're ready: agents can run on {ready === 1 ? "it" : "them"}.
          {#if projects.loaded && !projects.list.length}
            <a class="text-link hover:underline" href={href({ view: "edit-project" })}>Create a project and its agents →</a>
          {/if}
        </p>
      {:else}
        <p class="text-sm text-warn" data-testid="model-access-ready">Not ready yet: finish one below (its login or its token, or its key).</p>
      {/if}
      <Button variant="outline" size="sm" onclick={() => (picking = !picking)} data-testid="connect-model">
        {#if picking}Close{:else}<Plus />Connect another model{/if}
      </Button>
    </div>
    {#if picking}<div class="rounded-lg border p-4">{@render picker()}</div>{/if}
  </div>
{/if}
{#if loaded}
  <AccountsSettings bind:this={accountsSection} accounts={accounts ?? []} harnesses={harnesses ?? []} onchange={loadAccounts} />
  <ProvidersSettings bind:this={providersSection} providers={providers ?? []} onchange={loadProviders} />
{/if}
