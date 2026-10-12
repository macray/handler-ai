<script lang="ts">
  import { STATUS_LABEL, type SessionStatus } from "../lib/sessions.svelte";

  let { status, label = false }: { status: SessionStatus; label?: boolean } = $props();
</script>

<span class="status {status}" title={STATUS_LABEL[status]} data-testid="session-status" data-status={status}>
  <span class="dot" aria-hidden="true"></span>{#if label}<span class="text">{STATUS_LABEL[status]}</span>{/if}
</span>

<style>
  .status {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    font-size: 0.75rem;
    color: var(--muted-foreground);
    white-space: nowrap;
  }
  .dot {
    width: 0.6rem;
    height: 0.6rem;
    border-radius: 50%;
    border: 2px solid currentColor;
    flex: none;
  }
  .needs-you {
    color: var(--warn);
  }
  .needs-you .dot {
    background: currentColor;
    animation: pulse 1.2s ease-in-out infinite;
  }
  .replied {
    color: var(--link);
  }
  .replied .dot {
    background: currentColor;
  }
  .working {
    color: var(--ok);
  }
  .working .dot,
  .starting .dot {
    border-right-color: transparent;
    animation: spin 0.9s linear infinite;
  }
  .stopped .dot,
  .elsewhere .dot {
    border-style: dashed;
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
  @keyframes pulse {
    50% {
      opacity: 0.35;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .dot {
      animation: none !important;
    }
  }
</style>
