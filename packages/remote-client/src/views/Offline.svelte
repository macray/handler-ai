<script lang="ts">
  // The last launch's Home, opened with nothing answering (no network, the gateway or the
  // computer away): said on top of Apps, the Inbox and Ask, dated, until the live Home replaces
  // it (Sessions says it big, the same words).
  import { app } from "../lib/app.svelte";
  import { computerName } from "../lib/pairing";
  import { when } from "../lib/time";

  const computer = $derived(app.device ? computerName(app.device) : "");
</script>

{#if app.offline && app.homeAt !== null}
  <div class="offline" role="status" data-testid="home-offline">
    <strong>{app.mailbox?.reachable === false ? "No connection: can't reach your gateway" : `${computer} is away`}</strong>
    <span>As it was at {when(app.homeAt)}. Answer when it is back.</span>
    <button type="button" onclick={() => app.refresh()} disabled={app.loading}>Try again</button>
  </div>
{/if}

<style>
  .offline {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 0.2rem;
    padding: 0.6rem 0.8rem;
    border-radius: 10px;
    font-size: 0.85em;
    color: var(--warn);
    background: color-mix(in srgb, var(--warn) 10%, var(--card));
    border: 1px solid color-mix(in srgb, var(--warn) 25%, var(--card));
    animation: fade var(--dur-2) var(--ease) backwards;
  }
  @keyframes fade {
    from {
      opacity: 0;
    }
  }
  span {
    color: var(--muted-foreground);
  }
  .offline button {
    margin-top: 0.4rem;
    padding: 0.3rem 0.8rem;
    border-radius: 999px;
    border-color: currentColor;
  }
</style>
