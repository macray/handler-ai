<script lang="ts">
  // The Connect dialogs over any page (E1), mounted once in App, opened by lib/connect: first its
  // picker (one kind, or both on a first run), then the option's form, Model access's own
  // (AccountsSettings, ProvidersSettings, their lists not shown). The person stays on the page;
  // the one made is told to whoever opened it (a Who works picker chooses it), and the pages
  // listing accounts and providers load them again.
  import { untrack } from "svelte";
  import { api } from "../lib/api";
  import { connect, type ConnectKind } from "../lib/connect.svelte";
  import type { AccountInfo, HarnessInfo, ProviderInfo, ProviderTemplate } from "../lib/contracts.gen";
  import AccountsSettings from "./AccountsSettings.svelte";
  import ConnectPicker from "./ConnectPicker.svelte";
  import Dialog from "./Dialog.svelte";
  import ProvidersSettings from "./ProvidersSettings.svelte";

  let accounts = $state<AccountInfo[]>([]);
  let providers = $state<ProviderInfo[]>([]);
  let harnesses = $state<HarnessInfo[] | null>(null); // null: not loaded yet
  let templates = $state<ProviderTemplate[]>([]);
  let error = $state<string | null>(null);
  let picking = $state<ConnectKind | null>(null); // the picker shown; null once an option is picked
  let accountsForm = $state<ReturnType<typeof AccountsSettings>>();
  let providersForm = $state<ReturnType<typeof ProvidersSettings>>();

  async function loadAccounts(): Promise<void> {
    accounts = await api.accounts();
  }
  async function loadProviders(): Promise<void> {
    providers = await api.providers();
  }
  /** One changed in a form (made, logged in): here and on the pages listing them. */
  async function changed(load: () => Promise<void>): Promise<void> {
    await load();
    connect.changes++;
  }

  // a Connect opened: what its picker and forms need, loaded afresh
  $effect(() => {
    const kind = connect.current?.kind;
    if (!kind) return;
    untrack(() => {
      picking = kind;
      error = null;
      Promise.all([api.accounts(), api.providers(), api.providerTemplates()]).then(
        ([a, p, t]) => ((accounts = a), (providers = p), (templates = t)),
        (e: Error) => (error = e.message),
      );
      if (harnesses === null) api.harnesses().then((list) => (harnesses = list), (e: Error) => (error = e.message));
    });
  });

  /** An option picked: the picker closes, its form opens. */
  function pick(begin: () => void): void {
    picking = null;
    begin();
  }

  /** A form closed: what it made goes to the opener; nothing made, the Connect is over. */
  function closed(kind: "account" | "provider", made: string | null): void {
    if (!connect.current) return;
    if (made) connect.done({ kind, name: made });
    else connect.close();
  }

  const TITLE = { both: "Connect a model", account: "Connect a subscription", provider: "Connect an API key or a local model" };
  const TEXT = {
    both: "Agents need a model to work. One is enough to start; you can add the other kind later in Settings → Model access.",
    account: "A subscription you pay for, for your own use.",
    provider: "An API and its key, or a model server on this computer.",
  };
</script>

<Dialog
  bind:open={() => picking !== null, (v) => !v && picking !== null && ((picking = null), connect.close())}
  title={picking ? TITLE[picking] : ""}
  description={picking ? TEXT[picking] : undefined}
  wide={picking === "both"}
  testid="model-picker-dialog"
>
  {#if error}<p class="text-sm text-danger" data-testid="connect-error">{error}</p>{/if}
  {#if picking}
    <ConnectPicker
      which={picking}
      {harnesses}
      {templates}
      onaccount={(h) => pick(() => accountsForm?.start(h))}
      onprovider={(t) => pick(() => providersForm?.start(t))}
    />
  {/if}
</Dialog>
<AccountsSettings bind:this={accountsForm} dialogOnly listed={false} {accounts} harnesses={harnesses ?? []} onchange={() => changed(loadAccounts)} onclosed={(made) => closed("account", made)} />
<ProvidersSettings bind:this={providersForm} dialogOnly listed={false} {providers} onchange={() => changed(loadProviders)} onclosed={(made) => closed("provider", made)} />
