<script lang="ts">
  // The tabs at the bottom, where the thumb is: Ask (when the host offers something to ask),
  // Sessions, Apps, Inbox, Settings; an icon and a word each, a soft pill behind the one shown, an
  // amber count of what waits for the person (sessions that need you, open nudges). Its height is
  // index.html's `.s-tabs` (the place kept before the app knows its screen): nothing moves.
  import { app, type Tab } from "../lib/app.svelte";
  import { homeSessions } from "../lib/home";

  const WORDS: Record<Tab, string> = { ask: "Ask", sessions: "Sessions", apps: "Apps", inbox: "Inbox", settings: "Settings" };
  const needs = $derived(homeSessions(app.sessions).needs.length);
  const asked = $derived(app.inbox.filter((n) => n.kind === "nudge" && n.nudge?.state === "open").length);
  const badge = (t: Tab): number => (t === "sessions" ? needs : t === "inbox" ? asked : 0);
</script>

<nav class="tabs" aria-label="screens">
  {#each app.tabs as t (t)}
    {@const count = badge(t)}
    <button
      type="button"
      class:on={app.screen === t}
      aria-current={app.screen === t ? "page" : undefined}
      aria-label={count ? `${WORDS[t]}, ${count} waiting for you` : undefined}
      onclick={() => app.chooseTab(t)}
      data-testid="tab-{t}"
    >
      <span class="pill">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          {#if t === "ask"}<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          {:else if t === "sessions"}<path d="m4 17 6-6-6-6" /><path d="M12 19h8" />
          {:else if t === "apps"}<rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" />
          {:else if t === "inbox"}<path d="M22 12h-6l-2 3h-4l-2-3H2" /><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
          {:else}<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" /><circle cx="12" cy="12" r="3" />{/if}
        </svg>
        {#if count}<span class="badge" aria-hidden="true" data-testid="tab-{t}-count">{count}</span>{/if}
      </span>
      <span class="word">{WORDS[t]}</span>
    </button>
  {/each}
</nav>

<style>
  /* 58 px and the bottom's safe area, border included: index.html's `.s-tabs` and App's place */
  .tabs {
    flex: none;
    box-sizing: content-box;
    height: 57px;
    display: flex;
    border-top: 1px solid var(--border);
    padding: 0 0.25rem env(safe-area-inset-bottom);
    background: var(--card);
  }
  button {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 2px;
    border: 0;
    font: 10.5px/1.2 var(--mono);
    color: var(--muted-foreground);
  }
  button.on {
    color: var(--primary);
    font-weight: 600;
  }
  .pill {
    position: relative;
    display: grid;
    place-items: center;
    width: 48px;
    height: 28px;
    border-radius: 14px;
    transition: background var(--dur-1) var(--ease);
  }
  .on .pill {
    background: var(--accent-soft);
  }
  svg {
    width: 22px;
    height: 22px;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.8;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .badge {
    position: absolute;
    top: -5px;
    right: -6px;
    min-width: 17px;
    height: 17px;
    padding: 0 4px;
    box-sizing: content-box;
    border-radius: 9px;
    border: 2px solid var(--card);
    background: var(--warn-bar);
    color: #1c1a17;
    font: 700 10px/17px var(--mono);
    text-align: center;
  }
  .word {
    white-space: nowrap;
  }
</style>
