<script lang="ts">
  // Settings → Remote (D.7, docs/dev/design/remote.md): what it gives and what it needs (a gateway
  // you run: the steps, ticked as they are done; docs/user/phone.md in full), the gateway handler
  // polls, its light, and the paired devices, each yours or a family member's (apps only). Pairing
  // shows the device's key once, as a QR code whose URL carries it in the fragment (never sent to a
  // server).
  import When from "./When.svelte";
  import { Skeleton } from "$lib/components/ui/skeleton";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import type { RemotePairing } from "../lib/contracts.gen";
  import { LIGHT_LABEL, lightTone, remote } from "../lib/remote.svelte";
  import { ago } from "../lib/agents";
  import QrCode from "./QrCode.svelte";

  let url = $state("");
  let token = $state("");
  let editing = $state(false);
  let deviceName = $state("");
  let forFamily = $state(false); // the device is a family member's: apps only
  let person = $state(""); // that family member's name
  let pairing = $state<RemotePairing | null>(null);
  let error = $state<string | null>(null);
  let busy = $state(false);

  const status = $derived(remote.status);
  // the steps done: a gateway set (1, 2), a device paired (3)
  const connected = $derived(Boolean(status?.gatewayUrl));
  const paired = $derived(Boolean(status?.devices?.length));

  $effect(() => {
    remote.start();
  });

  async function run(action: () => Promise<unknown>): Promise<void> {
    busy = true;
    error = null;
    try {
      await action();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  function saveGateway(): Promise<void> {
    return run(async () => {
      await remote.setGateway(url, token);
      token = "";
      editing = false;
    });
  }

  function pair(): Promise<void> {
    return run(async () => {
      pairing = await remote.pair(deviceName || "phone", forFamily ? person.trim() : "owner");
      deviceName = "";
      person = "";
      forFamily = false;
    });
  }

  function revoke(id: string, name: string): void {
    if (confirm(`Revoke ${name}? It loses access at once; pairing it again needs a new QR code.`)) void run(() => remote.revoke(id));
  }
</script>

{#snippet number(n: number, done: boolean)}
  <span class="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full text-xs {done ? 'border border-ok text-ok' : 'bg-muted text-muted-foreground'}">
    {done ? "✓" : n}
  </span>
{/snippet}

<section class="space-y-4" data-testid="remote-settings">
  <div class="space-y-3">
    <p class="max-w-2xl text-sm text-muted-foreground">
      Use your sessions and mini apps from a phone or tablet, end-to-end encrypted. It goes through a <em>gateway</em>: a small
      server you run, which only relays encrypted messages. Optional.
    </p>
    <ol class="max-w-3xl space-y-2 text-sm" data-testid="remote-steps">
      <li class="flex gap-2.5">
        {@render number(1, connected)}
        <span><span class="font-medium">Run a gateway</span> on a machine your phone reaches over HTTPS, e.g. on your Tailscale
          network: <code>handler-gateway</code>, from Handler's <code>remote-gateway/</code> (a container, or <code>uv tool install</code>).</span>
      </li>
      <li class="flex gap-2.5">
        {@render number(2, connected)}
        <span><span class="font-medium">Connect this computer</span>: on the gateway, <code>handler-gateway add-host laptop</code> prints
          its host token, shown once. Enter the gateway's URL and that token below.</span>
      </li>
      <li class="flex gap-2.5">
        {@render number(3, paired)}
        <span><span class="font-medium">Pair a device</span> below (a QR code to scan), then turn on
          <span class="font-medium">Remote</span> in a session: the phone lists it.</span>
      </li>
    </ol>
  </div>

  <div class="space-y-3 rounded-lg border bg-card p-3.5 text-sm">
    <div class="flex flex-wrap items-center gap-2">
      <span class="size-2 shrink-0 rounded-full {lightTone(status?.light)}" aria-hidden="true"></span>
      <span data-testid="remote-light">{status ? LIGHT_LABEL[status.light] : "…"}</span>
      {#if status?.detail}<span class="text-danger">({status.detail})</span>{/if}
      {#if status?.since && status.light !== "off"}<span class="text-muted-foreground">· <When at={status.since} /></span>{/if}
      {#if status?.sharedSessions?.length}<span class="text-muted-foreground">· {status.sharedSessions.length} shared</span>{/if}
    </div>

    {#if !status}
      <Skeleton class="h-9 w-full" role="status" aria-label="Loading" data-testid="loading" />
    {:else if status.gatewayUrl && !editing}
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-muted-foreground">Gateway</span>
        <code class="rounded bg-muted px-1.5 py-0.5">{status.gatewayUrl}</code>
        <span class="text-muted-foreground">as <code>{status.hostId}</code></span>
        <span class="ml-auto flex gap-1.5">
          <Button variant="outline" size="sm" onclick={() => ((editing = true), (url = status?.gatewayUrl ?? ""))}>Change</Button>
          <Button variant="ghost" size="sm" class="text-destructive hover:text-destructive" disabled={busy} onclick={() => run(() => remote.clearGateway())}>Remove</Button>
        </span>
      </div>
    {:else}
      <form class="grid gap-2 sm:grid-cols-[1fr_1fr_auto] sm:items-end" onsubmit={(e) => (e.preventDefault(), void saveGateway())}>
        <div class="space-y-1">
          <Label for="gateway-url">Gateway URL</Label>
          <Input id="gateway-url" bind:value={url} placeholder="https://gateway.your-tailnet.ts.net" required data-testid="gateway-url" />
        </div>
        <div class="space-y-1">
          <Label for="host-token">Host token (<code>handler-gateway add-host</code>)</Label>
          <Input id="host-token" type="password" bind:value={token} placeholder="h_…" required autocomplete="off" data-testid="host-token" />
        </div>
        <div class="flex gap-1.5">
          <Button type="submit" size="sm" disabled={busy || !url.trim() || !token.trim()} data-testid="save-gateway">Save</Button>
          {#if editing}<Button variant="ghost" size="sm" onclick={() => (editing = false)}>Cancel</Button>{/if}
        </div>
      </form>
    {/if}
  </div>

  {#if status?.gatewayUrl}
    <div class="space-y-3 rounded-lg border bg-card p-3.5 text-sm">
      <h3 class="font-medium">Devices</h3>
      {#if status.devices?.length}
        <ul class="space-y-1.5">
          {#each status.devices as d (d.id)}
            <li class="flex flex-wrap items-center gap-2 rounded-md border bg-background px-2.5 py-1.5" data-testid="device-row">
              <span class="font-medium">{d.name}</span>
              <span class="rounded-md bg-muted px-1.5 py-0.5 text-xs" data-testid="device-person">
                {d.person && d.person !== "owner" ? `${d.person} · apps only` : "you"}
              </span>
              <code class="text-xs text-muted-foreground">{d.id}</code>
              <span class="text-xs text-muted-foreground">
                paired {ago(d.createdAt)}{d.lastSeenAt ? ` · seen ${ago(d.lastSeenAt)}` : " · never used"}
                {#if d.attached?.length}· attached to {d.attached.length}{/if}
              </span>
              <Button class="ml-auto" variant="ghost" size="sm" disabled={busy} onclick={() => revoke(d.id, d.name)}>Revoke</Button>
            </li>
          {/each}
        </ul>
      {:else}
        <p class="text-muted-foreground">No device paired yet.</p>
      {/if}

      {#if pairing}
        <div class="flex flex-wrap items-start gap-4 rounded-md border border-warn/60 bg-background p-3" data-testid="pairing">
          <QrCode text={pairing.pairingUrl} />
          <div class="min-w-0 flex-1 space-y-2">
            <p><strong>Scan this with {pairing.device.name}</strong> (camera app), then tap <em>Pair</em>.</p>
            <p class="text-muted-foreground">
              {#if pairing.device.person && pairing.device.person !== "owner"}
                The code holds the device's key: anyone who scans it can use the apps shared with {pairing.device.person}
                (never your sessions).
              {:else}
                The code holds the device's key: anyone who scans it can drive your shared sessions and apps.
              {/if}
              It is shown only now. The gateway must be served over HTTPS for the phone to use it.
            </p>
            <details>
              <summary class="cursor-pointer text-muted-foreground">Link (to open on the device by other means)</summary>
              <code class="mt-1 block break-all rounded bg-muted p-2 text-xs" data-testid="pairing-url">{pairing.pairingUrl}</code>
            </details>
            <Button size="sm" onclick={() => (pairing = null)}>Done</Button>
          </div>
        </div>
      {:else}
        <form class="space-y-3 border-t pt-3" onsubmit={(e) => (e.preventDefault(), void pair())}>
          <h3 class="font-medium">Pair a device</h3>
          <fieldset class="space-y-1.5">
            <legend class="mb-1 text-sm">Who is it for?</legend>
            <label class="flex items-center gap-2">
              <input type="radio" name="device-for" checked={!forFamily} onchange={() => (forFamily = false)} data-testid="device-for-me" />
              Me <span class="text-muted-foreground">— my shared sessions and apps</span>
            </label>
            <label class="flex items-center gap-2">
              <input type="radio" name="device-for" checked={forFamily} onchange={() => (forFamily = true)} data-testid="device-for-family" />
              A family member <span class="text-muted-foreground">— only the apps shared with them, never a session</span>
            </label>
          </fieldset>
          <div class="flex flex-wrap items-end gap-2">
            {#if forFamily}
              <div class="space-y-1">
                <Label for="device-person">Their name</Label>
                <Input
                  id="device-person"
                  bind:value={person}
                  placeholder="alice"
                  maxlength={30}
                  required
                  pattern="[a-z][a-z0-9_-]*"
                  title="lowercase letters, digits, - and _"
                  data-testid="device-person-input"
                />
              </div>
            {/if}
            <div class="space-y-1">
              <Label for="device-name">Device name</Label>
              <Input id="device-name" bind:value={deviceName} placeholder="phone" maxlength={60} data-testid="device-name" />
            </div>
            <Button type="submit" size="sm" disabled={busy} data-testid="pair-device">Pair</Button>
          </div>
        </form>
      {/if}
    </div>
  {/if}
  {#if error || remote.error}<p class="text-sm text-danger" data-testid="remote-error">{error ?? remote.error}</p>{/if}
</section>
