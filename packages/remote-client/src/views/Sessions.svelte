<script lang="ts">
  // Sessions (the owner's devices): the shared sessions in one list, those waiting for the person
  // on top (a soft warm tint), then the working, then the idle, each with its state as a word and
  // where it runs, since when (on the right, amber when it needs you) and what it last did; then a
  // trace of those no longer shared; "+" starts a new one. A card that needs you says what it
  // asks; a safe ask is answered there (Reject / Allow, card.ts), any other opens the session.
  // A state is said big over it (BigState): the computer away (the kept Home faded under it,
  // nothing answered from here), "all quiet" while nothing needs the person (no session waiting,
  // no open nudge); as soon as something does, the one-line header with its counts.
  // Apps, the Inbox and this device have their own tabs.
  import { app } from "../lib/app.svelte";
  import { age, asksWords, cardAnswers } from "../lib/card";
  import { homeSessions, placeOf, STATE_WORDS, stateOf, titleOf } from "../lib/home";
  import { computerName } from "../lib/pairing";
  import { ago, when } from "../lib/time";
  import BigState from "./BigState.svelte";
  import CardAnswers from "./CardAnswers.svelte";
  import Docked from "./Docked.svelte";
  import ListHeader, { type Count } from "./ListHeader.svelte";
  import { status } from "./Lights.svelte";

  const home = $derived(homeSessions(app.sessions));
  // the cards' ages follow the clock
  let now = $state(Date.now());
  $effect(() => {
    const tick = setInterval(() => (now = Date.now()), 30_000);
    return () => clearInterval(tick);
  });
  const nothing = $derived(!app.sessions.length);
  // nothing from the host yet (this launch or the last): why it is empty
  const waiting = $derived(app.homeAt === null);
  const idle = $derived(Boolean(app.mailbox?.reachable && !app.mailbox.unauthorized && !app.mailbox.hostOnline));
  const hostAway = $derived(Boolean(app.mailbox?.reachable && app.mailbox.hostSeen && !app.mailbox.hostOnline));
  // a new session needs the computer listening
  const canStart = $derived(
    (app.agents.length > 0 || app.chats.length > 0) && !app.offline && !app.mailbox?.unauthorized && !hostAway,
  );

  const computer = $derived(app.device ? computerName(app.device) : "");
  const link = $derived(status(app.mailbox));
  const asked = $derived(app.inbox.filter((n) => n.kind === "nudge" && n.nudge?.state === "open").length);
  // the Home shown is kept and nothing answers it: the gateway out of reach, or the computer away
  const away = $derived(app.homeAt !== null && (app.offline || hostAway));
  const unreachable = $derived(app.mailbox?.reachable === false);
  // nothing waits for the person: said big, the sessions under it
  const quiet = $derived(
    !waiting && !away && !app.mailbox?.unauthorized && !app.listError && !home.needs.length && !asked,
  );
  // the Home shown is the last launch's: said quietly, until the host answers
  const since = $derived(app.fresh || app.homeAt === null ? null : ago(app.homeAt, app.mailbox?.now ?? Date.now()));
  const hostLine = $derived.by(() => {
    if (unreachable) return `${computer} · can't reach your gateway`;
    if (away && app.mailbox?.hostSeen) return `${computer} · last seen ${when(app.mailbox.hostSeen)}`;
    if (since !== null) return `${computer} · ${since === "now" ? "updated just now" : `updated ${since} ago`}`;
    return link.light === "ok" ? `${computer} · seen now` : computer;
  });

  const counts = $derived.by((): Count[] => {
    const working = home.shared.filter((s) => s.busy).length;
    const rest = home.shared.length - working;
    return [
      ...(home.needs.length ? [{ words: `${home.needs.length} needs you`, tone: "needs" as const }] : []),
      ...(working ? [{ words: `${working} working`, tone: "working" as const }] : []),
      ...(rest ? [{ words: `${rest} idle`, tone: "idle" as const }] : []),
    ];
  });
</script>

{#snippet big(title: string, sub: string, tone: "" | "ok" | "grey")}
  <BigState
    {title}
    host={hostLine}
    light={tone === "grey" ? "unknown" : link.light}
    {sub}
    {tone}
    onrefresh={() => app.refresh()}
    busy={app.loading || !app.mailbox}
    label="{link.words}: {computer}. Refresh"
  />
{/snippet}

<div class="screen">
  {#if away}
    <!-- what is shown is how it was: said first, the list faded under it -->
    <div role="status" data-testid="home-offline">
      {@render big(unreachable ? "no connection" : `${computer} is away`, `As it was at ${when(app.homeAt ?? 0)}. Answer when it is back.`, "grey")}
    </div>
  {:else if waiting && idle}
    <div data-testid="host-idle">
      {@render big(`${computer} is away`, "Handler there reaches this phone only while a session or an app is shared.", "grey")}
    </div>
  {:else if quiet}
    {@render big("all quiet", "Nothing needs you.", "ok")}
  {:else}
    <ListHeader title="Sessions" {counts} />
  {/if}

  <main class="list" class:room={canStart}>
    {#if waiting}
      {#if app.listError}<p class="error fade">{app.listError}</p>{/if}
    {:else if nothing}
      {#if app.listError}
        <p class="error">{app.listError}</p>
      {:else if !away}
        <!-- nothing shared yet: where it is done, in words (on the computer, not here) -->
        <p class="hint fade" data-testid="home-empty">
          Your sessions show here once you share them: on your computer, in a session's header, click
          <span class="nowrap"><svg viewBox="0 0 24 24" aria-hidden="true"><rect width="14" height="20" x="5" y="2" rx="2" /><path d="M12 18h.01" /></svg>
            <strong>On your phone</strong></span>. Click it again to stop.
        </p>
      {/if}
    {/if}

    {#if home.needs.length || home.shared.length || app.unshared.length}
      <!-- one list: those waiting for you first, tinted; the header's chips count them -->
      <section class="fade" class:old={away} data-testid="sessions">
        {#each [...home.needs, ...home.shared] as s (s.id)}
          {@const state = stateOf(s)}
          {@const place = placeOf(s)}
          {@const since = age(s.since, now)}
          <div class="card" class:needs={state === "needs"} data-testid="shared-session">
            <button type="button" class="open" onclick={() => app.open(s)}>
              <span class="top">
                <span class="title">{titleOf(s)}</span>
                {#if since}<time class="age" datetime={s.since} data-testid="card-age">{since}</time>{/if}
              </span>
              {#if state === "needs"}
                {#if place}<span class="meta">{place}</span>{/if}
                <span class="asks">{asksWords(s)}</span>
                {#if s.ask?.summary}<span class="what" data-testid="card-ask">{s.ask.summary}</span>{/if}
              {:else}
                <span class="meta"><span class="state {state}">{state === "working" ? "●" : "○"} {STATE_WORDS[state]}</span>{#if place}<span class="sep" aria-hidden="true">·</span> {place}{/if}</span>
                {#if s.last}<span class="last" data-testid="card-last">{s.last}</span>{/if}
              {/if}
            </button>
            {#if cardAnswers(s) && !away}
              {#key s.ask.toolCallId}
                <CardAnswers busy={app.answering === s.id} onanswer={(answer) => app.answerCard(s, answer)} />
              {/key}
            {/if}
            {#if app.cardError?.id === s.id}<p class="card-error" role="alert">{app.cardError.words}</p>{/if}
          </div>
        {/each}
        {#each app.unshared.slice(0, 3) as u (u.id)}
          <p class="gone" data-testid="no-longer-shared">No longer shared: “{u.title}” <time>{when(u.at)}</time></p>
        {/each}
      </section>
    {/if}

    <Docked quiet={waiting || nothing || away} />
  </main>

  {#if canStart}
    <!-- above the tabs, where the thumb is -->
    <button type="button" class="new fade" onclick={() => app.compose()} aria-label="New session" title="New session" data-testid="new-session-open">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
    </button>
  {/if}
</div>

<style>
  /* what the host sent comes in softly where "Connecting…" was (none under reduced motion) */
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
  /* a session: its title in mono, since when on its right, then its state as a word in its
     colour, and where it runs, then its last line; the card opens it (its answers apart) */
  .card {
    display: flex;
    flex-direction: column;
    border: 1px solid var(--border);
    border-radius: 12px;
    background: var(--card);
    overflow: hidden;
  }
  /* waiting for you: a soft warm tint, no stripe */
  .card.needs {
    background: var(--needs-bg);
    border-color: var(--needs-border);
  }
  .open {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: 0.3rem;
    text-align: left;
    padding: 0.8rem 0.9rem;
    border: 0 !important;
    border-radius: 0 !important;
    background: none;
    font-size: 1em;
    min-height: 3.5rem;
  }
  .open:active {
    background: var(--accent);
  }
  .needs .open:active {
    background: color-mix(in srgb, var(--warn) 12%, var(--needs-bg));
  }
  .top {
    display: flex;
    align-items: baseline;
    gap: 0.75rem;
  }
  .title {
    flex: 1;
    min-width: 0;
    font: 500 0.95em/1.35 var(--mono);
    letter-spacing: -0.01em;
    overflow: hidden;
    text-overflow: ellipsis;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
  }
  .age {
    flex: none;
    font: 0.75em var(--mono);
    color: var(--muted-foreground);
  }
  .needs .age {
    color: var(--warn);
    font-weight: 600;
  }
  .last {
    font-size: 0.83em;
    color: var(--muted-foreground);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  /* what it asks, as the agent titled it */
  .what {
    align-self: flex-start;
    max-width: 100%;
    padding: 0.15rem 0.45rem;
    border: 1px solid var(--needs-border);
    border-radius: 6px;
    background: var(--card);
    font: 0.8em/1.45 var(--mono);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .card-error {
    padding: 0 0.9rem 0.7rem;
    font-size: 0.83em;
    color: var(--danger);
  }
  .meta {
    color: var(--muted-foreground);
    font-size: 0.85em;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .state {
    font-family: var(--mono);
    font-size: 0.95em;
  }
  .state.working {
    color: var(--ok);
  }
  .sep {
    margin: 0 0.1em 0 0.35em; /* the space after it is the text's */
  }
  .asks {
    font-size: 0.88em;
    color: var(--warn);
    font-weight: 500;
  }
  .gone {
    font-size: 0.83em;
    color: var(--muted-foreground);
    padding: 0.1rem 0.25rem;
  }
  .gone time {
    font-family: var(--mono);
    font-size: 0.95em;
  }
  .old {
    opacity: 0.55; /* only shown: nothing answers them */
  }
  /* nothing shared yet: where it is done, in words */
  .hint {
    padding: 0 0.5rem;
    font-size: 0.9em;
    line-height: 1.55;
    color: var(--muted-foreground);
  }
  .hint strong {
    color: var(--foreground);
    font-weight: 600;
  }
  .nowrap {
    white-space: nowrap;
  }
  .hint svg {
    width: 0.95em;
    height: 0.95em;
    vertical-align: -0.12em;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .error {
    color: var(--danger);
  }
  .screen {
    position: relative;
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .list.room {
    padding-bottom: 5.5rem; /* the last row clear of "+" */
  }
  /* New session: above the tabs, on the right, where the thumb is */
  .new {
    position: absolute;
    right: 1rem;
    bottom: 1rem;
    width: 54px;
    height: 54px;
    display: grid;
    place-items: center;
    border-radius: 17px;
    background: var(--foreground);
    color: var(--page);
    box-shadow: 0 8px 20px -6px rgb(28 26 23 / 0.5);
  }
  .new svg {
    width: 24px;
    height: 24px;
    fill: none;
    stroke: currentColor;
    stroke-width: 2.2;
    stroke-linecap: round;
  }

</style>
