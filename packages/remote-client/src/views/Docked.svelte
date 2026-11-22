<script lang="ts">
  // What the link says, docked at the bottom of a list screen, over it: what is shown never moves
  // when the link's state is known (gateway UI snappy §3). `quiet`: the screen says it already
  // (nothing from the host yet, or nothing to show).
  import { app } from "../lib/app.svelte";

  let { quiet = false }: { quiet?: boolean } = $props();

  const hostAway = $derived(Boolean(app.mailbox?.reachable && app.mailbox.hostSeen && !app.mailbox.hostOnline));
</script>

{#if app.mailbox?.unauthorized}
  <p class="banner error">
    The gateway does not know this device: it was revoked, or Handler could not register it yet.
    <button type="button" onclick={() => app.chooseTab("settings")}>Settings</button>
  </p>
{:else if hostAway && !quiet && !app.offline}
  <p class="banner" data-testid="host-away">
    Your computer is not listening right now: apps work from their offline copy, their actions wait for it.
  </p>
{/if}

<style>
  .banner {
    position: sticky;
    bottom: 0;
    margin-top: auto;
    padding: 0.6rem 0.8rem;
    border-radius: 10px;
    font-size: 0.85em;
    color: var(--warn);
    background: color-mix(in srgb, var(--warn) 10%, var(--card));
    border: 1px solid color-mix(in srgb, var(--warn) 25%, var(--card));
    box-shadow: 0 -6px 16px var(--page);
    animation: fade var(--dur-2) var(--ease) backwards;
  }
  .banner.error {
    color: var(--danger);
    background: color-mix(in srgb, var(--danger) 10%, var(--card));
    border-color: color-mix(in srgb, var(--danger) 25%, var(--card));
  }
  button {
    text-decoration: underline;
    margin-left: 0.25rem;
  }
  @keyframes fade {
    from {
      opacity: 0;
    }
  }
</style>
