<script lang="ts">
  // Settings → Remote (D.7, docs/dev/design/remote.md). Not set up: the three steps, the gateway's
  // form inside the second. Set up: the gateway handler polls and its light, the steps folded away,
  // and the paired devices, each yours or a family member's (apps only). Pairing opens a dialog that
  // shows the device's key once, as a QR code whose URL carries it in the fragment (never sent to a
  // server).
  import type { Snippet } from "svelte";
  import Plus from "@lucide/svelte/icons/plus";
  import Smartphone from "@lucide/svelte/icons/smartphone";
  import Dialog from "./Dialog.svelte";
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
  let error = $state<string | null>(null); // the gateway's or a device's
  let pairError = $state<string | null>(null); // the dialog's
  let busy = $state(false);
  let pairOpen = $state(false);

  const status = $derived(remote.status);
  // the steps done: a gateway set (1, 2), a device paired (3)
  const connected = $derived(Boolean(status?.gatewayUrl));
  const paired = $derived(Boolean(status?.devices?.length));

  $effect(() => {
    remote.start();
  });

  async function run(action: () => Promise<unknown>, onError = (m: string) => (error = m)): Promise<void> {
    busy = true;
    error = pairError = null;
    try {
      await action();
    } catch (e) {
      onError((e as Error).message);
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

  function openPairing(): void {
    pairing = null;
    pairError = null;
    pairOpen = true;
  }

  function pair(): Promise<void> {
    return run(
      async () => {
        pairing = await remote.pair(deviceName || "phone", forFamily ? person.trim() : "owner");
        deviceName = "";
        person = "";
        forFamily = false;
      },
      (m) => (pairError = m),
    );
  }

  function revoke(id: string, name: string): void {
    if (confirm(`Revoke ${name}? It loses access at once; pairing it again needs a new QR code.`)) void run(() => remote.revoke(id));
  }

  const family = (person: string | undefined) => Boolean(person && person !== "owner");
</script>

{#snippet step(n: number, done: boolean, title: string, body: Snippet)}
  <li class="flex gap-4">
    <span
      class="flex size-6 shrink-0 items-center justify-center rounded-full font-mono text-xs {done
        ? 'bg-ok/10 text-ok'
        : 'bg-muted text-muted-foreground'}"
    >
      {done ? "✓" : n}
    </span>
    <div class="min-w-0 flex-1 space-y-2 pt-0.5">
      <p class="font-medium">{title}</p>
      {@render body()}
    </div>
  </li>
{/snippet}

{#snippet command(text: string)}
  <code class="block w-fit max-w-full overflow-x-auto rounded-md bg-muted px-2.5 py-1.5 font-mono text-xs">{text}</code>
{/snippet}

{#snippet gatewayForm()}
  <form class="grid gap-3 pt-1 sm:grid-cols-2" onsubmit={(e) => (e.preventDefault(), void saveGateway())}>
    <div class="space-y-1.5">
      <Label for="gateway-url">Gateway URL</Label>
      <Input id="gateway-url" bind:value={url} placeholder="https://gateway.your-tailnet.ts.net" required data-testid="gateway-url" />
    </div>
    <div class="space-y-1.5">
      <Label for="host-token">Host token</Label>
      <Input id="host-token" type="password" bind:value={token} placeholder="h_…" required autocomplete="off" data-testid="host-token" />
    </div>
    <div class="flex items-center gap-2 sm:col-span-2">
      <Button type="submit" size="sm" disabled={busy || !url.trim() || !token.trim()} data-testid="save-gateway">Connect</Button>
      {#if editing}<Button variant="ghost" size="sm" onclick={() => (editing = false)}>Cancel</Button>{/if}
      {#if error}<p class="text-sm text-danger" data-testid="remote-error">{error}</p>{/if}
    </div>
  </form>
{/snippet}

{#snippet steps(withForm: boolean)}
  <ol class="space-y-6 text-sm" data-testid="remote-steps">
    {#snippet one()}
      <p class="text-muted-foreground">
        A small server your phone reaches over HTTPS, e.g. on your Tailscale network. It only relays encrypted messages. It is in
        Handler's <code>remote-gateway/</code> folder: run it as a container, or install it with <code>uv tool install</code>.
      </p>
      {@render command("handler-gateway")}
    {/snippet}
    {#snippet two()}
      <p class="text-muted-foreground">On the gateway, this prints this computer's host token, shown once. Enter it here with the gateway's URL.</p>
      {@render command("handler-gateway add-host laptop")}
      {#if withForm}{@render gatewayForm()}{/if}
    {/snippet}
    {#snippet three()}
      <p class="text-muted-foreground">Your phone scans a QR code shown here. Then turn on <span class="font-medium text-foreground">Remote</span> in a session: the phone lists it.</p>
    {/snippet}
    {@render step(1, connected, "Run a gateway", one)}
    {@render step(2, connected, "Connect this computer", two)}
    {@render step(3, paired, "Pair a device", three)}
  </ol>
{/snippet}

<section class="space-y-10" data-testid="remote-settings">
  <p class="max-w-2xl text-sm text-muted-foreground">
    Use your sessions and apps from a phone or tablet, end-to-end encrypted, through a gateway you run. Optional.
  </p>

  {#if !status}
    <Skeleton class="h-40 w-full rounded-[10px]" role="status" aria-label="Loading" data-testid="loading" />
  {:else if !connected}
    <!-- not set up: the steps, the gateway's form in the second -->
    <div class="enter rounded-[10px] border bg-card p-6 shadow-panel">
      <div class="mb-6 flex items-center gap-3">
        <span class="flex size-10 items-center justify-center rounded-lg bg-muted text-muted-foreground"><Smartphone class="size-5" /></span>
        <div>
          <h2 class="text-base font-semibold">Set up your phone</h2>
          <p class="text-sm text-muted-foreground" data-testid="remote-light">{LIGHT_LABEL[status.light]}</p>
        </div>
      </div>
      {@render steps(true)}
    </div>
  {:else}
    <!-- the gateway: its light, where it is -->
    <div class="space-y-6">
      <div class="rounded-[10px] border bg-card p-5 shadow-panel">
        {#if editing}
          <h2 class="mb-3 text-base font-semibold">Change the gateway</h2>
          {@render gatewayForm()}
        {:else}
          <div class="flex flex-wrap items-start justify-between gap-4">
            <div class="min-w-0 space-y-1.5">
              <p class="flex flex-wrap items-center gap-2 text-sm">
                <span class="size-2 shrink-0 rounded-full {lightTone(status.light)}" aria-hidden="true"></span>
                <span class="font-medium" data-testid="remote-light">{LIGHT_LABEL[status.light]}</span>
                {#if status.sharedSessions?.length}
                  <span class="text-muted-foreground">· {status.sharedSessions.length} session{status.sharedSessions.length === 1 ? "" : "s"} shared</span>
                {/if}
              </p>
              {#if status.detail}<p class="text-sm text-danger">{status.detail}</p>{/if}
              <p class="fact break-all" title="this computer: {status.hostId}">
                {status.gatewayUrl}{#if status.since}&ensp;·&ensp;since <When at={status.since} />{/if}
              </p>
            </div>
            <div class="flex gap-1.5">
              <Button variant="outline" size="sm" onclick={() => ((editing = true), (url = status?.gatewayUrl ?? ""))}>Change</Button>
              <Button variant="ghost" size="sm" class="text-destructive hover:text-destructive" disabled={busy} onclick={() => run(() => remote.clearGateway())}>Remove</Button>
            </div>
          </div>
        {/if}
      </div>
      <details class="group text-sm">
        <summary class="cursor-pointer text-muted-foreground select-none hover:text-foreground">How it works</summary>
        <div class="pt-4">{@render steps(false)}</div>
      </details>
    </div>

    <!-- the devices -->
    <div class="space-y-4">
      <div class="flex flex-wrap items-end justify-between gap-3">
        <div class="space-y-1">
          <h2 class="text-base font-semibold">Devices</h2>
          <p class="text-sm text-muted-foreground">Phones and tablets that can reach this computer. Revoke one you lost.</p>
        </div>
        {#if paired}
          <Button variant="outline" size="sm" onclick={openPairing} data-testid="pair-open"><Plus />Pair a device</Button>
        {/if}
      </div>
      {#if !editing && error}<p class="text-sm text-danger" data-testid="remote-error">{error}</p>{/if}

      {#if status.devices?.length}
        <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
          {#each status.devices as d (d.id)}
            <li class="enter flex items-center gap-4 px-4 py-3.5" data-testid="device-row">
              <span class="hidden size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground sm:flex"><Smartphone class="size-4" /></span>
              <div class="min-w-0 flex-1 space-y-0.5">
                <p class="flex flex-wrap items-center gap-2">
                  <span class="truncate text-sm font-medium" title={d.id}>{d.name}</span>
                  <span class="rounded-md bg-muted px-1.5 py-0.5 text-xs text-muted-foreground" data-testid="device-person">
                    {family(d.person) ? `${d.person} · apps only` : "you"}
                  </span>
                </p>
                <p class="fact">
                  {d.lastSeenAt ? `seen ${ago(d.lastSeenAt)}` : "never used"} · paired {ago(d.createdAt)}{#if d.attached?.length}&nbsp;· in {d.attached.length} session{d.attached.length === 1 ? "" : "s"}{/if}
                </p>
              </div>
              <Button variant="ghost" size="sm" class="text-muted-foreground hover:text-destructive" disabled={busy} onclick={() => revoke(d.id, d.name)}>Revoke</Button>
            </li>
          {/each}
        </ul>
      {:else}
        <div class="flex flex-col items-center gap-3 rounded-[10px] border border-dashed px-6 py-10 text-center">
          <span class="flex size-10 items-center justify-center rounded-lg bg-muted text-muted-foreground"><Smartphone class="size-5" /></span>
          <div class="space-y-1">
            <p class="text-sm font-medium">No device yet</p>
            <p class="text-sm text-muted-foreground">Pair your phone: it scans a QR code shown here.</p>
          </div>
          <Button size="sm" onclick={openPairing} data-testid="pair-open"><Plus />Pair a device</Button>
        </div>
      {/if}
    </div>
  {/if}
  {#if remote.error}<p class="text-sm text-danger">{remote.error}</p>{/if}

  <!-- pairing: who it is for and its name, then its QR code, shown once -->
  <Dialog bind:open={pairOpen} title={pairing ? `Scan this with ${pairing.device.name}` : "Pair a device"} description={pairing ? undefined : "Next, a QR code to scan with it."} testid="pair-dialog">
    {#if pairing}
      <div class="space-y-5" data-testid="pairing">
        <div class="flex justify-center rounded-[10px] border bg-white p-3"><QrCode text={pairing.pairingUrl} size={224} /></div>
        <p class="text-muted-foreground">
          Open the camera app, then tap <span class="font-medium text-foreground">Pair</span>. The code holds the device's key:
          {#if family(pairing.device.person)}
            anyone who scans it can use the apps shared with {pairing.device.person} (never your sessions).
          {:else}
            anyone who scans it can drive your shared sessions and apps.
          {/if}
          It is shown only now. The gateway must be served over HTTPS for the phone to use it.
        </p>
        <details>
          <summary class="cursor-pointer text-muted-foreground hover:text-foreground">The link, to open it on the device another way</summary>
          <code class="mt-2 block rounded-md bg-muted p-2.5 font-mono text-xs break-all" data-testid="pairing-url">{pairing.pairingUrl}</code>
        </details>
        <div class="flex justify-end">
          <Button size="sm" onclick={() => (pairOpen = false)}>Done</Button>
        </div>
      </div>
    {:else}
      <form class="space-y-5" onsubmit={(e) => (e.preventDefault(), void pair())}>
        <fieldset class="grid gap-2 sm:grid-cols-2">
          <legend class="mb-2 font-medium">Who is it for?</legend>
          {#each [{ value: false, title: "Me", text: "My shared sessions and apps", id: "device-for-me" }, { value: true, title: "A family member", text: "Only the apps shared with them, never a session", id: "device-for-family" }] as o (o.id)}
            <label
              class="flex cursor-pointer items-start gap-3 rounded-[10px] border p-3 transition-colors hover:bg-muted/50 {forFamily === o.value
                ? 'border-primary bg-primary/5'
                : ''}"
            >
              <input type="radio" name="device-for" class="mt-0.5 accent-primary" checked={forFamily === o.value} onchange={() => (forFamily = o.value)} data-testid={o.id} />
              <span class="space-y-0.5">
                <span class="block font-medium">{o.title}</span>
                <span class="block text-xs text-muted-foreground">{o.text}</span>
              </span>
            </label>
          {/each}
        </fieldset>
        {#if forFamily}
          <div class="space-y-1.5">
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
        <div class="space-y-1.5">
          <Label for="device-name">Device name</Label>
          <Input id="device-name" bind:value={deviceName} placeholder="phone" maxlength={60} data-testid="device-name" />
        </div>
        {#if pairError}<p class="text-danger" data-testid="remote-error">{pairError}</p>{/if}
        <div class="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onclick={() => (pairOpen = false)}>Cancel</Button>
          <Button type="submit" size="sm" disabled={busy} data-testid="pair-device">Show the QR code</Button>
        </div>
      </form>
    {/if}
  </Dialog>
</section>
