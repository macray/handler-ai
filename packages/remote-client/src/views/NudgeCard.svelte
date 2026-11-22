<script lang="ts">
  // A nudge in the inbox (H.17): what an app asks the person to do. An action's is its form,
  // drawn here, filled in beforehand by the app or from what the owner says (hold the
  // microphone: it fills the form, never sends), then Send; a page's opens the app at that page.
  // Dismiss, and how often it alerts again (this nudge's name, its next ones too). On a device
  // of someone the app is shared with, only Open and Dismiss: the rest is the owner's.
  import { onMount } from "svelte";
  import { app } from "../lib/app.svelte";
  import { endedWords, fieldsOf, fieldValues, formValues, less, more, SETTING_WORDS, type Schema, type Setting } from "../lib/nudges";
  import type { InboxMessage, RemoteActionRun } from "../lib/remote.gen";
  import { canRecord, record, type Recording } from "../lib/voice";
  import FormFields from "./FormFields.svelte";

  let { message, ago }: { message: InboxMessage; ago: string } = $props();

  const nudge = $derived(message.nudge!);
  const ended = $derived(endedWords(nudge));
  const owner = $derived(app.scope === "all");
  const fields = $derived(fieldsOf(nudge.form as Schema | null | undefined));
  const opens = $derived(nudge.open && message.app ? app.apps.find((a) => a.name === message.app) : undefined);
  const listens = $derived(app.voice.listens && canRecord());

  // the props give the first values only: what the app filled in beforehand
  // svelte-ignore state_referenced_locally
  let values = $state<Record<string, unknown>>(formValues(fieldsOf(message.nudge?.form as Schema | null | undefined), message.nudge?.fields));
  let run = $state<RemoteActionRun | null>(null);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let heard = $state<{ said: string; question?: string | null } | null>(null);
  let recording = $state<Recording | null>(null);
  let hearing = $state(false);
  let now = $state(Date.now());
  const setting = $derived<Setting>(nudge.setting ?? "default");
  let settingBusy = $state(false);

  $effect(() => {
    if (!recording) return;
    const tick = setInterval(() => (now = Date.now()), 250);
    return () => clearInterval(tick);
  });

  // its agent works on what was sent before this list was shown: read again until it ends
  onMount(() => {
    if (message.nudge?.state === "open" && message.nudge.runId) void follow(message.nudge.runId);
  });

  async function follow(runId: string): Promise<void> {
    if (!message.app || !nudge.action) return;
    for (;;) {
      await new Promise((r) => setTimeout(r, 3000));
      const again = await app.actionRun(message.app, nudge.action, runId).catch(() => null);
      if (!again) return;
      if (again.state !== "running") {
        run = again;
        await app.refreshInbox().catch(() => undefined);
        return;
      }
      run = again;
    }
  }

  async function send(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (!message.app || !nudge.action || busy) return;
    error = null;
    let filled: Record<string, unknown>;
    try {
      filled = fieldValues(fields, values);
    } catch (e) {
      error = (e as Error).message;
      return;
    }
    busy = true;
    run = null;
    try {
      run = await app.act({ app: message.app, action: nudge.action, fields: filled, nudge: message.id });
      if (run.state === "running" && run.runId) void follow(run.runId);
      else await app.refreshInbox();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  async function hold(event: PointerEvent): Promise<void> {
    event.preventDefault();
    if (recording || busy || hearing) return;
    try {
      recording = await record(() => void release());
      now = Date.now();
    } catch (e) {
      error = `The microphone: ${(e as Error).message}`;
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
    error = null;
    try {
      const speech = await r.stop();
      const said = speech ? await app.transcribe(speech) : "";
      if (!said) return;
      const fill = await app.nudgeFill(message.id, said);
      if (fill.fields) values = { ...values, ...formValues(fields, fill.fields) };
      heard = { said: fill.said, question: fill.question };
    } catch (e) {
      error = `Nothing was filled in: ${(e as Error).message}`;
    } finally {
      hearing = false;
    }
  }

  async function dismiss(): Promise<void> {
    error = null;
    try {
      await app.nudgeDismiss(message.id);
    } catch (e) {
      error = (e as Error).message;
    }
  }

  async function remind(to: Setting | null): Promise<void> {
    if (!to || !message.app || settingBusy) return;
    settingBusy = true;
    error = null;
    try {
      await app.nudgeSetting({ app: message.app, nudge: nudge.name, setting: to });
    } catch (e) {
      error = (e as Error).message;
    } finally {
      settingBusy = false;
    }
  }

  function until(at: string): string {
    const d = new Date(at);
    return d.toDateString() === new Date().toDateString()
      ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
      : d.toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" });
  }
</script>

<li class="nudge" class:ended data-testid="nudge">
  <div class="head">
    <span class="from">{message.name}</span>
    {#if !ended && nudge.until}<span class="meta">until {until(nudge.until)}</span>{/if}
    <time datetime={message.at}>{ago}</time>
  </div>
  <span class="title">{message.title}</span>
  {#if message.summary}<p class="body">{message.summary}</p>{/if}

  {#if ended}
    <p class="state" data-testid="nudge-state">{ended}</p>
  {:else}
    {#if nudge.action && owner}
      <form class="form" onsubmit={send} data-testid="nudge-form">
        <FormFields {fields} bind:values testid="nudge-field" />
        {#if heard}
          <p class="heard" data-testid="nudge-heard">You said: “{heard.said}”{#if heard.question}<br /><b>{heard.question}</b>{/if}</p>
        {/if}
        <div class="row">
          {#if recording}
            <span class="hint rec">● {Math.floor((now - recording.started) / 1000)}s · release to fill it in · slide away to cancel</span>
          {:else}
            <span class="hint">{hearing ? "Filling it in from what you said…" : listens ? "Hold the microphone to say it" : ""}</span>
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
              data-testid="nudge-mic"
              ><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
                ><path d="M12 19v3" /><path d="M19 10v2a7 7 0 0 1-14 0v-2" /><rect x="9" y="2" width="6" height="13" rx="3" /></svg
              ></button
            >
          {/if}
          <button type="submit" class="send" disabled={busy || hearing || run?.state === "running"} data-testid="nudge-send">{busy ? "…" : "Send"}</button>
        </div>
      </form>
    {:else if nudge.open}
      {#if opens}
        <button type="button" class="link" onclick={() => app.openApp(opens, nudge.open ?? "/")} data-testid="nudge-open">Open ›</button>
      {:else}
        <p class="hint">{message.app} is not shared with this phone: open it on your computer.</p>
      {/if}
    {/if}

    <div class="actions">
      <button type="button" class="chip" onclick={dismiss} data-testid="nudge-dismiss">Dismiss</button>
      {#if owner && message.app}
        <button type="button" class="chip" disabled={settingBusy || !less(setting)} onclick={() => remind(less(setting))} data-testid="nudge-less">Remind me less</button>
        <button type="button" class="chip" disabled={settingBusy || !more(setting)} onclick={() => remind(more(setting))} data-testid="nudge-more">Remind me more</button>
      {/if}
    </div>
    {#if owner && message.app}<p class="hint" data-testid="nudge-setting">Reminders: {SETTING_WORDS[setting]}</p>{/if}
  {/if}
    {#if !ended && (run?.state === "running" || (!run && nudge.runId))}
      <p class="answer hint" data-testid="nudge-running">On it: its job is running. Its answer comes here.</p>
    {:else if run?.state === "succeeded" && run.result}
      <p class="answer {run.result.status}" data-testid="nudge-answer">{run.result.summary}</p>
    {:else if run?.state === "failed"}
      <p class="answer failed" data-testid="nudge-failed">{run.error ?? "It failed."}</p>
    {/if}

  {#if error}<p class="error">{error}</p>{/if}
</li>

<style>
  .nudge {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    padding: 0.75rem 0.9rem;
  }
  .head {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }
  /* the app (or whoever) it comes from, a small mono chip */
  .from {
    min-width: 0;
    padding: 0.1rem 0.5rem;
    border-radius: 6px;
    background: color-mix(in srgb, var(--warn) 12%, transparent);
    color: var(--warn);
    font: 500 0.78em var(--mono);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .ended .from {
    background: var(--muted);
    color: var(--muted-foreground);
  }
  .head time {
    margin-left: auto;
  }
  .title {
    font: 500 0.98em/1.35 var(--mono);
    letter-spacing: -0.01em;
  }
  .ended .title {
    color: var(--muted-foreground);
  }
  .meta,
  .hint {
    color: var(--muted-foreground);
    font-size: 0.85em;
  }
  time {
    flex: none;
    font: 0.78em var(--mono);
    color: var(--muted-foreground);
  }
  .body {
    white-space: pre-wrap;
  }
  .state {
    font-size: 0.85em;
    color: var(--muted-foreground);
  }
  .form {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  .row {
    display: flex;
    align-items: center;
    gap: 0.6rem;
  }
  .row .hint {
    flex: 1;
  }
  .send {
    padding: 0.5rem 1.4rem;
    border-radius: 10px;
    font-weight: 600;
    background: var(--primary);
    color: var(--primary-foreground);
    min-height: 44px;
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
    font-size: 0.85em;
    padding: 0.5rem 0.7rem;
    border-radius: 10px;
    background: var(--muted);
  }
  /* its answer: a soft tint in its colour, no stripe */
  .answer {
    padding: 0.6rem 0.8rem;
    border-radius: 12px;
    background: var(--muted);
  }
  .answer.ok {
    background: color-mix(in srgb, var(--ok) 10%, var(--card));
  }
  .answer.attention {
    background: color-mix(in srgb, var(--warn) 12%, var(--card));
  }
  .answer.failed {
    background: color-mix(in srgb, var(--danger) 10%, var(--card));
  }
  .link {
    align-self: flex-start;
    font-weight: 500;
    color: var(--link);
    padding: 0.5rem 0;
    min-height: 40px;
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
  }
  .chip {
    padding: 0.4rem 0.8rem;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--card);
    font-size: 0.85em;
    font-weight: 500;
    min-height: 36px;
  }
  .chip:disabled {
    opacity: 0.45;
  }
  .error {
    color: var(--danger);
    font-size: 0.85em;
  }
</style>
