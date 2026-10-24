<script lang="ts">
  // Ask (D.24), on the owner's phone: say what you want (typed, or spoken: hold the microphone,
  // release to send, slide away to cancel; written down on the host, D.25), the host's router
  // picks which of your apps does it and runs it; the answer here, an agent's read again until it
  // ends (and pushed to your inbox), read aloud as Settings → Voice says. A question back is
  // answered in the same box. Today's asks stay on this phone; below, what you can ask.
  import { app } from "../lib/app.svelte";
  import type { AskAnswer, AskTurn } from "../lib/remote.gen";
  import { canRecord, readAloud, record, type Recording } from "../lib/voice";

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
      const answer = await app.ask(turns);
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

<header class="top"><h1>Ask</h1></header>
<main class="page" data-testid="ask-screen">
  <form class="box" onsubmit={send}>
    <textarea bind:value={words} rows="2" placeholder={pending.length ? "Your answer…" : "Ask anything your apps do…"} aria-label="what you want" data-testid="ask-input"></textarea>
    <div class="row">
      {#if recording}
        <span class="hint rec">● {Math.floor((now - recording.started) / 1000)}s · release to send · slide away to cancel</span>
      {:else}
        <span class="hint">{hearing ? "Writing down what you said…" : pending.length ? "It asked you something" : listens ? "Hold the microphone to speak" : "Type what you want"}</span>
      {/if}
      {#if listens}
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
          data-testid="ask-mic"
          ><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
            ><path d="M12 19v3" /><path d="M19 10v2a7 7 0 0 1-14 0v-2" /><rect x="9" y="2" width="6" height="13" rx="3" /></svg
          ></button
        >
      {/if}
      <button type="submit" class="send" disabled={busy || !words.trim()} data-testid="ask-send">{busy ? "…" : "Ask"}</button>
    </div>
  </form>

  {#each entries as e (e.at)}
    {@const a = e.answer}
    <section class="turn" data-testid="ask-entry">
      {#if e.said}<p class="said">{#if e.spoken}<svg class="heard" aria-label="heard" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"
            ><path d="M12 19v3" /><path d="M19 10v2a7 7 0 0 1-14 0v-2" /><rect x="9" y="2" width="6" height="13" rx="3" /></svg
          >{/if}{e.said}</p>{/if}
      {#if e.error}
        <p class="error">{e.error}</p>
      {:else if !a}
        <p class="hint">Finding which app does it…</p>
      {:else if a.kind === "pick"}
        <p class="pick">{a.app} · {app.askOptions.find((o) => o.app === a.app && o.action === a.action)?.description ?? a.action}</p>
        {#if a.run?.state === "succeeded" && a.run.result}
          <p class="answer {a.run.result.status}" data-testid="ask-answer">{a.run.result.summary}</p>
        {:else if a.run?.state === "failed"}
          <p class="answer failed">{a.run.error ?? "It failed."}</p>
        {:else}
          <p class="answer hint">On it: its agent is working. Its answer comes here, and to your inbox.</p>
        {/if}
      {:else if a.kind === "needs"}
        <p class="answer" data-testid="ask-question">{a.question ?? a.summary}</p>
      {:else}
        <p class="answer">{a.summary}</p>
        {#if app.chats.length}
          <button type="button" class="chat" onclick={() => app.compose(true, e.said)} data-testid="ask-chat">Start a chat about it</button>
        {/if}
      {/if}
    </section>
  {/each}

  {#if app.askOptions.length}
    <section>
      <h2>What you can ask</h2>
      <ul class="card">
        {#each app.askOptions as o (`${o.app}/${o.action}`)}<li><b>{o.app}</b> {o.description}</li>{/each}
      </ul>
    </section>
  {/if}
</main>

<style>
  .top {
    padding: max(0.75rem, env(safe-area-inset-top)) 1rem 0.25rem;
  }
  .top h1 {
    font-size: 1.25rem;
    font-weight: 650;
  }
  .page {
    flex: 1;
    overflow-y: auto;
    padding: 0.75rem 0.75rem max(1rem, env(safe-area-inset-bottom));
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }
  .box {
    border: 1px solid var(--border);
    border-radius: 16px;
    background: var(--card);
    padding: 0.6rem 0.6rem 0.5rem 0.8rem;
  }
  textarea {
    width: 100%;
    font: inherit;
    border: 0;
    background: transparent;
    color: inherit;
    resize: none;
    outline: none;
  }
  .row {
    display: flex;
    align-items: center;
    gap: 0.6rem;
  }
  .hint {
    flex: 1;
    font-size: 0.85em;
    color: var(--muted-foreground);
  }
  .send {
    padding: 0.5rem 1rem;
    border-radius: 999px;
    font-weight: 600;
    background: var(--primary);
    color: var(--primary-foreground);
  }
  .send:disabled {
    opacity: 0.5;
  }
  .mic {
    width: 44px;
    height: 44px;
    border-radius: 999px;
    display: grid;
    place-items: center;
    border: 1px solid var(--border);
    color: var(--muted-foreground);
    touch-action: none;
    user-select: none;
    -webkit-user-select: none;
  }
  .mic svg {
    width: 20px;
    height: 20px;
  }
  .mic.on {
    background: var(--danger);
    border-color: var(--danger);
    color: #fff;
    box-shadow: 0 0 0 10px color-mix(in oklab, var(--danger) 18%, transparent);
  }
  .rec {
    color: var(--danger);
    font-family: ui-monospace, monospace;
  }
  .heard {
    width: 0.85em;
    height: 0.85em;
    margin-right: 0.35rem;
    vertical-align: -0.05em;
    color: var(--muted-foreground);
  }
  .turn {
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
  }
  .said {
    font-weight: 600;
  }
  .pick {
    font-size: 0.85em;
    color: var(--muted-foreground);
  }
  .answer {
    padding: 0.6rem 0.8rem;
    border-radius: 14px;
    background: var(--muted);
    border-left: 3px solid var(--border);
  }
  .answer.ok {
    border-left-color: var(--ok);
  }
  .answer.attention {
    border-left-color: var(--warn);
  }
  .answer.failed {
    border-left-color: var(--danger);
  }
  .chat {
    align-self: flex-start;
    padding: 0.45rem 0.9rem;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--card);
    font-size: 0.9em;
    font-weight: 500;
  }
  .error {
    color: var(--danger);
    font-size: 0.9em;
  }
  h2 {
    font-size: 0.8em;
    font-weight: 600;
    color: var(--muted-foreground);
    margin-bottom: 0.4rem;
  }
  .card {
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--card);
    font-size: 0.9em;
  }
  .card li {
    padding: 0.55rem 0.9rem;
  }
  .card li + li {
    border-top: 1px solid var(--border);
  }
  .card b {
    font-weight: 600;
    margin-right: 0.35rem;
  }
</style>
