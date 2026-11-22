<script lang="ts">
  // A safe ask answered on its session's card: Reject, Allow (filled; once, never "always").
  // Made again for each new ask (keyed by its tool call), so on a touch screen its buttons take no
  // tap for a moment after it appears, as the permission sheet's.
  import { SETTLE, settled } from "@handler/acp-view/lib/touch.svelte";

  let { busy = false, onanswer }: { busy?: boolean; onanswer: (answer: "allow" | "reject") => void } = $props();
  const settle = settled();
</script>

<div class="answers">
  <button
    type="button"
    class="no"
    class:settling={!settle.ready}
    style:--settle="{SETTLE}ms"
    disabled={!settle.ready || busy}
    onclick={() => onanswer("reject")}
    data-testid="card-reject">Reject</button
  >
  <button
    type="button"
    class="yes"
    class:settling={!settle.ready}
    style:--settle="{SETTLE}ms"
    disabled={!settle.ready || busy}
    onclick={() => onanswer("allow")}
    title="This time only"
    data-testid="card-allow">{busy ? "…" : "Allow"}</button
  >
</div>

<style>
  .answers {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.5rem;
    padding: 0 0.9rem 0.8rem;
  }
  button {
    position: relative;
    overflow: hidden;
    min-height: 2.6rem;
    border-radius: 10px !important;
    font: 600 0.95em var(--sans);
  }
  .no {
    border: 1px solid var(--needs-border) !important;
    background: var(--card);
    color: var(--foreground);
  }
  .yes {
    background: var(--primary);
    color: var(--primary-foreground);
  }
  /* a touch screen's buttons take no tap for a moment: a fill sweeps across them */
  button.settling::after {
    content: "";
    position: absolute;
    inset: auto 0 0 0;
    height: 3px;
    background: currentColor;
    transform-origin: left;
    animation: settle var(--settle) linear forwards;
  }
  @keyframes settle {
    from {
      transform: scaleX(0);
    }
  }
</style>
