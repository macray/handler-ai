<script lang="ts">
  // Home: what the host shares with this device's person — sessions (the owner only), mini apps,
  // what apps told them, and calls waiting for the computer. The device itself is in Settings.
  import { app } from "../lib/app.svelte";
  import type { SharedSession } from "../lib/remote.gen";
  import Lights from "./Lights.svelte";

  function basename(path: string): string {
    return path.split("/").filter(Boolean).at(-1) ?? path;
  }

  function ago(at: string): string {
    const s = Math.max(0, (Date.now() - new Date(at).getTime()) / 1000);
    if (Number.isNaN(s)) return "";
    if (s < 60) return "now";
    if (s < 3600) return `${Math.floor(s / 60)} min`;
    if (s < 86400) return `${Math.floor(s / 3600)} h`;
    return new Date(at).toLocaleDateString();
  }

  // the ones waiting for an answer first, then the working ones; grouped by project
  const rank = (s: SharedSession): number => (s.pendingPermissions ? 0 : s.busy ? 1 : 2);
  const sessions = $derived([...app.sessions].sort((a, b) => rank(a) - rank(b)));
  const groups = $derived.by(() => {
    const byProject = new Map<string, SharedSession[]>();
    for (const s of sessions) {
      const name = s.project ?? "Other";
      byProject.set(name, [...(byProject.get(name) ?? []), s]);
    }
    return [...byProject.entries()];
  });
  const owner = $derived(app.scope === "all");
  const hostAway = $derived(Boolean(app.mailbox?.reachable && app.mailbox.hostSeen && !app.mailbox.hostOnline));
  const nothing = $derived(!app.sessions.length && !app.apps.length && !app.agents.length);

  // back on the page (the phone slept, another app was in front): the list may be stale
  $effect(() => {
    const again = () => {
      if (document.visibilityState === "visible" && !app.loading) void app.refresh();
    };
    document.addEventListener("visibilitychange", again);
    return () => document.removeEventListener("visibilitychange", again);
  });
</script>

<header class="bar">
  <h1>Handler remote</h1>
  {#if app.mailbox}<Lights mailbox={app.mailbox} />{/if}
  <button
    type="button"
    class="icon"
    class:spin={app.loading}
    onclick={() => app.refresh()}
    disabled={app.loading}
    aria-label="Refresh"
    title="Refresh"
  >
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 12a8 8 0 1 1-2.34-5.66M20 4v5h-5" /></svg>
  </button>
  <button type="button" class="icon" onclick={() => (app.settings = true)} aria-label="Settings" title="Settings" data-testid="open-settings">
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="3" />
      <path
        d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"
      />
    </svg>
  </button>
</header>

<main class="list">
  {#if app.mailbox?.unauthorized}
    <p class="banner error">
      The gateway does not know this device: it was revoked, or Handler could not register it yet.
      <button type="button" onclick={() => (app.settings = true)}>Settings</button>
    </p>
  {:else if hostAway && !nothing}
    <p class="banner" data-testid="host-away">
      Your computer is not listening right now: apps work from their offline copy, their actions wait for it.
    </p>
  {/if}

  {#if nothing}
    {#if app.loading}
      <p class="empty">Asking the host…</p>
      {#if app.mailbox?.reachable && !app.mailbox.hostOnline}
        <p class="empty" data-testid="host-idle">
          The host is not listening right now: it polls the gateway only while a session or an app is shared. Share one in
          Handler and it appears here.
        </p>
      {/if}
    {:else if app.listError}
      <p class="error">{app.listError}</p>
    {:else}
      <div class="empty">
        <p><strong>Nothing is shared with you yet.</strong></p>
        {#if owner}
          <p>In Handler: turn on a session's <strong>Remote</strong> switch, or share an app with a person (Apps page).</p>
        {:else}
          <p>Ask the owner of the computer to share an app with you.</p>
        {/if}
      </div>
    {/if}
  {/if}

  {#if owner && app.agents.length}
    <button type="button" class="new" onclick={() => (app.composing = true)} data-testid="new-session-open">+ New session</button>
  {/if}

  {#each groups as [project, list] (project)}
    <section data-testid="session-group">
      <h2>{project} <span class="count">{list.length}</span></h2>
      {#each list as s (s.id)}
        <button type="button" class="item" onclick={() => app.open(s)} data-testid="shared-session">
          <span class="dot {s.pendingPermissions ? 'needs' : s.busy ? 'busy' : ''}" aria-hidden="true"></span>
          <span class="text">
            <span class="title">{s.title ?? s.agent ?? s.label ?? basename(s.scope)}</span>
            <span class="meta">{s.agent ?? s.label ?? basename(s.scope)} · {s.harness}</span>
          </span>
          {#if s.pendingPermissions}<span class="pill needs">needs you</span>
          {:else if s.busy}<span class="pill busy">working</span>
          {:else}<span class="pill">idle</span>{/if}
        </button>
      {/each}
    </section>
  {/each}

  {#if app.apps.length}
    <section>
      <h2>Apps <span class="count">{app.apps.length}</span></h2>
      {#each app.apps as a (a.name)}
        <button type="button" class="item" onclick={() => app.openApp(a)} data-testid="shared-app">
          <span class="tile" aria-hidden="true">{a.name.slice(0, 1).toUpperCase()}</span>
          <span class="text">
            <span class="title">{a.name}</span>
            {#if a.description}<span class="meta">{a.description}</span>{/if}
          </span>
          <span class="chevron" aria-hidden="true">›</span>
        </button>
      {/each}
    </section>
  {/if}

  {#if app.calls.length}
    <section class="calls" data-testid="queued-calls">
      <h2>
        Waiting for your computer
        {#if app.calls.some((c) => c.done)}<button type="button" class="link" onclick={() => app.forgetDoneCalls()}>Clear done</button>{/if}
      </h2>
      <ul class="card">
        {#each app.calls as c (c.id)}
          <li>
            <span class="line"><strong>{c.app}</strong> · {c.route.split(" ")[1]}</span>
            {#if c.done}<span class="pill busy">done{c.status && c.status >= 400 ? ` (${c.status})` : ""}</span>
            {:else}<span class="pill needs">waiting</span>{/if}
          </li>
        {/each}
      </ul>
    </section>
  {/if}

  {#if app.inbox.length}
    <section>
      <h2>Inbox</h2>
      <ul class="card">
        {#each app.inbox.slice(0, 5) as n (n.id)}
          <li class="note" data-testid="notification">
            <span class="text">
              <span class="title">{n.status === "failed" ? `${n.title}: failed` : n.title}</span>
              <span class="meta">{n.summary ? `${n.name} — ${n.summary}` : n.name}</span>
            </span>
            <time datetime={n.at}>{ago(n.at)}</time>
          </li>
        {/each}
      </ul>
    </section>
  {/if}
</main>

<style>
  .new {
    align-self: flex-start;
    padding: 0.55rem 0.9rem;
    border-radius: 999px;
    background: var(--primary);
    color: var(--primary-foreground);
    font-weight: 500;
  }
  .bar {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.6rem 0.5rem 0.6rem 1rem;
    padding-top: max(0.6rem, env(safe-area-inset-top));
    border-bottom: 1px solid var(--border);
    background: var(--card);
  }
  h1 {
    flex: 1;
    font-size: 1.05em;
    font-weight: 600;
    white-space: nowrap;
  }
  .icon {
    display: grid;
    place-items: center;
    width: 2.25rem;
    height: 2.25rem;
    border-radius: 999px;
    color: var(--muted-foreground);
  }
  .icon:active {
    background: var(--accent);
  }
  .icon svg {
    width: 1.2rem;
    height: 1.2rem;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.8;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .spin svg {
    animation: spin 0.9s linear infinite;
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
  .list {
    flex: 1;
    overflow-y: auto;
    padding: 0.75rem 0.75rem max(1rem, env(safe-area-inset-bottom));
    display: flex;
    flex-direction: column;
    gap: 1.1rem;
  }
  section {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  h2 {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.75em;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--muted-foreground);
    padding: 0 0.25rem;
  }
  .count {
    font-weight: 500;
    opacity: 0.8;
  }
  .link {
    margin-left: auto;
    text-transform: none;
    letter-spacing: 0;
    font-weight: 500;
    color: var(--link);
  }
  .item {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    text-align: left;
    padding: 0.75rem 0.9rem;
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--card);
    font-size: 1em;
    min-height: 3.5rem;
  }
  .item:active {
    background: var(--accent);
  }
  .text {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
  }
  .line {
    flex: 1;
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .title {
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .meta {
    color: var(--muted-foreground);
    font-size: 0.85em;
    overflow: hidden;
    text-overflow: ellipsis;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
  }
  .dot {
    flex: none;
    width: 0.55rem;
    height: 0.55rem;
    border-radius: 50%;
    background: var(--border);
  }
  .dot.needs {
    background: var(--warn);
  }
  .dot.busy {
    background: var(--ok);
  }
  .tile {
    flex: none;
    display: grid;
    place-items: center;
    width: 2.25rem;
    height: 2.25rem;
    border-radius: 8px;
    background: var(--primary);
    color: var(--primary-foreground);
    font-weight: 600;
  }
  .chevron {
    color: var(--muted-foreground);
    font-size: 1.4em;
    line-height: 1;
  }
  .pill {
    flex: none;
    font-size: 0.75em;
    padding: 0.15rem 0.55rem;
    border-radius: 999px;
    background: var(--muted);
    color: var(--muted-foreground);
    white-space: nowrap;
  }
  .pill.needs {
    color: var(--warn);
    background: color-mix(in srgb, var(--warn) 14%, transparent);
  }
  .pill.busy {
    color: var(--ok);
    background: color-mix(in srgb, var(--ok) 14%, transparent);
  }
  .card {
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--card);
    font-size: 0.9em;
  }
  .card li {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.6rem 0.9rem;
  }
  .card li + li {
    border-top: 1px solid var(--border);
  }
  .note .title {
    font-weight: 500;
  }
  time {
    flex: none;
    align-self: flex-start;
    font-size: 0.8em;
    color: var(--muted-foreground);
  }
  .banner {
    padding: 0.6rem 0.8rem;
    border-radius: 10px;
    font-size: 0.85em;
    color: var(--warn);
    background: color-mix(in srgb, var(--warn) 10%, transparent);
  }
  .banner.error {
    color: var(--danger);
    background: color-mix(in srgb, var(--danger) 10%, transparent);
  }
  .banner button {
    text-decoration: underline;
    margin-left: 0.25rem;
  }
  .empty {
    color: var(--muted-foreground);
    padding: 1rem 0.25rem;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }
  .empty strong {
    color: var(--foreground);
  }
  .error {
    color: var(--danger);
  }
</style>
