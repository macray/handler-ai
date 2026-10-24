<script lang="ts">
  // The secrets handler uses (D.14, E3): the keys and tokens of accounts, providers, addon
  // configurations and apps, kept by handler or where the person keeps them, grouped by what
  // they belong to. For each: where its value is, and how agents get it, as a badge: a stand-in
  // handler swaps for the value on the way to its hosts (hidden from them), or the value itself,
  // with why in its tooltip (a warning: what they read, they can send anywhere their network
  // allows). A value is changed where its owner is set (Change opens that page), the one place
  // for it; one nothing uses is forgotten here.
  import KeyRound from "@lucide/svelte/icons/key-round";
  import ShieldCheck from "@lucide/svelte/icons/shield-check";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import { Button } from "$lib/components/ui/button";
  import * as Tooltip from "$lib/components/ui/tooltip";
  import { api } from "../lib/api";
  import { ago } from "../lib/agents";
  import type { SecretInfo } from "../lib/contracts.gen";
  import { href } from "../lib/router.svelte";
  import { GROUPS, group, ownerHref, removable, slot, source } from "../lib/secrets";

  let secrets = $state<SecretInfo[] | null>(null);
  let error = $state<string | null>(null);
  let busy = $state(false);

  const load = () =>
    api.secrets().then(
      (list) => (secrets = list),
      (e: Error) => (error = e.message),
    );
  void load();

  async function run(action: () => Promise<unknown>): Promise<void> {
    busy = true;
    error = null;
    try {
      await action();
      await load();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  function remove(s: SecretInfo): void {
    if (!confirm(`Forget ${s.path}? Nothing uses it; its value is deleted.`)) return;
    void run(() => api.deleteSecret(s.path));
  }

  const readable = $derived((secrets ?? []).filter((s) => s.visible && s.usedBy?.length));
  const groups = $derived(GROUPS.map((g) => ({ ...g, list: (secrets ?? []).filter((s) => group(s) === g.id) })).filter((g) => g.list.length));
</script>

{#snippet badge(s: SecretInfo)}
  {#if s.usedBy?.length && (s.visible || s.hosts?.length)}
    <Tooltip.Root>
      <Tooltip.Trigger>
        {#snippet child({ props })}
          {#if s.visible}
            <button type="button" {...props} class="inline-flex items-center gap-1 rounded-md bg-warn/10 px-1.5 py-0.5 text-xs text-warn" data-testid="secret-visible">
              <TriangleAlert class="size-3" />agents can read it
            </button>
          {:else}
            <button type="button" {...props} class="inline-flex items-center gap-1 rounded-md bg-ok/10 px-1.5 py-0.5 text-xs text-ok" data-testid="secret-hidden">
              <ShieldCheck class="size-3" />hidden from agents
            </button>
          {/if}
        {/snippet}
      </Tooltip.Trigger>
      <Tooltip.Content class="max-w-sm">
        {#if s.visible}
          Agents read the value itself: {s.visible}. What an agent can read, it can send anywhere its network allows.
        {:else}
          Agents hold a stand-in; Handler puts the value in their requests to {s.hosts?.join(", ")} only.
          {#if s.lastSent}Last added {ago(s.lastSent.t)} to {s.lastSent.host}.{/if}
        {/if}
      </Tooltip.Content>
    </Tooltip.Root>
  {/if}
{/snippet}

<section class="space-y-10" data-testid="secrets">
  <div class="space-y-4">
    <p class="max-w-2xl text-sm text-muted-foreground">
      The keys and tokens of your accounts, providers, addon configurations and apps. Agents never see them: they hold a stand-in, and Handler puts
      the real value in their requests to the secret's hosts only. Where that cannot work, the agent reads the value itself, and its line says so.
    </p>
    {#if readable.length}
      <p class="flex max-w-2xl items-start gap-2.5 rounded-[10px] border border-warn/40 bg-warn/5 px-4 py-3 text-sm text-warn" data-testid="secrets-readable">
        <TriangleAlert class="mt-0.5 size-4 shrink-0" />
        <span>
          {readable.length === 1 ? "One secret is" : `${readable.length} secrets are`} readable by the agents given {readable.length === 1
            ? "it"
            : "them"}: what an agent can read, it can send anywhere its network allows.
        </span>
      </p>
    {/if}
  </div>

  {#if secrets && !secrets.length}
    <div class="rounded-[10px] border border-dashed px-6 py-10 text-center text-sm">
      <span class="mx-auto mb-3 flex size-10 items-center justify-center rounded-lg bg-muted text-muted-foreground"><KeyRound class="size-5" /></span>
      <p class="font-medium">No secret yet</p>
      <p class="mt-1 text-muted-foreground">
        They come with what you add: the token of an account and the key of a provider in
        <a class="text-link hover:underline" href={href({ view: "settings", section: "models" })}>Model access</a>, an addon's in
        <a class="text-link hover:underline" href={href({ view: "addons" })}>Addons</a>.
      </p>
    </div>
  {:else if secrets}
    <Tooltip.Provider delayDuration={150}>
      {#each groups as g (g.id)}
        <div class="space-y-3">
          <h2 class="text-base font-semibold">{g.label}</h2>
          <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
            {#each g.list as s (s.path)}
              <li class="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3.5" data-testid="secret">
                <span class="hidden size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground sm:flex"><KeyRound class="size-4" /></span>
                <div class="min-w-0 flex-1 basis-60 space-y-0.5">
                  <p class="flex flex-wrap items-center gap-2">
                    <span class="font-medium" data-testid="secret-title">{slot(s)}</span>
                    {@render badge(s)}
                  </p>
                  <p class="fact">
                    {s.path} · <span class={s.hasValue === false ? "text-warn" : ""} data-testid="secret-source">{source(s)}</span>
                  </p>
                </div>
                {#if s.usedBy?.length}
                  <Button variant="ghost" size="sm" class="ml-auto" href={ownerHref(s.usedBy[0]!)} data-testid="secret-change">Change</Button>
                {:else if removable(s)}
                  <Button variant="ghost" size="sm" class="ml-auto text-destructive hover:text-destructive" onclick={() => remove(s)} disabled={busy} data-testid="secret-remove"
                    >Forget</Button
                  >
                {/if}
              </li>
            {/each}
          </ul>
        </div>
      {/each}
    </Tooltip.Provider>
  {/if}
  {#if error}<p class="text-sm text-danger">{error}</p>{/if}
</section>
