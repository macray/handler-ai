<script lang="ts">
  // One shared session: the same timeline, permission prompts and composer as the handler web UI,
  // over the encrypted mailbox.
  import Composer from "@handler/acp-view/components/Composer.svelte";
  import { FollowEnd } from "@handler/acp-view/lib/follow";
  import PermissionPrompt from "@handler/acp-view/components/PermissionPrompt.svelte";
  import Timeline from "@handler/acp-view/components/Timeline.svelte";
  import { app } from "../lib/app.svelte";
  import type { SendState } from "../lib/mailbox.svelte";
  import Lights from "./Lights.svelte";

  let draft = $state("");

  const session = $derived(app.current);
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
    void [conn?.session.entries.length, last && "text" in last ? last.text.length : 0, conn?.permissions.length];
    follow.toEnd();
  });

  // Back from sleep (the host detached this device after 90 s without news): attach again.
  $effect(() => {
    if (!detached) return;
    const again = () => {
      if (document.visibilityState === "visible") void app.reattach();
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
    <span class="sub">{session?.label ?? folder} · {session?.harness}</span>
  </div>
  {#if app.mailbox}<Lights mailbox={app.mailbox} />{/if}
</header>

<div class="screen" {@attach follow.attach}>
  {#if conn}
    <Timeline session={conn.session} />
  {:else if app.attaching}
    <p class="text-muted-foreground">Attaching… the host replays the conversation.</p>
  {/if}
  {#if app.error}<p class="error" data-testid="error">✗ {app.error}</p>{/if}
  {#if final}
    <div class="banner">
      <span>{final}</span>
      <button type="button" onclick={() => app.close()}>Back</button>
    </div>
  {:else if detached || (!conn && !app.attaching)}
    <div class="banner">
      <span>Detached{conn?.closed?.reason ? ` (${conn.closed.reason})` : ""}.</span>
      <button type="button" onclick={() => app.reattach()}>Attach again</button>
    </div>
  {/if}
</div>

{#if conn?.permissions.length}
  <div class="asks" data-testid="pinned-permissions">
    {#each conn.permissions as pending (pending.request.toolCall.toolCallId)}
      <PermissionPrompt {pending} />
    {/each}
  </div>
{/if}

{#if conn && !conn.closed}
  <footer>
    <Composer
      bind:text={draft}
      busy={conn.busy}
      commands={conn.session.commands}
      onsend={({ text }) => {
        follow.resume();
        void app.send(text);
      }}
      oncancel={() => conn.cancel()}
      turnStartedAt={conn.turnStartedAt}
      interrupting={conn.interrupting}
      waiting={conn.permissions.length > 0}
    />
    {#if lastSend}<p class="send {lastSend.state}" data-testid="send-state">{SEND_LABEL[lastSend.state]}</p>{/if}
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
    padding: 0 0.75rem;
    max-height: 50%;
    overflow-y: auto;
    flex: none;
  }
  footer {
    padding: 0.5rem 0.75rem;
    padding-bottom: max(0.5rem, env(safe-area-inset-bottom));
    border-top: 1px solid var(--border);
    font-size: 13px;
  }
  .send {
    margin-top: 0.3rem;
    font-size: 0.8em;
    color: var(--muted-foreground);
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
