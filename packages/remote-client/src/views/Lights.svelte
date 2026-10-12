<script lang="ts" module>
  // Two lights: can this device reach the gateway, and has the host polled it lately.
  import type { Mailbox } from "../lib/mailbox.svelte";

  export type Light = "ok" | "warn" | "danger" | "unknown";

  /** Each light's color and what it means (the Settings screen spells it out). */
  export function lights(mailbox: Mailbox): { gateway: Light; gatewayText: string; host: Light; hostText: string } {
    return {
      gateway: mailbox.unauthorized ? "warn" : mailbox.reachable === null ? "unknown" : mailbox.reachable ? "ok" : "danger",
      gatewayText: mailbox.unauthorized
        ? "the gateway does not know this device (revoked?)"
        : mailbox.reachable === false
          ? `gateway unreachable${mailbox.error ? `: ${mailbox.error}` : ""}`
          : mailbox.reachable
            ? "gateway reachable"
            : "connecting to the gateway…",
      host: mailbox.hostSeen === null ? "unknown" : mailbox.hostOnline ? "ok" : "danger",
      hostText: mailbox.hostOnline
        ? "the host is polling"
        : mailbox.hostSeen
          ? `host last seen ${new Date(mailbox.hostSeen).toLocaleTimeString()} (nothing shared, or offline)`
          : "the host has not polled yet",
    };
  }
</script>

<script lang="ts">
  let { mailbox }: { mailbox: Mailbox } = $props();

  const l = $derived(lights(mailbox));
</script>

<span class="lights" data-testid="lights">
  <span class="light {l.gateway}" title={l.gatewayText} aria-label={l.gatewayText}></span>gateway
  <span class="light {l.host}" title={l.hostText} aria-label={l.hostText}></span>host
</span>

<style>
  .lights {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    font-size: 0.75em;
    color: var(--muted-foreground);
    white-space: nowrap;
  }
  .light {
    width: 0.6rem;
    height: 0.6rem;
    border-radius: 50%;
    background: var(--muted-foreground);
    margin-left: 0.3rem;
  }
  .ok {
    background: var(--ok);
  }
  .warn {
    background: var(--warn);
  }
  .danger {
    background: var(--danger);
  }
</style>
