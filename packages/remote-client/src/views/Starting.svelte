<script lang="ts">
  // Before the app knows which screen to show (Sessions or Ask: the host's answer, or the last
  // one kept): no screen's shape. While the last Home is read from this phone, index.html's
  // "Connecting…", the same, in the middle: a phone with a Home kept sees it turn into its tab,
  // nothing on screen moving. With none kept (the first launch), Handler's name and the chain
  // this phone → the gateway → the computer, lit link by link as each answers.
  import { app } from "../lib/app.svelte";
  import { computerName } from "../lib/pairing";
  import Chain from "./Chain.svelte";
  import { lights, type Light } from "./Lights.svelte";

  const first = $derived(app.ready && app.homeAt === null);
  const computer = $derived(app.device ? computerName(app.device) : "");
  const m = $derived(app.mailbox);
  const gateway = $derived<Light>(m ? lights(m).gateway : "unknown");
  // asked through the gateway: not known before it answers
  const host = $derived<Light>(m?.reachable && m.hostOnline ? "ok" : "unknown");
  const words = $derived(m?.reachable ? `Asking ${computer}…` : "Reaching your gateway…");
</script>

<main class="starting" aria-busy="true" data-testid="starting">
  {#if first}
    <div class="first">
      <p class="name">
        <svg viewBox="0 0 64 64" aria-hidden="true">
          <path class="ink" d="M23 20 V14 a4 4 0 0 1 4 -4 h10 a4 4 0 0 1 4 4 v6" />
          <path class="ink" d="M14 20 H50 a8 8 0 0 1 8 8 V44 a8 8 0 0 1 -8 8 H28 L17 60 V52 H14 a8 8 0 0 1 -8 -8 V28 a8 8 0 0 1 8 -8 Z" />
          <circle cx="22" cy="36" r="3.5" /><circle cx="32" cy="36" r="3.5" /><circle cx="42" cy="36" r="3.5" />
        </svg>
        handler
      </p>
      <Chain {gateway} {host} {computer} />
      <p class="status" role="status" data-testid="lights">{words}</p>
    </div>
  {:else}
    <!-- index.html's, the same -->
    <span class="connecting" role="status" data-testid="lights"><i aria-hidden="true"></i>Connecting…</span>
  {/if}
</main>

<style>
  .starting {
    flex: 1;
    display: grid;
    place-items: center;
    padding-top: env(safe-area-inset-top);
  }
  .first {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 1.6rem;
    animation: fade var(--dur-2) var(--ease) backwards;
  }
  @keyframes fade {
    from {
      opacity: 0;
    }
  }
  .name {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    font: 800 30px/1 var(--mono);
    letter-spacing: -0.05em;
  }
  .name svg {
    width: 40px;
    height: 40px;
  }
  .ink {
    fill: none;
    stroke: currentColor;
    stroke-width: 5;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  circle {
    fill: var(--primary);
  }
  .status {
    font: 13px/1.4 var(--mono);
    color: var(--muted-foreground);
  }
  .connecting {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.75em;
    line-height: 1.25;
    color: var(--muted-foreground);
    white-space: nowrap;
  }
  .connecting i {
    width: 0.5rem;
    height: 0.5rem;
    border-radius: 50%;
    background: var(--muted-foreground);
    animation: waiting 1.4s var(--ease) infinite alternate;
  }
  @keyframes waiting {
    to {
      opacity: 0.25;
    }
  }
</style>
