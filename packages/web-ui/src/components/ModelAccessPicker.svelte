<script lang="ts">
  // What an agent runs as (contract E): one of the accounts (it brings its harness) or one of the
  // providers (then the harness that talks to it, among those that speak its protocol), and the
  // model. Accounts and providers are made in Settings → Model access.
  import { productName } from "../lib/harnesses.svelte";
  import { api } from "../lib/api";
  import type { ModelAccess } from "../lib/access";
  import type { AccountInfo, ProviderInfo } from "../lib/contracts.gen";
  import { allows } from "../lib/contexts.svelte";
  import { href } from "../lib/router.svelte";
  import ContextTag from "./ContextTag.svelte";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import * as NativeSelect from "$lib/components/ui/native-select";

  // context: its project's (D.19): the accounts and providers not made for it cannot be picked
  let { value = $bindable(), context = null }: { value: ModelAccess; context?: string | null } = $props();

  let accounts = $state<AccountInfo[]>([]);
  let providers = $state<ProviderInfo[]>([]);
  let loaded = $state(false);
  let error = $state<string | null>(null);

  Promise.all([api.accounts(), api.providers()]).then(
    ([a, p]) => {
      accounts = a.filter((x) => x.status !== "invalid");
      providers = p.filter((x) => x.status !== "invalid" && (x.harnesses?.length ?? 0) > 0);
      loaded = true;
    },
    (e: Error) => (error = e.message),
  );

  const provider = $derived(providers.find((p) => p.name === value.provider));

  // nothing chosen yet: the only one ready, else the only one there is (not ready: no login, no
  // key; its session would not start). With two or more, the person chooses: never the wrong
  // account ("pro" and "perso") by default.
  $effect(() => {
    if (!loaded || value.account || value.provider) return;
    const readyAccounts = accounts.filter((a) => a.status === "ready" && allows(context, a.contexts));
    const readyProviders = providers.filter((p) => p.status === "ready" && allows(context, p.contexts));
    const [someAccounts, someProviders] = readyAccounts.length + readyProviders.length ? [readyAccounts, readyProviders] : [accounts, providers];
    if (someAccounts.length + someProviders.length !== 1) return;
    if (someAccounts[0]) pickAccount(someAccounts[0]);
    else if (someProviders[0]) pickProvider(someProviders[0]);
  });

  function pickAccount(a: AccountInfo): void {
    value = { harness: a.harness ?? null, account: a.name, provider: null, model: value.account === a.name ? value.model : null };
  }

  function pickProvider(p: ProviderInfo): void {
    const harnesses = p.harnesses ?? [];
    const harness = value.harness && harnesses.includes(value.harness) ? value.harness : (harnesses[0] ?? null);
    value = { harness, account: null, provider: p.name, model: value.provider === p.name ? value.model : null };
  }

  const card = "flex cursor-pointer flex-col items-start gap-0.5 rounded-lg border bg-card p-2.5 text-left text-sm transition-colors hover:border-foreground/30";
  const selected = "border-primary ring-1 ring-primary";
</script>

<div class="space-y-3" data-testid="model-access">
  <div class="grid grid-cols-[repeat(auto-fill,minmax(13rem,1fr))] gap-2" role="radiogroup" aria-label="model access">
    {#each accounts as a (a.name)}
      {@const allowed = allows(context, a.contexts)}
      <button type="button" role="radio" aria-checked={value.account === a.name} disabled={!allowed} class="{card} {value.account === a.name ? selected : ''} {allowed ? '' : 'cursor-not-allowed opacity-50'}" onclick={() => pickAccount(a)} data-testid="access-account">
        <span class="flex items-center gap-1.5 font-medium">{a.name}{#each a.contexts ?? [] as c (c)}<ContextTag name={c} />{/each}</span>
        <span class="text-xs text-muted-foreground">account · {productName(a.harness ?? "?")}{a.plan ? ` · ${a.plan}` : ""}</span>
        {#if !allowed}<span class="text-xs text-muted-foreground">not for {context} projects</span>
        {:else if a.status !== "ready"}<span class="text-xs text-warn">{(a.problems ?? []).join("; ") || "not logged in"}</span>{/if}
      </button>
    {/each}
    {#each providers as p (p.name)}
      {@const allowed = allows(context, p.contexts)}
      <button type="button" role="radio" aria-checked={value.provider === p.name} disabled={!allowed} class="{card} {value.provider === p.name ? selected : ''} {allowed ? '' : 'cursor-not-allowed opacity-50'}" onclick={() => pickProvider(p)} data-testid="access-provider">
        <span class="flex items-center gap-1.5 font-medium">{p.name}{#each p.contexts ?? [] as c (c)}<ContextTag name={c} />{/each}</span>
        <span class="text-xs text-muted-foreground">provider · {(p.harnesses ?? []).join(", ")}</span>
        {#if !allowed}<span class="text-xs text-muted-foreground">not for {context} projects</span>
        {:else if p.status !== "ready"}<span class="text-xs text-warn">{(p.problems ?? []).join("; ") || "incomplete"}</span>{/if}
      </button>
    {/each}
  </div>
  {#if loaded && !accounts.length && !providers.length}
    <p class="text-xs text-warn">
      No account or provider yet: add one in <a class="text-link hover:underline" href={href({ view: "settings", section: "models" })}>Settings → Model access</a>.
    </p>
  {/if}
  {#if loaded && !value.account && !value.provider && accounts.length + providers.length > 1}
    <p class="text-xs text-muted-foreground" data-testid="access-choose">Choose which one it runs as.</p>
  {/if}
  {#if error}<p class="text-xs text-danger">{error}</p>{/if}

  <div class="flex flex-wrap items-center gap-x-4 gap-y-2">
    {#if provider}
      <div class="flex items-center gap-2">
        <Label for="access-harness" class="text-xs">Agent program</Label>
        <NativeSelect.Root id="access-harness" class="w-40" bind:value={value.harness} data-testid="access-harness">
          {#each provider.harnesses ?? [] as h (h)}<NativeSelect.Option value={h}>{productName(h)}</NativeSelect.Option>{/each}
        </NativeSelect.Root>
      </div>
    {/if}
    <div class="flex items-center gap-2">
      <Label for="access-model" class="text-xs">Model</Label>
      {#if provider}
        <NativeSelect.Root id="access-model" class="w-56" value={value.model ?? ""} onchange={(e) => (value.model = e.currentTarget.value || null)} data-testid="access-model">
          <NativeSelect.Option value="">{provider.models?.[0]?.id ?? "its first model"} (its default)</NativeSelect.Option>
          {#each (provider.models ?? []).slice(1) as m (m.id)}<NativeSelect.Option value={m.id}>{m.name ?? m.id}</NativeSelect.Option>{/each}
        </NativeSelect.Root>
      {:else}
        <Input
          id="access-model"
          class="h-8 w-56 font-mono text-xs placeholder:font-sans"
          placeholder="its default model"
          value={value.model ?? ""}
          oninput={(e) => (value.model = e.currentTarget.value.trim() || null)}
          data-testid="access-model"
        />
      {/if}
    </div>
  </div>
</div>
