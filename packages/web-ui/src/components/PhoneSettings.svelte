<script lang="ts">
  // Settings → Your phone (D.7, remote design), one page: 1 · the gateway, then 2 · your devices.
  // Not set (or Change): a guided setup (E5), its ways as tabs (Container, Without a container;
  // a community gateway, soon), steps 1–3 the commands to run on the gateway's machine (lib/gateway),
  // step 4 its address and the host token step 3 printed, and Connect, which waits for handlerd's
  // one try of the gateway (D.7): saved either way, what failed is said in words beside it, the
  // form kept open to fix it (Cancel: the saved gateway, its light red). Set:
  // its address and its light, what went wrong in words, the host token sealed, Change, and the
  // computer's name (what the phones paired from now on call it; the hostname until renamed). Your
  // devices (Pair a device, each one paired and last seen, Revoke) are greyed until a gateway is
  // set (Pair a device says why, its fix step 1: E1). Pairing opens a dialog that shows the
  // device's key once, as a QR code whose URL carries it in the fragment (never sent to a server).
  import { ask } from "../lib/ask.svelte";
  import Lock from "@lucide/svelte/icons/lock";
  import Plus from "@lucide/svelte/icons/plus";
  import Smartphone from "@lucide/svelte/icons/smartphone";
  import X from "@lucide/svelte/icons/x";
  import Dialog from "./Dialog.svelte";
  import DisabledReason from "./DisabledReason.svelte";
  import { PAIR_BLOCKED } from "../lib/blocked";
  import { Skeleton } from "$lib/components/ui/skeleton";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import type { RemotePairing } from "../lib/contracts.gen";
  import { LIGHT_LABEL, lightTone, remote } from "../lib/remote.svelte";
  import { ago } from "../lib/agents";
  import QrCode from "./QrCode.svelte";
  import CommandLine from "./CommandLine.svelte";
  import { connectError, CONTAINER, GATEWAY_WAYS, gatewayProblem, HTTPS_COMMAND } from "../lib/gateway";
  import { SEGMENT, SEGMENT_OFF, SEGMENT_ON } from "../lib/form";

  let url = $state("");
  let token = $state("");
  let editing = $state(false);
  let way = $state(CONTAINER); // the tab shown
  let deviceName = $state("");
  let forFamily = $state(false); // the device is a family member's: apps only
  let person = $state(""); // that family member's name
  let pairing = $state<RemotePairing | null>(null);
  let error = $state<string | null>(null); // the gateway's or a device's
  let pairError = $state<string | null>(null); // the dialog's
  let busy = $state(false);
  let connecting = $state(false); // Connect waits for the try (a few seconds at most)
  let pairOpen = $state(false);
  let naming = $state(false); // the computer's name being changed
  let computerName = $state("");

  const status = $derived(remote.status);
  const connected = $derived(Boolean(status?.gatewayUrl));
  const problem = $derived(gatewayProblem(status?.light, status?.detail));

  $effect(() => {
    remote.start();
  });

  async function run(
    action: () => Promise<unknown>,
    onError = (m: string) => (error = m),
    words = (e: unknown) => (e as Error).message,
  ): Promise<void> {
    busy = true;
    error = pairError = null;
    try {
      await action();
    } catch (e) {
      onError(words(e));
    } finally {
      busy = false;
    }
  }

  async function saveGateway(): Promise<void> {
    connecting = true;
    await run(
      async () => {
        await remote.setGateway(url, token);
        // saved, and tried once: what failed stays beside Connect, the form open to fix it
        const failed = gatewayProblem(remote.status?.light, remote.status?.detail, true);
        if (failed) {
          editing = true;
          error = failed;
          return;
        }
        token = "";
        editing = false;
      },
      (m) => (error = m),
      connectError,
    );
    connecting = false;
  }

  function saveName(): Promise<void> {
    return run(async () => {
      await remote.setComputerName(computerName);
      naming = false;
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

  async function revoke(id: string, name: string): Promise<void> {
    if (await ask({ title: `Revoke ${name}?`, detail: "It loses access at once; pairing it again needs a new QR code.", yes: "Revoke", danger: true })) void run(() => remote.revoke(id));
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

{#snippet step(n: number)}
  <span class="flex size-5 shrink-0 items-center justify-center rounded-full border font-mono text-xs text-muted-foreground">{n}</span>
{/snippet}

<section class="space-y-10" data-testid="phone-settings">
  {#if !status}
    <Skeleton class="h-40 w-full rounded-[10px]" role="status" aria-label="Loading" data-testid="loading" />
  {:else}
    <!-- 1 · the gateway: the guided setup until one is set (or Change), then it and its light -->
    <div class="space-y-3">
      {#if !connected || editing}
        <div class="space-y-4 rounded-[10px] border bg-card p-5 text-sm shadow-panel" data-testid="gateway-setup">
          <div class="flex flex-wrap items-center gap-3">
            {@render heading(1, editing ? "Change your gateway" : "Set up your gateway", "")}
            <div class="ml-auto inline-flex rounded-lg border bg-muted p-0.5" role="tablist" aria-label="how the gateway runs">
              {#each GATEWAY_WAYS as w (w.id)}
                <button
                  type="button"
                  role="tab"
                  aria-selected={w.id === way.id}
                  disabled={w.soon}
                  title={w.soon ? "Soon: the address of a gateway someone else runs, instead of steps 1–3" : undefined}
                  class="{SEGMENT} {w.soon ? 'cursor-default text-muted-foreground/60' : w.id === way.id ? SEGMENT_ON : SEGMENT_OFF}"
                  onclick={() => (way = w)}
                  data-testid="gateway-way-{w.id}">{w.label}{#if w.soon}{" "}· soon{/if}</button
                >
              {/each}
            </div>
          </div>
          <p class="text-muted-foreground">
            On an always-on machine your phone and this computer both reach: a home server, a NAS, a small VPS. <b class="font-medium text-foreground">Not this computer</b>: Handler never
            accepts connections from outside. About 10 minutes; every detail is in the phone guide, <code>docs/phone.md</code> in Handler's source folder.
          </p>
          <ol class="space-y-5" data-testid="remote-steps">
            {#if way.run}
              <li class="flex gap-3">
                {@render step(1)}
                <div class="min-w-0 flex-1 space-y-2">
                  <p><b class="font-semibold">Run the gateway</b> <span class="text-muted-foreground">{way.run.note}</span></p>
                  <CommandLine command={way.run.command} />
                  {#if way.run.after}<p class="text-xs text-muted-foreground">{way.run.after}</p>{/if}
                </div>
              </li>
              <li class="flex gap-3">
                {@render step(2)}
                <div class="min-w-0 flex-1 space-y-2">
                  <p><b class="font-semibold">Reach it over HTTPS</b> <span class="text-muted-foreground">with Tailscale (recommended: only your own devices reach it)</span></p>
                  <CommandLine command={HTTPS_COMMAND} />
                  <p class="text-xs text-muted-foreground">
                    It prints the address, like <code>https://nas.your-tailnet.ts.net</code>. Install Tailscale on your phone too. Public, behind Caddy instead: the phone guide.
                  </p>
                </div>
              </li>
              <li class="flex gap-3">
                {@render step(3)}
                <div class="min-w-0 flex-1 space-y-2">
                  <p><b class="font-semibold">Give this computer its token</b> <span class="text-muted-foreground">it prints one line starting with <code>h_</code>, shown once</span></p>
                  <CommandLine command={way.addHost ?? ""} />
                  <p class="text-xs text-muted-foreground"><code>laptop</code> is this computer's name at the gateway: any name will do.</p>
                </div>
              </li>
            {/if}
            <li class="flex gap-3">
              {@render step(4)}
              <form class="min-w-0 flex-1 space-y-3" onsubmit={(e) => (e.preventDefault(), void saveGateway())} data-testid="gateway-form">
                <p><b class="font-semibold">Paste them here</b></p>
                <div class="grid max-w-xl grid-cols-[7rem_1fr] items-center gap-x-4 gap-y-2.5">
                  <Label for="gateway-url" class="font-normal text-muted-foreground">Address</Label>
                  <Input id="gateway-url" class="font-mono text-xs" bind:value={url} placeholder="https://nas.your-tailnet.ts.net" required data-testid="gateway-url" />
                  <Label for="host-token" class="font-normal text-muted-foreground">Host token</Label>
                  <Input id="host-token" class="font-mono text-xs" type="password" bind:value={token} placeholder="h_…" required autocomplete="off" data-testid="host-token" />
                </div>
                <div class="flex flex-wrap items-center justify-end gap-2">
                  {#if error}<p class="mr-auto flex items-start gap-1.5 text-danger" data-testid="remote-error"><X class="mt-0.5 size-3.5 shrink-0" />{error}</p>{/if}
                  {#if editing}
                    <Button variant="ghost" size="sm" class="text-destructive hover:text-destructive" disabled={busy} onclick={() => run(async () => ((editing = false), await remote.clearGateway()))}
                      >Remove the gateway</Button
                    >
                    <Button variant="ghost" size="sm" onclick={() => ((editing = false), (error = null))}>Cancel</Button>
                  {/if}
                  <Button type="submit" size="sm" disabled={busy || !url.trim() || !token.trim()} data-testid="save-gateway">{connecting ? "Connecting…" : "Connect"}</Button>
                </div>
              </form>
            </li>
          </ol>
        </div>
      {:else}
        {@render heading(1, "Your gateway", "")}
        <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel" data-testid="gateway">
          <li class={ROW}>
            <span class={LABEL}>Address</span>
            <span class="fact min-w-0 flex-1 break-all" title="this computer: {status.hostId}">{status.gatewayUrl}</span>
            <span class="flex items-center gap-1.5 text-xs" data-testid="remote-light"><span class="size-2 rounded-full {lightTone(status.light)}" aria-hidden="true"></span>{LIGHT_LABEL[status.light]}</span>
          </li>
          {#if problem}
            <li class="flex items-start gap-2 px-4 py-3.5 text-danger" data-testid="gateway-problem"><X class="mt-0.5 size-3.5 shrink-0" />{problem}</li>
          {:else if status.light === "idle"}
            <li class="{ROW} text-muted-foreground" data-testid="gateway-untried">Not tried yet: Handler reaches the gateway only while something is on your phone (a session or an app).</li>
          {/if}
          <li class={ROW}>
            <span class={LABEL}>Host token</span>
            <span class="flex flex-1 items-center gap-1 text-xs text-ok"><Lock class="size-3" />sealed</span>
            <Button variant="ghost" size="sm" onclick={() => ((editing = true), (error = null), (url = status?.gatewayUrl ?? ""))} data-testid="gateway-change">Change</Button>
          </li>
          <li class={ROW} data-testid="computer-name">
            <span class={LABEL}>This computer's name</span>
            {#if naming}
              <form class="flex min-w-0 flex-1 flex-wrap items-center gap-2" onsubmit={(e) => (e.preventDefault(), void saveName())}>
                <Input class="max-w-xs" bind:value={computerName} maxlength={60} required aria-label="This computer's name" data-testid="computer-name-input" />
                <Button type="submit" size="sm" disabled={busy || !computerName.trim()} data-testid="computer-name-save">Save</Button>
                <Button variant="ghost" size="sm" onclick={() => (naming = false)}>Cancel</Button>
                <p class="basis-full text-xs text-muted-foreground">Phones paired before keep the name they were given, until paired again.</p>
              </form>
            {:else}
              <span class="min-w-0 flex-1"><span data-testid="computer-name-value">{status.computerName}</span> <span class="text-xs text-muted-foreground">what your phones call it</span></span>
              <Button variant="ghost" size="sm" onclick={() => ((naming = true), (error = null), (computerName = status?.computerName ?? ""))} data-testid="computer-name-change">Rename</Button>
            {/if}
          </li>
        </ul>
      {/if}
    </div>

    <!-- 2 · the devices: greyed until a gateway is set, but for why and its fix (step 1) -->
    <div class="space-y-3" data-testid="devices">
      <div class="flex flex-wrap items-center gap-2">
        <span class="mr-auto {connected ? '' : 'opacity-50'}">{@render heading(2, "Your devices", "")}</span>
        {#if !connected}<DisabledReason blocked={PAIR_BLOCKED} testid="pair-todo" />{/if}
        <Button size="sm" disabled={!connected} onclick={openPairing} data-testid="pair-open"><Plus />Pair a device</Button>
      </div>
      {#if connected && !editing && error}<p class="text-sm text-danger" data-testid="remote-error">{error}</p>{/if}
      {#if status.devices?.length}
        <ul class="{connected ? '' : 'pointer-events-none opacity-50'} divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
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
        <p class="rounded-[10px] border border-dashed px-4 py-6 text-center text-sm text-muted-foreground {connected ? '' : 'opacity-50'}">No device yet</p>
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
