<script lang="ts">
  // Model access: the two ways an agent's harness reaches a model, accounts (a subscription
  // logged in, D.9) and providers (an API and its key, or a model server on this computer, D.12).
  // One of either kind is enough to start. This page loads what both sections show, says whether
  // agents can run (said only when there is something to do: finish one, fix this computer, or
  // create a first project), and offers every way to connect a model: on the page on a first run,
  // then from the page's first line, one Connect per kind (never below the fold, however long the
  // lists), in a dialog: the Connect dialogs any page opens (ConnectDialogs, lib/connect), the
  // lists loaded again when one is made. On the page, each option opens its section's dialog.
  import Check from "@lucide/svelte/icons/check";
  import Plus from "@lucide/svelte/icons/plus";
  import { Button } from "$lib/components/ui/button";
  import { api } from "../lib/api";
  import { connect } from "../lib/connect.svelte";
  import type { AccountInfo, HarnessInfo, ProviderInfo, ProviderTemplate } from "../lib/contracts.gen";
  import { projects } from "../lib/projects.svelte";
  import { href } from "../lib/router.svelte";
  import { runtime } from "../lib/runtime.svelte";
  import AccountsSettings from "./AccountsSettings.svelte";
  import ConnectPicker from "./ConnectPicker.svelte";
  import LoadingCards from "./LoadingCards.svelte";
  import ProvidersSettings from "./ProvidersSettings.svelte";

  let accounts = $state<AccountInfo[] | null>(null); // null: not loaded yet
  let providers = $state<ProviderInfo[] | null>(null);
  let harnesses = $state<HarnessInfo[] | null>(null);
  let templates = $state<ProviderTemplate[]>([]);
  let error = $state<string | null>(null);
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

  // one made or changed in a Connect dialog (ConnectDialogs, opened by the page's Connects): listed again
  $effect(() => {
    if (!connect.changes) return;
    void loadAccounts();
    void loadProviders();
  });

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
</script>

{#if error}<p class="text-sm text-danger" data-testid="model-access-error">{error}</p>{/if}
{#if !loaded}
  <div class="grid grid-cols-[repeat(auto-fill,minmax(18rem,1fr))] gap-3"><LoadingCards /></div>
{:else if none}
  <div class="enter space-y-6">
    <div class="space-y-1">
      <h2 class="text-base font-semibold">Connect a model</h2>
      <p class="text-sm text-muted-foreground">Agents need a model to work. One is enough to start; you can add more later, of either kind.</p>
    </div>
    <ConnectPicker which="both" {harnesses} {templates} onaccount={(h) => accountsSection?.start(h)} onprovider={(t) => providersSection?.start(t)} />
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
      <Button variant="outline" size="sm" onclick={() => connect.open("account")} data-testid="add-account"><Plus />Connect a subscription</Button>
      <Button variant="outline" size="sm" onclick={() => connect.open("provider")} data-testid="add-provider"><Plus />Connect an API key or local model</Button>
    </div>
  {/if}
  <AccountsSettings bind:this={accountsSection} listed={!none} accounts={accounts ?? []} harnesses={harnesses ?? []} onchange={loadAccounts} />
  <ProvidersSettings bind:this={providersSection} listed={!none} providers={providers ?? []} onchange={loadProviders} />
{/if}
