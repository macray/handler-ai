<script lang="ts">
  // Inbox: what apps ask the person to do (open nudges, their form in the card, tinted) first, then
  // what Handler told them (the last 5, by day; an icon per source, red when it failed, amber for
  // attention; an unread dot until tapped here; one tied to a shared app opens it), then the calls
  // left for when the computer is back.
  import { app } from "../lib/app.svelte";
  import { computerName } from "../lib/pairing";
  import type { InboxMessage } from "../lib/remote.gen";
  import { ago } from "../lib/time";
  import Docked from "./Docked.svelte";
  import ListHeader, { type Count } from "./ListHeader.svelte";
  import NudgeCard from "./NudgeCard.svelte";
  import Offline from "./Offline.svelte";

  // what apps ask you to do, open, first (the host lists them first); then the rest of the inbox
  const asked = $derived(app.inbox.filter((n) => n.kind === "nudge" && n.nudge?.state === "open"));
  // the 5 newest
  const told = $derived(
    app.inbox
      .filter((n) => !asked.includes(n))
      .toSorted((a, b) => Date.parse(b.at) - Date.parse(a.at))
      .slice(0, 5),
  );
  const unread = $derived(told.filter((n) => !app.isRead(n)).length);
  const computer = $derived(app.device ? computerName(app.device) : "your computer");
  const clock = (at: number): string => new Date(at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  // the messages by day: today's, then the earlier ones
  const days = $derived.by(() => {
    const today = new Date().toDateString();
    const isToday = (n: InboxMessage) => new Date(n.at).toDateString() === today;
    return [
      { words: "Today", items: told.filter(isToday) },
      { words: "Earlier", items: told.filter((n) => !isToday(n)) },
    ].filter((d) => d.items.length);
  });

  // a tap reads it (on this phone) and shows its whole summary; again, folds it
  let open = $state<string | null>(null);
  function tap(id: string): void {
    app.markRead(id);
    open = open === id ? null : id;
  }
  const waiting = $derived(app.homeAt === null);
  const nothing = $derived(!asked.length && !told.length && !app.calls.length);

  const counts = $derived.by((): Count[] => [
    ...(asked.length ? [{ words: `${asked.length} asked of you`, tone: "needs" as const }] : []),
    ...(unread ? [{ words: `${unread} new` }] : []),
  ]);
</script>

<!-- where a message comes from, as a plain icon -->
{#snippet icon(source: InboxMessage["source"])}
  <svg viewBox="0 0 24 24">
    {#if source === "app"}<rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" />
    {:else if source === "automation"}<circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" />
    {:else if source === "plan"}<path d="M3 6h.01M3 12h.01M3 18h.01M8 6h13M8 12h13M8 18h13" />
    {:else if source === "session"}<path d="m5 17 6-6-6-6M12 19h7" />
    {:else if source === "ask"}<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z" />
    {:else}<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" /><path d="M14 2v4a2 2 0 0 0 2 2h4M16 13H8M16 17H8M10 9H8" />{/if}
  </svg>
{/snippet}

<ListHeader title="Inbox" {counts} />

<main class="list">
  <Offline />
  {#if app.listError && (waiting || nothing)}
    <p class="error fade">{app.listError}</p>
  {:else if !waiting && nothing}
    <div class="empty fade" data-testid="inbox-empty">
      <p><strong>Nothing in your inbox.</strong></p>
      <p>What your apps, automations and sessions tell you comes here.</p>
    </div>
  {/if}

  {#if asked.length}
    <!-- what is asked of you: a card each, tinted, its form in it -->
    <section class="fade" class:old={app.offline} data-testid="nudges">
      {#each asked as n (n.id)}<ul class="card asked"><NudgeCard message={n} ago={ago(n.at)} /></ul>{/each}
    </section>
  {/if}

  {#each days as d (d.words)}
    <section class="fade">
      <h2>{d.words}</h2>
      <ul class="card">
        {#each d.items as n (n.id)}
          {#if n.kind === "nudge" && n.nudge}<NudgeCard message={n} ago={ago(n.at)} />{:else}
          {@const opens = n.app ? app.apps.find((a) => a.name === n.app) : undefined}
          {@const unread = !app.isRead(n)}
          <li class="note" class:unread data-testid="notification">
            <button type="button" class="hit" aria-expanded={open === n.id} onclick={() => tap(n.id)}>
              <span class="icon {n.status ?? ''}" aria-hidden="true">{@render icon(n.source)}</span>
              <span class="text">
                <span class="title">{#if unread}<span class="dot" aria-label="new"></span>{/if}{n.status === "failed" ? `${n.title}: failed` : n.title}</span>
                <span class="meta" class:full={open === n.id}>{n.source} · {n.summary ?? n.name}</span>
              </span>
              <time datetime={n.at}>{ago(n.at)}</time>
            </button>
            {#if opens}
              <button type="button" class="link open" onclick={() => { app.markRead(n.id); app.openApp(opens); }} data-testid="notification-open-app">Open {opens.name} ›</button>
            {/if}
          </li>
          {/if}
        {/each}
      </ul>
    </section>
  {/each}

  {#if app.calls.length}
    <section class="fade" data-testid="queued-calls">
      <h2>
        Waiting for {computer}
        {#if app.calls.some((c) => c.done)}<button type="button" class="link" onclick={() => app.forgetDoneCalls()}>Clear done</button>{/if}
      </h2>
      <ul class="card">
        {#each app.calls as c (c.id)}
          <li class="call">
            <span class="icon" aria-hidden="true">{@render icon("app")}</span>
            <span class="text">
              <span class="title">{c.app} · {c.route.split(" ")[1]}</span>
              <span class="meta">queued <time>{clock(c.at)}</time></span>
            </span>
            {#if c.done}<span class="pill busy">done{c.status && c.status >= 400 ? ` (${c.status})` : ""}</span>
            {:else}<span class="pill needs">waiting</span>{/if}
          </li>
        {/each}
      </ul>
    </section>
  {/if}
  <Docked quiet={waiting || nothing} />
</main>

<style>
  .fade {
    animation: fade var(--dur-2) var(--ease) backwards;
  }
  @keyframes fade {
    from {
      opacity: 0;
    }
  }
  .list {
    flex: 1;
    overflow-y: auto;
    padding: 0.75rem;
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
    font: 500 0.72em var(--mono);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted-foreground);
    padding: 0 0.25rem;
  }
  .link {
    margin-left: auto;
    text-transform: none;
    letter-spacing: 0;
    font-weight: 500;
    color: var(--link);
  }
  .link.open {
    margin: -0.35rem 0 0 3.15rem;
    align-self: flex-start;
    padding: 0 0 0.5rem;
    min-height: 36px;
    font-size: 0.9em;
  }
  .card {
    border: 1px solid var(--border);
    border-radius: 12px;
    background: var(--card);
    font-size: 0.9em;
    overflow: hidden;
  }
  /* asked of you: the soft warm tint, never a stripe */
  .card.asked {
    background: var(--needs-bg);
    border-color: var(--needs-border);
  }
  .card :global(li + li) {
    border-top: 1px solid var(--border);
  }
  .note {
    display: flex;
    flex-direction: column;
  }
  .hit,
  .call {
    display: flex;
    align-items: flex-start;
    gap: 0.75rem;
    padding: 0.7rem 0.9rem;
    text-align: left;
    font-size: 1em;
    width: 100%;
  }
  .hit:active {
    background: var(--accent);
  }
  .icon {
    flex: none;
    display: grid;
    place-items: center;
    width: 2.1rem;
    height: 2.1rem;
    border-radius: 9px;
    background: var(--muted);
    color: var(--muted-foreground);
  }
  .icon.failed {
    background: color-mix(in srgb, var(--danger) 12%, var(--card));
    color: var(--danger);
  }
  .icon.attention {
    background: color-mix(in srgb, var(--warn) 14%, var(--card));
    color: var(--warn);
  }
  .icon svg {
    width: 1.05rem;
    height: 1.05rem;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .text {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
  }
  .title {
    font: 500 0.95em/1.35 var(--mono);
    letter-spacing: -0.01em;
    overflow-wrap: anywhere;
  }
  .note:not(.unread) .title {
    color: var(--muted-foreground);
  }
  .dot {
    display: inline-block;
    width: 0.45rem;
    height: 0.45rem;
    margin: 0 0.45rem 0.1rem 0;
    border-radius: 50%;
    background: var(--primary);
    vertical-align: middle;
  }
  .meta {
    color: var(--muted-foreground);
    font-size: 0.88em;
    overflow: hidden;
    text-overflow: ellipsis;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
  }
  .meta.full {
    display: block;
  }
  time {
    flex: none;
    font: 0.78em var(--mono);
    color: var(--muted-foreground);
  }
  .meta time {
    font-size: 1em;
  }
  .call {
    align-items: center;
  }
  .pill {
    flex: none;
    font: 0.75em var(--mono);
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
  .old {
    opacity: 0.55; /* only shown: nothing answers them */
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
