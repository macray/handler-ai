<script lang="ts" module>
  // Where this device's link is, in a few words and one light (the header of each screen); the
  // two parts it is made of (the gateway reached, the computer listening) are in Settings.
  import type { Mailbox } from "../lib/mailbox.svelte";

  export type Light = "ok" | "warn" | "danger" | "unknown";

  /** Each part's color and what it means (the Settings screen spells it out). */
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
        ? "your computer is listening"
        : mailbox.hostSeen
          ? `your computer last listened at ${new Date(mailbox.hostSeen).toLocaleTimeString()} (nothing shared, or it is off)`
          : "your computer has not listened yet",
    };
  }

  /** The two parts as one: the light and its words. */
  export function status(mailbox: Mailbox | null): { light: Light; words: string; title: string } {
    if (!mailbox || mailbox.reachable === null) return { light: "unknown", words: "Connecting…", title: "connecting to your computer…" };
    const l = lights(mailbox);
    if (mailbox.unauthorized) return { light: "warn", words: "Not recognized", title: l.gatewayText };
    if (!mailbox.reachable) return { light: "danger", words: "No connection", title: l.gatewayText };
    if (!mailbox.hostOnline) return { light: "danger", words: "Computer away", title: l.hostText };
    return { light: "ok", words: "Connected", title: l.hostText };
  }
</script>

<script lang="ts">
  import { ago } from "../lib/time";

  // `updated`: when the host sent what is shown, while it is the last launch's (said quietly)
  let { mailbox, updated = null }: { mailbox: Mailbox | null; updated?: number | null } = $props();

  const l = $derived(status(mailbox));
  const since = $derived(updated === null ? null : ago(updated, mailbox?.now ?? Date.now()));
</script>

<span class="lights" data-testid="lights" title={l.title} role="status">
  <span class="light {l.light}" aria-hidden="true"></span>
  <span class="words">
    <span>{l.words}</span>
    {#if since !== null}<span class="since" data-testid="updated-ago">{since === "now" ? "updated just now" : `updated ${since} ago`}</span>{/if}
  </span>
</span>

<style>
  .lights {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    min-width: 0;
    font-size: 0.75em;
    line-height: 1.25;
    color: var(--muted-foreground);
    white-space: nowrap;
  }
  .words {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .since {
    font-size: 0.9em;
    opacity: 0.8;
  }
  .light {
    flex: none;
    width: 0.5rem;
    height: 0.5rem;
    border-radius: 50%;
    background: var(--muted-foreground);
  }
  .unknown {
    animation: waiting 1.4s var(--ease) infinite alternate; /* a status that works */
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
  @keyframes waiting {
    to {
      opacity: 0.25;
    }
  }
</style>
