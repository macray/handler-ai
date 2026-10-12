<script lang="ts">
  // The secrets handler uses (D.14, E3): the keys and tokens of accounts, providers, addon
  // configurations and apps, kept by handler or where the person keeps them. For each: what it
  // belongs to, where its value is, the agents that use it, and how they get it: a stand-in handler
  // swaps for the value on the way to its hosts (they never see it), or the value itself, with
  // why (a warning: what they read, they can send anywhere their network allows). A value kept by
  // handler is replaced here, unless its owner sets it (an account's login, an app's secret); one
  // nothing uses is removed here.
  import KeyRound from "@lucide/svelte/icons/key-round";
  import ShieldCheck from "@lucide/svelte/icons/shield-check";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { api } from "../lib/api";
  import { ago } from "../lib/agents";
  import type { SecretInfo } from "../lib/contracts.gen";
  import { ownerHref, owner, removable, replaceable, source, title } from "../lib/secrets";

  let secrets = $state<SecretInfo[] | null>(null);
  let error = $state<string | null>(null);
  let busy = $state(false);
  let editing = $state<string | null>(null); // the path whose value is being replaced
  let value = $state("");

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

  function replace(s: SecretInfo): void {
    void run(async () => {
      await api.setSecret(s.path, value.trim(), s.description);
      editing = null;
      value = "";
    });
  }

  function remove(s: SecretInfo): void {
    if (!confirm(`Forget ${s.path}? Nothing uses it; its value is deleted.`)) return;
    void run(() => api.deleteSecret(s.path));
  }

  const readable = $derived((secrets ?? []).filter((s) => s.visible && s.agents?.length));
</script>

<section class="space-y-6" data-testid="secrets">
  <p class="max-w-2xl text-sm text-muted-foreground">
    The keys and tokens of your accounts, providers, addon configurations and apps. Agents never see them: an agent holds a stand-in, and Handler
    puts the real value in its requests to the secret's hosts only, so a page or a file that tricks it cannot send the secret anywhere else.
    Where that cannot work, the agent reads the value itself; it is said below.
  </p>

  {#if readable.length}
    <div class="flex max-w-3xl items-start gap-2 rounded-md border border-warn/40 bg-warn/5 p-3 text-sm" data-testid="secrets-readable">
      <TriangleAlert class="mt-0.5 size-4 shrink-0 text-warn" />
      <p>
        {readable.length === 1 ? "One secret is" : `${readable.length} secrets are`} readable by the agents that use {readable.length === 1
          ? "it"
          : "them"}: what an agent can read, it can send anywhere its network allows.
      </p>
    </div>
  {/if}

  {#if secrets}
    <ul class="max-w-3xl divide-y rounded-lg border bg-card text-sm">
      {#each secrets as s (s.path)}
        <li class="space-y-1.5 px-3.5 py-3" data-testid="secret">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0 space-y-0.5">
              <div class="flex items-center gap-2">
                <KeyRound class="size-3.5 shrink-0 text-muted-foreground" />
                <span class="font-medium" data-testid="secret-title">{title(s)}</span>
              </div>
              <div class="text-xs text-muted-foreground">
                <span class="font-mono">{s.path}</span> ·
                <span class={s.hasValue === false ? "text-warn" : ""} data-testid="secret-source">{source(s)}</span>
              </div>
            </div>
            <div class="flex shrink-0 items-center gap-2">
              {#if replaceable(s) && editing !== s.path}
                <Button variant="outline" size="sm" onclick={() => ((editing = s.path), (value = ""))} disabled={busy} data-testid="secret-replace">
                  Replace
                </Button>
              {/if}
              {#if removable(s)}
                <Button variant="outline" size="sm" onclick={() => remove(s)} disabled={busy} data-testid="secret-remove">Forget</Button>
              {/if}
            </div>
          </div>

          {#if editing === s.path}
            <form class="flex gap-2" onsubmit={(e) => (e.preventDefault(), replace(s))}>
              <Input class="flex-1" type="password" placeholder="the new value" bind:value autocomplete="off" data-testid="secret-value" />
              <Button type="submit" size="sm" disabled={busy || !value.trim()} data-testid="secret-save">Save</Button>
              <Button variant="ghost" size="sm" onclick={() => (editing = null)}>Cancel</Button>
            </form>
          {/if}

          {#if s.usedBy?.length}
            {#if s.visible}
              <p class="flex items-start gap-1.5 text-xs text-warn" data-testid="secret-visible">
                <TriangleAlert class="mt-px size-3.5 shrink-0" />Agents can read it: {s.visible}.
              </p>
            {:else if s.hosts?.length}
              <p class="flex items-start gap-1.5 text-xs text-ok" data-testid="secret-hidden">
                <ShieldCheck class="mt-px size-3.5 shrink-0" /><span
                  >Hidden from agents: Handler adds it to their requests to <span class="font-mono">{s.hosts?.join(", ")}</span>.</span
                >
              </p>
            {/if}
            <p class="text-xs text-muted-foreground">
              {#if s.agents?.length}Used by {s.agents.join(", ")}{:else}No agent uses it yet{/if}
              {#if s.lastSent}· last added {ago(s.lastSent.t)} to <span class="font-mono">{s.lastSent.host}</span>{/if}
              · set in {#each s.usedBy as u, i (u)}{#if i}, {/if}<a class="text-link hover:underline" href={ownerHref(u)}>{owner(u).label}</a>{/each}
            </p>
          {:else}
            <p class="text-xs text-muted-foreground">Nothing uses it.</p>
          {/if}
        </li>
      {:else}
        <li class="px-3.5 py-3 text-muted-foreground">No secret yet: they come with the accounts, providers and addon configurations you add.</li>
      {/each}
    </ul>
  {/if}
  {#if error}<p class="text-sm text-danger">{error}</p>{/if}
</section>
