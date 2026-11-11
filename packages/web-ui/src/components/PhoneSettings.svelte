<script lang="ts">
  // Settings → Your phone (D.7, remote design), one page: 1 · the gateway (its address and its
  // light, the host token sealed, Change; not set: its two fields and Connect; How to set one up
  // folded), then 2 · your devices (Pair a device, each one paired and last seen, Revoke), greyed
  // until a gateway is set. Pairing opens a dialog that shows the device's key once, as a QR code
  // whose URL carries it in the fragment (never sent to a server).
  import Lock from "@lucide/svelte/icons/lock";
  import Plus from "@lucide/svelte/icons/plus";
  import Smartphone from "@lucide/svelte/icons/smartphone";
  import Dialog from "./Dialog.svelte";
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
  let howOpen = $state(false);
  let deviceName = $state("");
  let forFamily = $state(false); // the device is a family member's: apps only
  let person = $state(""); // that family member's name
  let pairing = $state<RemotePairing | null>(null);
  let error = $state<string | null>(null); // the gateway's or a device's
  let pairError = $state<string | null>(null); // the dialog's
  let busy = $state(false);
  let pairOpen = $state(false);

  const status = $derived(remote.status);
  const connected = $derived(Boolean(status?.gatewayUrl));

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
  const ROW = "flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3.5";
  const LABEL = "w-36 shrink-0 font-medium";
</script>

{#snippet heading(n: number, title: string, note: string)}
  <span class="flex items-center gap-2 text-sm">
    <span class="flex size-5 items-center justify-center rounded-full bg-muted font-mono text-xs text-muted-foreground">{n}</span>
    <span class="font-semibold">{title}</span>
    {#if note}<span class="text-muted-foreground">{note}</span>{/if}
  </span>
{/snippet}

{#snippet command(text: string)}
  <code class="block w-fit max-w-full overflow-x-auto rounded-md bg-muted px-2.5 py-1.5 font-mono text-xs">{text}</code>
{/snippet}

<section class="space-y-10" data-testid="phone-settings">
  {#if !status}
    <Skeleton class="h-40 w-full rounded-[10px]" role="status" aria-label="Loading" data-testid="loading" />
  {:else}
    <!-- 1 · the gateway -->
    <div class="space-y-3">
      <div class="flex flex-wrap items-center justify-between gap-2">
        {@render heading(1, "The gateway", "your own, on a machine both can reach")}
        <button type="button" class="text-sm text-primary hover:underline" aria-expanded={howOpen} onclick={() => (howOpen = !howOpen)} data-testid="gateway-how">How to set one up</button>
      </div>
      {#if howOpen}
        <ol class="enter list-decimal space-y-3 rounded-[10px] border bg-muted/40 py-4 pr-4 pl-9 text-sm" data-testid="remote-steps">
          <li class="space-y-1.5">
            <p>Run it where your phone reaches over HTTPS (your Tailscale network, say). It only relays encrypted messages: in Handler's <code>remote-gateway/</code> folder, as a container or with <code>uv tool install</code>.</p>
            {@render command("handler-gateway")}
          </li>
          <li class="space-y-1.5">
            <p>On the gateway, this prints this computer's host token, shown once: enter it here with the gateway's address.</p>
            {@render command("handler-gateway add-host laptop")}
          </li>
          <li><p>Pair your phone below, then turn on its button in a session: the phone lists it.</p></li>
        </ol>
      {/if}
      {#if !connected || editing}
        <form class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel" onsubmit={(e) => (e.preventDefault(), void saveGateway())} data-testid="gateway-form">
          <div class={ROW}>
            <Label for="gateway-url" class={LABEL}>Address</Label>
            <Input id="gateway-url" class="max-w-md flex-1 font-mono text-xs" bind:value={url} placeholder="https://gateway.your-tailnet.ts.net" required data-testid="gateway-url" />
          </div>
          <div class={ROW}>
            <Label for="host-token" class={LABEL}>Host token</Label>
            <Input id="host-token" class="max-w-md flex-1" type="password" bind:value={token} placeholder="h_…" required autocomplete="off" data-testid="host-token" />
          </div>
          <div class="{ROW} justify-end">
            {#if error}<p class="mr-auto text-danger" data-testid="remote-error">{error}</p>{/if}
            {#if editing}
              <Button variant="ghost" size="sm" class="mr-auto text-destructive hover:text-destructive" disabled={busy} onclick={() => run(async () => ((editing = false), await remote.clearGateway()))}>Remove the gateway</Button>
              <Button variant="ghost" size="sm" onclick={() => (editing = false)}>Cancel</Button>
            {/if}
            <Button type="submit" size="sm" disabled={busy || !url.trim() || !token.trim()} data-testid="save-gateway">Connect</Button>
          </div>
        </form>
      {:else}
        <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel" data-testid="gateway">
          <li class={ROW}>
            <span class={LABEL}>Address</span>
            <span class="fact min-w-0 flex-1 break-all" title="this computer: {status.hostId}">{status.gatewayUrl}</span>
            <span class="flex items-center gap-1.5 text-xs" data-testid="remote-light"><span class="size-2 rounded-full {lightTone(status.light)}" aria-hidden="true"></span>{LIGHT_LABEL[status.light]}</span>
          </li>
          {#if status.detail}<li class="{ROW} text-danger">{status.detail}</li>{/if}
          <li class={ROW}>
            <span class={LABEL}>Host token</span>
            <span class="flex flex-1 items-center gap-1 text-xs text-ok"><Lock class="size-3" />sealed</span>
            <Button variant="ghost" size="sm" onclick={() => ((editing = true), (url = status?.gatewayUrl ?? ""))} data-testid="gateway-change">Change</Button>
          </li>
        </ul>
      {/if}
    </div>

    <!-- 2 · the devices: greyed until a gateway is set -->
    <div class="space-y-3 {connected ? '' : 'pointer-events-none opacity-50'}" aria-disabled={!connected} data-testid="devices">
      <div class="flex flex-wrap items-center justify-between gap-2">
        {@render heading(2, "Your devices", "")}
        <Button size="sm" disabled={!connected} onclick={openPairing} data-testid="pair-open"><Plus />Pair a device</Button>
      </div>
      {#if connected && !editing && error}<p class="text-sm text-danger" data-testid="remote-error">{error}</p>{/if}
      {#if status.devices?.length}
        <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
          {#each status.devices as d (d.id)}
            <li class="enter {ROW}" data-testid="device-row">
              <span class="flex w-36 shrink-0 items-center gap-2 font-medium" title={d.id}><Smartphone class="size-4 text-muted-foreground" /><span class="truncate">{d.name}</span></span>
              <span class="min-w-0 flex-1 text-muted-foreground">
                paired {ago(d.createdAt)} · {d.lastSeenAt ? `last seen ${ago(d.lastSeenAt)}` : "never used"}{#if d.attached?.length}{" "}· in {d.attached.length} session{d.attached.length === 1 ? "" : "s"}{/if}
                {#if family(d.person)}<span class="ml-1 rounded-md bg-muted px-1.5 py-0.5 text-xs" data-testid="device-person">{d.person} · apps only</span>{/if}
              </span>
              <Button variant="ghost" size="sm" class="text-muted-foreground hover:text-destructive" disabled={busy} onclick={() => revoke(d.id, d.name)}>Revoke</Button>
            </li>
          {/each}
        </ul>
      {:else}
        <p class="rounded-[10px] border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">No device yet</p>
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
