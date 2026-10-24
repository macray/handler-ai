<script lang="ts">
  // A session's state at a glance, one dot: its fill says how alive it is (solid: it wants you,
  // tinted: its agent runs, empty: it does not), its ring's colour its health. A mark, never a
  // button: resuming is on the session's page.
  import { STATUS_LABEL, type SessionStatus } from "../lib/sessions.svelte";

  // title: what it says on hover (a project's dot sums its sessions up), its state's name by default
  let { status, label = false, title }: { status: SessionStatus; label?: boolean; title?: string } = $props();
</script>

<span class="status {status}" title={title ?? STATUS_LABEL[status]} data-testid="session-status" data-status={status}>
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
    position: relative;
    width: 0.6rem;
    height: 0.6rem;
    border-radius: 50%;
    border: 2px solid currentColor;
    flex: none;
  }
  /* running: a green ring, tinted inside; spinning while it works; dashed when open in other tabs */
  .idle,
  .working,
  .elsewhere {
    color: var(--ok);
  }
  .idle .dot,
  .working .dot,
  .elsewhere .dot {
    background: color-mix(in oklab, currentColor 30%, transparent);
  }
  /* failed: a red ring, empty, struck through (not by colour alone) */
  .failed {
    color: var(--danger);
  }
  .failed .dot::after {
    content: "";
    position: absolute;
    left: 50%;
    top: -2px;
    bottom: -2px;
    width: 2px;
    margin-left: -1px;
    background: currentColor;
    transform: rotate(45deg);
  }
  .needs-you {
    color: var(--warn);
  }
  /* waiting for you: the dot pops when it gets there, then a soft ring keeps calling */
  .needs-you .dot {
    background: currentColor;
    animation:
      pop var(--dur-3) var(--ease-spring),
      ring 2s var(--ease) var(--dur-3) infinite;
  }
  .replied {
    color: var(--link);
  }
  .replied .dot {
    background: currentColor;
    animation: pop var(--dur-3) var(--ease-spring);
  }
  .working .dot,
  .starting .dot {
    border-right-color: transparent;
    animation: spin 0.9s linear infinite;
  }
  .elsewhere .dot {
    border-style: dashed;
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
  @keyframes pop {
    from {
      transform: scale(0.4);
    }
  }
  @keyframes ring {
    from {
      box-shadow: 0 0 0 0 color-mix(in oklab, currentColor 45%, transparent);
    }
    70%,
    to {
      box-shadow: 0 0 0 5px transparent;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .dot {
      animation: none !important;
    }
  }
</style>
