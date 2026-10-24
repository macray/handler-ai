<script lang="ts">
  // One shared session: the same timeline, permission prompts and composer as the handler web UI,
  // over the encrypted mailbox.
  import Composer from "@handler/acp-view/components/Composer.svelte";
  import { FollowEnd } from "@handler/acp-view/lib/follow";
  import PermissionPrompt from "@handler/acp-view/components/PermissionPrompt.svelte";
  import Timeline from "@handler/acp-view/components/Timeline.svelte";
  import { dragSheet, flungDown, flungUp } from "@handler/acp-view/lib/sheet";
  import { activity } from "@handler/acp-view/lib/tools";
  import { app, loadDraft, saveDraft } from "../lib/app.svelte";
  import type { SendState } from "../lib/mailbox.svelte";
  import Lights from "./Lights.svelte";

  const session = $derived(app.current);
  const draftOf = app.current?.id ?? ""; // this screen shows one session
  let draft = $state(loadDraft(draftOf));
  $effect(() => saveDraft(draftOf, draft));
  const folder = $derived(session?.scope.split("/").filter(Boolean).at(-1) ?? "");
  const conn = $derived(app.conn);
  const final = $derived(app.whyClosed());
  const detached = $derived(Boolean(conn?.closed) && !final);

  const SEND_LABEL: Record<SendState, string> = {
    sending: "sending…",
    sent: "sent — waiting for the host to fetch it",
    fetched: "fetched by the host",
    delivered: "delivered",
    expired: "expired: the host refused it as too old",
    failed: "not sent: the gateway is unreachable",
  };
  const lastSend = $derived(app.mailbox?.lastSend);

  // Follow new output while the view is at its end.
  const follow = new FollowEnd();
  $effect(() => {
    const last = conn?.session.entries.at(-1);
    void [conn?.session.entries.length, last && "text" in last ? last.text.length : 0, conn?.permissions.length, conn?.session.lastStop];
    follow.toEnd();
  });

  // The permission requests are a sheet from the bottom: open (the question and its answers),
  // full (dragged up: a long diff), or down to a bar (dragged down: read the conversation first;
  // a tap brings it back). A new request opens it.
  let sheet = $state<"open" | "full" | "down">("open");
  const asked = $derived(conn?.permissions[0]?.request.toolCall);
  $effect(() => {
    void asked?.toolCallId;
    sheet = "open";
  });
  function released(dy: number, velocity: number): boolean {
    if (flungDown(dy, velocity)) {
      if (sheet === "full") {
        sheet = "open";
        return false;
      }
      sheet = "down";
      return true;
    }
    if (flungUp(dy, velocity)) sheet = "full";
    return false;
  }

  // Back from sleep (the host detaches this device after 90 s without news): attach again, as
  // soon as the screen is back on when it may have been detached, before anything is sent.
  $effect(() => {
    const again = () => {
      if (document.visibilityState === "visible" && (detached || app.mailbox?.mayBeDetached)) void app.reattach();
    };
    again();
    document.addEventListener("visibilitychange", again);
    return () => document.removeEventListener("visibilitychange", again);
  });
</script>

<header class="bar">
  <button type="button" class="back" onclick={() => app.close()} aria-label="back to the list">‹</button>
  <div class="head">
    <span class="title">{conn?.session.title ?? session?.title ?? session?.label ?? folder}</span>
    <span class="sub">{session?.label ?? folder} · {session?.harness ?? "the model alone"}</span>
  </div>
  {#if app.mailbox}<Lights mailbox={app.mailbox} />{/if}
</header>

<div class="screen" {@attach follow.attach}>
  {#if conn}
    <Timeline session={conn.session} root={session?.scope} busy={conn.busy} asking={conn.permissions.map((p) => p.request.toolCall.toolCallId)} />
  {:else if app.attaching}
    <p class="text-muted-foreground">Attaching… the host replays the conversation.</p>
  {/if}
  {#if app.error}<p class="error" data-testid="error">✗ {app.error}</p>{/if}
  {#if final}
    <div class="banner">
      <span>{final}</span>
      <button type="button" onclick={() => app.close()}>Back</button>
    </div>
  {:else if conn && app.attaching}
    <p class="text-muted-foreground" data-testid="reattaching">Reconnecting…</p>
  {:else if detached || (!conn && !app.attaching)}
    <div class="banner">
      <span>Detached{conn?.closed?.reason ? ` (${conn.closed.reason})` : ""}.</span>
      <button type="button" onclick={() => app.reattach()}>Attach again</button>
    </div>
  {/if}
</div>

{#if conn?.permissions.length}
  {#if sheet === "down"}
    <button type="button" class="asks-bar" onclick={() => (sheet = "open")} data-testid="permission-bar">
      <span class="dot" aria-hidden="true"></span><span class="what">Needs you · {asked?.title ?? "a permission"}</span><span class="open">Answer</span>
    </button>
  {:else}
    <div class="asks" class:full={sheet === "full"} data-sheet data-testid="pinned-permissions">
      <div class="handle" aria-hidden="true" {@attach dragSheet(released)}></div>
      {#each conn.permissions as pending (pending.request.toolCall.toolCallId)}
        <PermissionPrompt {pending} root={session?.scope} />
      {/each}
    </div>
  {/if}
{/if}

{#if conn && !conn.closed}
  <footer>
    <Composer
      bind:text={draft}
      busy={conn.busy}
      activity={activity(conn.session.entries, session?.scope)}
      commands={conn.session.commands}
      onsend={({ text }) => {
        follow.resume();
        void app.send(text).then((sent) => {
          if (!sent) draft = [text, draft].filter(Boolean).join("\n\n");
        });
      }}
      oncancel={() => conn.cancel()}
      turnStartedAt={conn.turnStartedAt}
      interrupting={conn.interrupting}
      waiting={conn.permissions.length > 0}
    />
    <!-- where a message is, floating above the composer (no line of the screen for it); once
         delivered nothing is said: the agent's answer says it -->
    {#if lastSend && lastSend.state !== "delivered"}<p class="send {lastSend.state}" data-testid="send-state">{SEND_LABEL[lastSend.state]}</p>{/if}
  </footer>
{/if}

<style>
  .bar {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.6rem 0.75rem;
    padding-top: max(0.6rem, env(safe-area-inset-top));
    border-bottom: 1px solid var(--border);
    background: var(--card);
    font-family: "Inter Variable", "Inter", system-ui, sans-serif;
  }
  .back {
    font-size: 1.6em;
    line-height: 1;
    padding: 0 0.5rem 0.1rem;
  }
  .head {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
  }
  .title {
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sub {
    font-size: 0.75em;
    color: var(--muted-foreground);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .screen {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 0.75rem;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
    font-size: 13px;
  }
  .asks {
    position: relative;
    padding: 1.25rem 0.75rem 0;
    max-height: 55%;
    overflow-y: auto;
    flex: none;
    background: var(--card);
    border-top: 1px solid var(--border);
    border-radius: 16px 16px 0 0;
    box-shadow: 0 -12px 32px -12px rgb(0 0 0 / 0.6);
    transition:
      transform var(--dur-3) var(--ease),
      max-height var(--dur-3) var(--ease);
    animation: sheet-in var(--dur-3) var(--ease) backwards;
  }
  .asks.full {
    max-height: 88%;
  }
  @keyframes sheet-in {
    from {
      transform: translateY(100%);
    }
  }
  .handle {
    position: absolute;
    inset: 0 0 auto 0;
    height: 1.25rem;
    touch-action: none;
  }
  .handle::after {
    content: "";
    position: absolute;
    top: 0.45rem;
    left: 50%;
    translate: -50% 0;
    width: 2.5rem;
    height: 4px;
    border-radius: 999px;
    background: var(--border);
  }
  .asks-bar {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    min-height: 2.75rem;
    margin: 0 0.75rem 0.5rem;
    padding: 0 0.9rem;
    border: 1px solid var(--warn) !important;
    border-radius: 999px !important;
    background: color-mix(in srgb, var(--warn) 12%, var(--background));
    color: var(--warn);
    font-family: var(--sans);
    font-size: 14px;
    text-align: left;
    animation: enter var(--dur-2) var(--ease) backwards;
  }
  .asks-bar .dot {
    width: 0.55rem;
    height: 0.55rem;
    flex: none;
    border-radius: 50%;
    background: currentColor;
  }
  .asks-bar .what {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--foreground);
  }
  .asks-bar .open {
    font-weight: 600;
  }
  footer {
    position: relative;
    padding: 0.5rem 0.75rem;
    padding-bottom: max(0.5rem, env(safe-area-inset-bottom));
    border-top: 1px solid var(--border);
    font-size: 13px;
  }
  .send {
    position: absolute;
    right: 0.75rem;
    bottom: calc(100% + 0.4rem);
    max-width: calc(100% - 1.5rem);
    margin: 0;
    padding: 0.15rem 0.7rem;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--card);
    box-shadow: 0 4px 14px -4px rgb(0 0 0 / 0.5);
    font-size: 12px;
    color: var(--muted-foreground);
    pointer-events: none; /* never in the way of a tap (a permission's answers under it) */
    animation: enter var(--dur-2) var(--ease) backwards;
  }
  .send.expired,
  .send.failed {
    border-color: color-mix(in srgb, var(--danger) 50%, transparent);
  }
  .send.expired,
  .send.failed,
  .error {
    color: var(--danger);
  }
  .banner {
    display: flex;
    gap: 1ch;
    align-items: center;
    justify-content: space-between;
    border: 1px dashed var(--warn);
    border-radius: 6px;
    padding: 0.5rem 0.75rem;
    color: var(--warn);
  }
  .banner button {
    color: var(--prompt);
    border-color: var(--prompt);
    padding: 0.2rem 0.7rem;
    white-space: nowrap;
  }
</style>
