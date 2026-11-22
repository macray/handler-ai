<script lang="ts">
  // Ask (D.24), on the owner's phone: say what you want (typed, or spoken: hold the microphone,
  // release to send, slide away to cancel; written down on the host, D.25), the host's router
  // picks which of your apps does it and runs it; the answer here, an agent's read again until it
  // ends (and pushed to your inbox), read aloud as Settings → Voice says. A question back is
  // answered in the same box. Today's asks stay on this phone, read as a short conversation (the
  // latest last, over the mic and the box, where the thumb is); before the first, what you can
  // ask, as chips (a tap fills the box).
  import { app } from "../lib/app.svelte";
  import type { AskAnswer, AskTurn } from "../lib/remote.gen";
  import { canRecord, readAloud, record, type Recording } from "../lib/voice";
  import ListHeader from "./ListHeader.svelte";
  import Offline from "./Offline.svelte";

  type Entry = { said: string; at: string; answer?: AskAnswer; error?: string; spoken?: boolean };

  const KEY = "handler-ask-today";
  const today = new Date().toDateString();

  let entries = $state<Entry[]>(load());
  let words = $state("");
  let busy = $state(false);
  let pending = $state<AskTurn[]>([]); // a question was asked back: its exchange
  let recording = $state<Recording | null>(null);
  let hearing = $state(false);
  let now = $state(Date.now());
  const listens = $derived(app.voice.listens && canRecord());
  let page = $state<HTMLElement | null>(null);
  let box = $state<HTMLTextAreaElement | null>(null);
  // the conversation reads down: the latest at the bottom, scrolled to (entries hold it first)
  const turns = $derived([...entries].reverse());

  $effect(() => {
    void turns.length;
    void turns[turns.length - 1]?.answer;
    if (page) page.scrollTop = page.scrollHeight;
  });

  /** A chip of what you can ask: the box filled with its app's name, for the rest to be said. */
  function fill(name: string): void {
    words = `${name}: `;
    box?.focus();
  }

  $effect(() => {
    if (!recording) return;
    const tick = setInterval(() => (now = Date.now()), 250);
    return () => clearInterval(tick);
  });

  async function hold(event: PointerEvent): Promise<void> {
    event.preventDefault();
    if (recording || busy || hearing) return;
    try {
      recording = await record(() => void release());
      now = Date.now();
    } catch (e) {
      entries = [{ said: "", at: new Date().toISOString(), error: `The microphone: ${(e as Error).message}`, spoken: true }, ...entries];
    }
  }

  function slideAway(): void {
    recording?.cancel();
    recording = null;
  }

  async function release(): Promise<void> {
    const r = recording;
    if (!r) return;
    recording = null;
    hearing = true;
    try {
      const speech = await r.stop();
      const heard = speech ? await app.transcribe(speech) : "";
      if (heard) await send(undefined, heard);
    } catch (e) {
      entries = [{ said: "", at: new Date().toISOString(), error: `Nothing was written down: ${(e as Error).message}`, spoken: true }, ...entries];
    } finally {
      hearing = false;
    }
  }

  function speak(entry: Entry): void {
    const a = entry.answer;
    if (!a || !(entry.spoken ? app.voice.readAloudSpoken : app.voice.readAloudTyped)) return;
    if (a.kind === "pick" && a.run?.state === "running") return;
    readAloud(a.kind === "pick" ? (a.run?.result?.summary ?? a.run?.error ?? a.summary) : (a.question ?? a.summary));
  }

  function load(): Entry[] {
    try {
      const kept = JSON.parse(localStorage.getItem(KEY) ?? "null") as { day: string; entries: Entry[] } | null;
      return kept?.day === today ? kept.entries : [];
    } catch {
      return [];
    }
  }

  function keep(): void {
    localStorage.setItem(KEY, JSON.stringify({ day: today, entries: entries.slice(0, 20) }));
  }

  async function send(event?: Event, heard?: string): Promise<void> {
    event?.preventDefault();
    const said = (heard ?? words).trim();
    if (!said || busy) return;
    busy = true;
    if (heard === undefined) words = "";
    const turns: AskTurn[] = [...pending, { who: "you", text: said }];
    const at = new Date().toISOString();
    const spoken = heard !== undefined;
    entries = [{ said, at, spoken }, ...entries];
    try {
      const answer = await app.ask(turns, spoken);
      entries[0] = { said, at, answer, spoken };
      pending = answer.kind === "needs" ? [...turns, { who: "handler", text: answer.question ?? answer.summary }] : [];
      speak(entries[0]);
      if (answer.kind === "pick" && answer.run?.state === "running") void follow(at);
    } catch (e) {
      entries[0] = { said, at, error: (e as Error).message, spoken };
      pending = [];
    } finally {
      busy = false;
      keep();
    }
  }

  async function follow(at: string): Promise<void> {
    for (;;) {
      const i = entries.findIndex((e) => e.at === at);
      const answer = entries[i]?.answer;
      if (!answer?.run || answer.run.state !== "running" || !answer.run.runId || !answer.app || !answer.action) break;
      await new Promise((r) => setTimeout(r, 3000));
      const run = await app.actionRun(answer.app, answer.action, answer.run.runId).catch(() => null);
      if (!run) break;
      entries[i] = { ...entries[i]!, answer: { ...answer, run } };
      if (run.state !== "running") speak(entries[i]!);
    }
    keep();
  }
</script>

<!-- the icons: the microphone (said by voice, the button), the terminal (a chat about it) -->
{#snippet mic()}
  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" /><path d="M19 10v2a7 7 0 0 1-14 0v-2" /><path d="M12 19v3" /></svg>
{/snippet}

<ListHeader title="Ask" />
<main class="page" bind:this={page} data-testid="ask-screen">
  <Offline />
  <div class="push" aria-hidden="true"></div>
  {#if !entries.length && app.askOptions.length}
    <section class="can">
      <h2>What you can ask</h2>
      <div class="chips">
        {#each app.askOptions as o (`${o.app}/${o.action}`)}
          <button type="button" class="chip" onclick={() => fill(o.app)}><b>{o.app}</b> {o.description}</button>
        {/each}
      </div>
    </section>
  {/if}

  {#each turns as e (e.at)}
    {@const a = e.answer}
    <section class="turn" data-testid="ask-entry">
      {#if e.said}<p class="said">{#if e.spoken}<span class="heard" role="img" aria-label="heard">{@render mic()}</span>{/if}<span>{e.said}</span></p>{/if}
      {#if e.error}
        <div class="ans"><p class="error">{e.error}</p></div>
      {:else if !a}
        <div class="ans"><p class="run"><span class="spin" aria-hidden="true"></span>Finding which app does it…</p></div>
      {:else if a.kind === "pick"}
        <div class="ans">
          <p class="by"><b>{a.app}</b> · {app.askOptions.find((o) => o.app === a.app && o.action === a.action)?.description ?? a.action}</p>
          {#if a.run?.state === "succeeded" && a.run.result}
            <p data-testid="ask-answer"><span class="mark {a.run.result.status}" aria-hidden="true">{a.run.result.status === "ok" ? "✓" : a.run.result.status === "failed" ? "✕" : "!"}</span> {a.run.result.summary}</p>
          {:else if a.run?.state === "failed"}
            <p><span class="mark failed" aria-hidden="true">✕</span> {a.run.error ?? "It failed."}</p>
          {:else}
            <p class="run"><span class="spin" aria-hidden="true"></span>On it: its job is running. Its answer comes here, and to your Inbox.</p>
          {/if}
        </div>
      {:else if a.kind === "needs"}
        <div class="ans q">
          {#if a.app}<p class="by"><b>{a.app}</b>{#if a.action} · {app.askOptions.find((o) => o.app === a.app && o.action === a.action)?.description ?? a.action}{/if}</p>{/if}
          <p data-testid="ask-question">{a.question ?? a.summary}</p>
        </div>
      {:else}
        <div class="ans">
          <p class="by">no app does this</p>
          <p>{a.summary}</p>
          {#if app.chats.length || app.agents.length}
            <!-- New session with what was said in it: on Chat, else a project's agent allowed from the phone -->
            <button type="button" class="chat" onclick={() => app.compose(true, e.said)} data-testid="ask-chat">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m4 17 6-6-6-6" /><path d="M12 19h8" /></svg>Start a chat about it
            </button>
          {/if}
        </div>
      {/if}
    </section>
  {/each}
</main>

{#if listens}
  <div class="bigmic">
    <button
      type="button"
      class="mic"
      class:on={recording}
      aria-label="hold to speak"
      disabled={busy || hearing}
      onpointerdown={hold}
      onpointerup={release}
      onpointerleave={slideAway}
      onpointercancel={slideAway}
      oncontextmenu={(e) => e.preventDefault()}
      data-testid="ask-mic">{@render mic()}</button
    >
    {#if !entries.length || hearing}<span class="hint">{hearing ? "writing down what you said…" : "hold to speak"}</span>{/if}
  </div>
{/if}
<form class="box" onsubmit={send}>
  <textarea
    bind:this={box}
    bind:value={words}
    rows="1"
    placeholder={pending.length ? "Your answer…" : "Ask anything your apps do…"}
    aria-label="what you want"
    data-testid="ask-input"
  ></textarea>
  <button type="submit" class="send" class:on={words.trim() && !busy} disabled={busy || !words.trim()} data-testid="ask-send"
    >{busy ? "…" : pending.length ? "Send" : "Ask"}</button
  >
</form>

{#if recording}
  <!-- the screen dimmed while recording; the mic stays above it, under the thumb -->
  <div class="dim" role="status">
    <span class="rec">● {Math.floor((now - recording.started) / 1000)}s · release to send · slide away to cancel</span>
  </div>
{/if}

<style>
  .page {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 0.25rem 0.75rem 0.75rem;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }
  .push {
    flex: 1; /* the conversation sits at the bottom, over the mic */
  }
  h2 {
    font: 600 10.5px/1.4 var(--mono);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted-foreground);
    margin: 0 0.15rem 0.5rem;
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .chip {
    padding: 6px 11px;
    border: 1px solid var(--border);
    border-radius: 16px;
    background: var(--card);
    font-size: 12.5px;
    color: var(--muted-foreground);
    text-align: left;
  }
  .chip b {
    font: 600 12px var(--mono);
    color: var(--foreground);
    margin-right: 2px;
  }
  .turn {
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }
  /* what you said: an orange bubble on the right */
  .said {
    align-self: flex-end;
    max-width: 86%;
    display: flex;
    gap: 6px;
    align-items: flex-start;
    padding: 8px 12px;
    border-radius: 14px 14px 4px 14px;
    background: var(--accent-soft);
    color: var(--accent-soft-foreground);
    border: 1px solid color-mix(in srgb, var(--primary) 22%, transparent);
    font-size: 0.92em;
    overflow-wrap: anywhere;
  }
  .heard {
    flex: none;
    display: inline-grid;
    margin-top: 3px;
    color: var(--primary);
  }
  .heard :global(svg) {
    width: 14px;
    height: 14px;
  }
  /* its answer: which app took it in small mono, then what it said */
  .ans {
    display: flex;
    flex-direction: column;
    gap: 3px;
    padding: 10px 12px;
    border: 1px solid var(--border);
    border-radius: 14px;
    background: var(--card);
    font-size: 0.92em;
  }
  .ans.q {
    background: color-mix(in srgb, var(--warn-bar) 10%, var(--card));
    border-color: color-mix(in srgb, var(--warn-bar) 28%, var(--card));
  }
  .by {
    font: 600 11px/1.4 var(--mono);
    color: var(--muted-foreground);
  }
  .by b {
    color: var(--foreground);
    font-weight: 600;
  }
  .mark.ok {
    color: var(--ok);
  }
  .mark.attention {
    color: var(--warn);
    font-weight: 700;
  }
  .mark.failed {
    color: var(--danger);
  }
  .run {
    display: flex;
    gap: 8px;
    align-items: center;
    color: var(--muted-foreground);
  }
  .spin {
    flex: none;
    width: 14px;
    height: 14px;
    border-radius: 50%;
    border: 2px solid var(--border);
    border-top-color: var(--ok);
    animation: turn 0.9s linear infinite;
  }
  @keyframes turn {
    to {
      transform: rotate(360deg);
    }
  }
  .chat {
    align-self: stretch;
    margin-top: 8px;
    height: 38px;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    border-radius: 10px;
    background: var(--primary);
    color: var(--primary-foreground);
    font-weight: 600;
  }
  .chat svg {
    width: 14px;
    height: 14px;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .error {
    color: var(--danger);
  }
  /* the big mic, over the box: hold to speak, release to send, slide away to cancel */
  .bigmic {
    flex: none;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    padding: 4px 0 10px;
  }
  .mic {
    position: relative;
    z-index: 2; /* above the dimmed screen while recording */
    width: 64px;
    height: 64px;
    display: grid;
    place-items: center;
    border-radius: 50%;
    background: var(--primary);
    color: var(--primary-foreground);
    box-shadow: 0 6px 16px -6px color-mix(in srgb, var(--primary) 60%, transparent);
    touch-action: none;
    user-select: none;
    -webkit-user-select: none;
    transition: transform var(--dur-1) var(--ease);
  }
  .mic :global(svg) {
    width: 26px;
    height: 26px;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.8;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .mic.on {
    transform: scale(1.2);
    box-shadow:
      0 0 0 14px color-mix(in srgb, var(--primary) 25%, transparent),
      0 0 0 30px color-mix(in srgb, var(--primary) 12%, transparent);
  }
  .hint {
    font: 11.5px var(--mono);
    color: var(--muted-foreground);
  }
  /* the box: one line, its button on the right */
  .box {
    flex: none;
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 0 0.75rem 0.6rem;
    padding: 8px 8px 8px 14px;
    border: 1px solid var(--border);
    border-radius: 18px;
    background: var(--card);
  }
  textarea {
    flex: 1;
    min-width: 0;
    max-height: 6.5em;
    field-sizing: content;
    font: inherit;
    border: 0;
    background: transparent;
    color: inherit;
    resize: none;
    outline: none;
  }
  .send {
    flex: none;
    height: 36px;
    padding: 0 14px;
    border-radius: 12px;
    background: var(--muted);
    color: var(--muted-foreground);
    font-weight: 600;
  }
  .send.on {
    background: var(--primary);
    color: var(--primary-foreground);
  }
  .dim {
    position: fixed;
    inset: 0;
    z-index: 1;
    display: flex;
    align-items: flex-end;
    justify-content: center;
    padding: 0 1.5rem calc(env(safe-area-inset-bottom) + 250px);
    background: rgb(28 26 23 / 0.86);
    pointer-events: none; /* the mic keeps the touch: release sends, sliding away cancels */
    animation: fade var(--dur-1) var(--ease) backwards;
  }
  .rec {
    font: 12px/1.5 var(--mono);
    color: #fff;
    text-align: center;
  }
  @keyframes fade {
    from {
      opacity: 0;
    }
  }
</style>
