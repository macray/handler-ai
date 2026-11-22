<script lang="ts">
  // Settings → Connection: the chain this phone → the gateway → the computer, lit link by link (the
  // broken one shows where it fails, in words under it), and the ids, each with a copy button.
  import { app } from "../lib/app.svelte";
  import { computerName } from "../lib/pairing";
  import { lights, status, type Light } from "./Lights.svelte";
  import Chain from "./Chain.svelte";
  import PageHeader from "./PageHeader.svelte";

  let { onback }: { onback: () => void } = $props();

  const device = $derived(app.device);
  const computer = $derived(device ? computerName(device) : "");
  const link = $derived(status(app.mailbox));
  const l = $derived(app.mailbox ? lights(app.mailbox) : null);
  const gateway = $derived<Light>(l?.gateway ?? "unknown");
  // the computer is reached through the gateway: unknown while the gateway is not
  const host = $derived<Light>(gateway === "ok" ? (l?.host ?? "unknown") : "unknown");
  const gatewayAt = $derived(device ? device.gateway.replace(/^https?:\/\//, "").replace(/\/$/, "") : "");

  const ids = $derived(
    device
      ? [
          { key: "gateway", label: "Gateway", shown: gatewayAt, copied: device.gateway },
          { key: "computer", label: "Computer", shown: computer === device.hostId ? device.hostId : `${computer} · ${device.hostId}`, copied: device.hostId },
          { key: "phone", label: "This phone", shown: device.deviceId, copied: device.deviceId },
        ]
      : [],
  );

  let copied = $state<string | null>(null);
  let timer: ReturnType<typeof setTimeout> | undefined;

  /** Copies `text`: "Copied" once the browser has it (a page paired is https, or this computer). */
  async function copy(key: string, text: string): Promise<void> {
    await navigator.clipboard.writeText(text);
    copied = key;
    clearTimeout(timer);
    timer = setTimeout(() => (copied = null), 1500);
  }
</script>

<PageHeader title="Connection" back="Settings" {onback} />

<main class="page" data-testid="connection">
  <div class="card">
    <p class="state {link.light}" data-testid="connection-state">{link.words}</p>
    <Chain {gateway} {host} {computer} />
    {#if l}
      <ul class="why">
        <li><span class="light {l.gateway}" aria-hidden="true"></span>{l.gatewayText}</li>
        <li><span class="light {l.host}" aria-hidden="true"></span>{l.hostText}</li>
      </ul>
    {/if}
  </div>

  <ul class="card ids">
    {#each ids as id (id.key)}
      <li>
        <span class="text">
          <span>{id.label}</span>
          <code data-testid="id-{id.key}">{id.shown}</code>
        </span>
        <button
          type="button"
          class="copy"
          onclick={() => copy(id.key, id.copied)}
          aria-label="copy {id.label}"
          title="Copy"
          data-testid="copy-{id.key}"
        >
          {#if copied === id.key}
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6 9 17l-5-5" /></svg>
          {:else}
            <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="14" height="14" rx="2" /><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" /></svg>
          {/if}
        </button>
      </li>
    {/each}
  </ul>
  {#if copied}<p class="hint" role="status">Copied</p>{/if}
</main>

<style>
  .page {
    flex: 1;
    overflow-y: auto;
    padding: 0.75rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }
  .card {
    border: 1px solid var(--border);
    border-radius: 12px;
    background: var(--card);
  }
  .card:not(.ids) {
    padding: 0.85rem 0.9rem;
    display: flex;
    flex-direction: column;
    gap: 0.85rem;
  }
  .state {
    font: 600 1.05em var(--mono);
  }
  .state.ok {
    color: var(--ok);
  }
  .state.warn {
    color: var(--warn);
  }
  .state.danger {
    color: var(--danger);
  }
  .why {
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    font-size: 0.85em;
    color: var(--muted-foreground);
  }
  .why li {
    display: flex;
    align-items: baseline;
    gap: 0.55rem;
  }
  .light {
    flex: none;
    display: inline-block;
    width: 0.55rem;
    height: 0.55rem;
    border-radius: 50%;
    background: var(--muted-foreground);
  }
  .light.ok {
    background: var(--ok);
  }
  .light.warn {
    background: var(--warn);
  }
  .light.danger {
    background: var(--danger);
  }
  .ids li {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.7rem 0.6rem 0.7rem 0.9rem;
  }
  .ids li + li {
    border-top: 1px solid var(--border);
  }
  .text {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
  }
  code {
    font: 0.78em var(--mono);
    color: var(--muted-foreground);
    overflow-wrap: anywhere;
    user-select: all;
  }
  .copy {
    flex: none;
    display: grid;
    place-items: center;
    width: 44px;
    height: 44px;
    border-radius: 10px;
    color: var(--muted-foreground);
  }
  .copy svg {
    width: 1.15rem;
    height: 1.15rem;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .copy:active {
    background: var(--accent);
  }
  .hint {
    font-size: 0.8em;
    color: var(--muted-foreground);
    padding: 0 0.25rem;
  }
</style>
