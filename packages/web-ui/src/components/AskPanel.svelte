<script lang="ts">
  // Ask (D.24), Chat's Ask tab (ChatView): a box of its own, apart from the chat's. Say what you
  // want, Handler picks which of your apps' actions does it (the router, the agent given for one
  // of Handler's needs: an agent on the model alone), runs it at once, and answers here: the app
  // and action it picked, why, the answer (an agent's, read again until it ends). A question back
  // is answered in the same box (one more turn of the exchange, which the tab keeps and sends
  // whole). Not this: the other actions, the picked one's form as the router filled it. Today's
  // asks stay on the tab (this browser); older ones are on their app and in the Inbox. Below: what
  // you can ask, by app. When no app does it: a chat about it, in Chat's Talk tab (what was said
  // typed in its box). With no router yet, the tab sets one up first. Speaking (D.25): the
  // microphone records until clicked again (Esc drops it), what was heard is sent at once, marked
  // as heard, and the answer read aloud (Settings → Voice); Voice off, the microphone leads there.
  import ArrowUp from "@lucide/svelte/icons/arrow-up";
  import AppWindow from "@lucide/svelte/icons/app-window";
  import MessagesSquare from "@lucide/svelte/icons/messages-square";
  import Mic from "@lucide/svelte/icons/mic";
  import { Button } from "$lib/components/ui/button";
  import { Textarea } from "$lib/components/ui/textarea";
  import ActionTry from "./ActionTry.svelte";
  import Dialog from "./Dialog.svelte";
  import { api } from "../lib/api";
  import type { App, AppAction, AskTurn, AssistantAnswer, HandlerNeed, Voice } from "../lib/contracts.gen";
  import { href } from "../lib/router.svelte";
  import HelperCard from "./HelperCard.svelte";
  import { canRecord, readAloud, record, type Recording } from "../lib/voice";

  type Entry = { said: string; at: string; answer?: AssistantAnswer; error?: string; spoken?: boolean };

  const KEY = "handler.ask.today";
  const today = new Date().toDateString();

  let apps = $state<App[] | null>(null);
  let router = $state<HandlerNeed | null>(null);
  let entries = $state<Entry[]>(load());
  let words = $state("");
  let busy = $state(false);
  let pending = $state<AskTurn[]>([]); // an exchange under way: a question was asked back
  let other = $state<{ app: string; action: AppAction; initial: Record<string, unknown> } | null>(null);
  let otherOpen = $state(false);
  let voice = $state<Voice | null>(null);
  let recording = $state<Recording | null>(null);
  let hearing = $state(false); // the recording is being written down
  let now = $state(Date.now());
  const listens = $derived(Boolean(voice?.model && !voice.problem && canRecord()));

  const TONE: Record<string, string> = { ok: "bg-ok", attention: "bg-warn", failed: "bg-danger" };
  const askable = $derived((apps ?? []).filter((a) => a.current && a.askable && a.actions?.length));

  function load(): Entry[] {
    try {
      const kept = JSON.parse(localStorage.getItem(KEY) ?? "null") as { day: string; entries: Entry[] } | null;
      return kept?.day === today ? kept.entries : [];
    } catch {
      return [];
    }
  }

  function keep(): void {
    localStorage.setItem(KEY, JSON.stringify({ day: today, entries: entries.slice(0, 30) }));
  }

  $effect(() => {
    Promise.all([api.apps(), api.handlerNeeds()]).then(
      ([a, r]) => ((apps = a), (router = r.find((x) => x.name === "ask-router") ?? null)),
      () => (apps = []),
    );
    api.voice().then(
      (v) => (voice = v),
      () => (voice = null),
    );
  });

  $effect(() => {
    if (!recording) return;
    const tick = setInterval(() => (now = Date.now()), 250);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && cancelRecording();
    window.addEventListener("keydown", esc);
    return () => (clearInterval(tick), window.removeEventListener("keydown", esc));
  });

  async function startRecording(): Promise<void> {
    try {
      recording = await record(() => void stopRecording());
      now = Date.now();
    } catch (e) {
      entries = [{ said: "", at: new Date().toISOString(), error: `The microphone: ${(e as Error).message}`, spoken: true }, ...entries];
    }
  }

  function cancelRecording(): void {
    recording?.cancel();
    recording = null;
  }

  async function stopRecording(): Promise<void> {
    const r = recording;
    if (!r) return;
    recording = null;
    hearing = true;
    try {
      const speech = await r.stop();
      const heard = speech ? (await api.transcribe(speech)).text : "";
      if (heard) await send(undefined, heard);
    } catch (e) {
      entries = [{ said: "", at: new Date().toISOString(), error: `Nothing was written down: ${(e as Error).message}`, spoken: true }, ...entries];
    } finally {
      hearing = false;
    }
  }

  /** Reads an answer aloud when Voice says so for how it was asked (an agent's: once it ended). */
  function speak(entry: Entry): void {
    const a = entry.answer;
    if (!a || !voice || !(entry.spoken ? voice.readAloudSpoken : voice.readAloudTyped)) return;
    if (a.kind === "pick" && a.run?.state === "running") return;
    readAloud(a.kind === "pick" ? (a.run?.result?.summary ?? a.run?.error ?? a.summary) : (a.question ?? a.summary));
  }

  async function send(event?: Event, heard?: string): Promise<void> {
    event?.preventDefault();
    const said = (heard ?? words).trim();
    if (!said || busy) return;
    busy = true;
    if (heard === undefined) words = "";
    const turns: AskTurn[] = [...pending, { who: "you", text: said }];
    const entry: Entry = { said, at: new Date().toISOString(), spoken: heard !== undefined };
    entries = [entry, ...entries];
    try {
      const answer = await api.ask(turns, Intl.DateTimeFormat().resolvedOptions().timeZone);
      entries[0] = { ...entry, answer };
      pending = answer.kind === "needs" ? [...turns, { who: "handler", text: answer.question ?? answer.summary }] : [];
      speak(entries[0]);
      if (answer.kind === "pick" && answer.run?.state === "running") void follow(0);
    } catch (e) {
      entries[0] = { ...entry, error: (e as Error).message };
      pending = [];
    } finally {
      busy = false;
      keep();
    }
  }

  /** An agent's action: read again until it ends (its answer is in the Inbox too). */
  async function follow(i: number): Promise<void> {
    let answer = entries[i]?.answer;
    while (answer?.run?.state === "running" && answer.run.runId && answer.app && answer.action) {
      await new Promise((r) => setTimeout(r, 2000));
      const run = await api.actionRun(answer.app, answer.action, answer.run.runId).catch(() => null);
      if (!run) return;
      answer = { ...answer, run };
      const at = entries.findIndex((e) => e.at === entries[i]?.at);
      if (at >= 0) entries[at] = { ...entries[at]!, answer };
      if (at >= 0 && answer.run?.state !== "running") speak(entries[at]!);
    }
    keep();
  }

  function key(event: KeyboardEvent): void {
    if (event.key === "Enter" && !event.shiftKey) void send(event);
  }

  function notThis(answer: AssistantAnswer, app: string, action: AppAction): void {
    other = { app, action, initial: app === answer.app && action.name === answer.action ? (answer.fields ?? {}) : {} };
    otherOpen = true;
  }

  function actionOf(app: string, name: string | null | undefined): AppAction | undefined {
    return apps?.find((a) => a.name === app)?.actions?.find((x) => x.name === name);
  }
</script>

<div class="max-w-3xl space-y-6" data-testid="ask-page">
    {#if apps && !router?.agentId}
      <div data-testid="ask-no-router">
        <HelperCard need="ask-router" onready={(a) => router && (router = { ...router, agentId: a.id })}>
          {#snippet preview()}
            <div class="space-y-2.5">
              <p class="rounded-lg border bg-background px-3 py-2 text-sm text-muted-foreground">Add “dentist Thursday 3pm” to my week</p>
              <p class="flex items-center gap-2 text-xs"><AppWindow class="size-3.5" /><b class="font-medium">{askable[0]?.name ?? "Planner"}</b> can do this <span class="rounded-md border bg-background px-2 py-0.5">Ask {askable[0]?.name ?? "Planner"}</span></p>
            </div>
          {/snippet}
        </HelperCard>
      </div>
    {:else if apps && !askable.length}
      <div class="space-y-3 rounded-xl border border-dashed p-5 text-sm text-muted-foreground" data-testid="ask-nothing">
        <p>None of your apps can be asked anything yet. Install one that can (Planner: your calendar), then say what you want here.</p>
        <Button size="sm" variant="outline" href={href({ view: "apps" })}><AppWindow />Apps</Button>
      </div>
    {:else if apps}
      <form class="rounded-2xl bg-card p-3 pl-4 shadow-panel" onsubmit={send} data-testid="ask-box">
        <Textarea
          bind:value={words}
          onkeydown={key}
          rows={2}
          placeholder={pending.length ? "Your answer…" : "Ask anything your apps do…"}
          aria-label="what you want"
          class="min-h-14 resize-none border-0 bg-transparent p-0 text-base shadow-none focus-visible:ring-0 dark:bg-transparent"
          data-testid="ask-input"
        />
        <div class="mt-1 flex items-center gap-2">
          {#if recording}
            <span class="flex-1 text-xs text-muted-foreground" data-testid="ask-listening"
              ><span class="font-mono text-danger">● {Math.floor((now - recording.started) / 60000)}:{String(Math.floor(((now - recording.started) / 1000) % 60)).padStart(2, "0")}</span>
              Listening · click the microphone to stop and send · Esc cancels</span
            >
          {:else}
            <span class="flex-1 text-xs text-muted-foreground"
              >{hearing ? "Writing down what you said…" : pending.length ? "It asked you something: answer it, or say something else" : "Enter to send · Handler picks the app"}</span
            >
          {/if}
          {#if listens}
            <Button
              type="button"
              size="icon"
              variant={recording ? "destructive" : "outline"}
              class="rounded-full"
              disabled={busy || hearing}
              aria-label={recording ? "stop and send" : "speak"}
              onclick={() => (recording ? stopRecording() : startRecording())}
              data-testid="ask-mic"><Mic /></Button
            >
          {:else}
            <a
              class="flex size-9 items-center justify-center rounded-full text-muted-foreground/60 ring-1 ring-border hover:text-foreground"
              href={href({ view: "settings", section: "voice" })}
              title="Speak instead of typing: Settings → Voice"
              aria-label="set up speaking"
              data-testid="ask-mic-setup"><Mic class="size-4" /></a
            >
          {/if}
          <Button type="submit" size="icon" class="rounded-full" disabled={busy || !words.trim()} aria-label="send" data-testid="ask-send"><ArrowUp /></Button>
        </div>
      </form>
    {/if}

    {#if entries.length}
      <p class="font-mono text-xs text-muted-foreground">today</p>
      <ul class="space-y-6" data-testid="ask-entries">
        {#each entries as e (e.at)}
          {@const a = e.answer}
          <li class="space-y-2" data-testid="ask-entry">
            {#if e.said}<p class="flex items-center gap-1.5 font-medium">{#if e.spoken}<Mic class="size-3.5 shrink-0 text-muted-foreground" aria-label="heard" />{/if}{e.said}</p>{/if}
            {#if e.error}
              <p class="text-sm text-danger">{e.error}</p>
            {:else if !a}
              <p class="fact">Finding which app does it…</p>
            {:else if a.kind === "pick" && a.app}
              <p class="flex flex-wrap items-center gap-2 text-sm text-muted-foreground" data-testid="ask-pick">
                <AppWindow class="size-4 text-primary" /><b class="font-medium text-foreground">{a.app} · {actionOf(a.app, a.action)?.description ?? a.action}</b>
                {#if a.why}<i>· {a.why}</i>{/if}
              </p>
              <div class="flex items-start gap-3 rounded-xl bg-card px-4 py-3 shadow-panel">
                {#if a.run?.state === "succeeded" && a.run.result}
                  <span class="mt-1.5 size-2 shrink-0 rounded-full {TONE[a.run.result.status]}"></span>
                  <p class="flex-1" data-testid="ask-answer">{a.run.result.summary}</p>
                {:else if a.run?.state === "failed"}
                  <p class="flex-1 text-danger">{a.run.error ?? "It failed."}</p>
                {:else}
                  <p class="flex-1 text-muted-foreground">On it: {a.app}'s agent is working. Its answer comes here, and to your Inbox.</p>
                {/if}
                <details class="relative">
                  <summary class="cursor-pointer list-none text-xs text-muted-foreground hover:text-foreground" data-testid="ask-not-this">Not this</summary>
                  <ul class="absolute right-0 z-10 mt-2 w-72 space-y-0.5 rounded-xl bg-popover p-1.5 text-sm shadow-lift">
                    {#each askable as app (app.name)}
                      {#each app.actions ?? [] as action (action.name)}
                        <li>
                          <button type="button" class="w-full cursor-pointer rounded-lg px-2.5 py-1.5 text-left hover:bg-muted" onclick={() => notThis(a, app.name, action)}
                            >{app.name} · {action.description}</button
                          >
                        </li>
                      {/each}
                    {/each}
                  </ul>
                </details>
                <a class="text-xs text-link hover:underline" href={href({ view: "apps", app: a.app })}>{a.app}</a>
              </div>
            {:else if a.kind === "needs"}
              <p class="rounded-xl bg-card px-4 py-3 shadow-panel" data-testid="ask-question">{a.question ?? a.summary}</p>
            {:else}
              <div class="rounded-xl bg-card px-4 py-3 shadow-panel" data-testid="ask-none">
                <p>{a.summary}</p>
                {#if a.actions?.length}<p class="mt-1 text-sm text-muted-foreground">What you can ask is listed below; another app may do it (Apps).</p>{/if}
                <Button variant="outline" size="sm" class="mt-2.5" href={href({ view: "chat", say: e.said })} data-testid="ask-chat"><MessagesSquare />Start a chat about it</Button>
              </div>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}

    {#if askable.length}
      <section class="space-y-2 pt-4">
        <h2 class="flex items-baseline gap-2 font-semibold">What you can ask <span class="text-xs font-normal text-muted-foreground">from your apps</span></h2>
        <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel" data-testid="ask-can">
          {#each askable as app (app.name)}
            <li class="flex gap-4 px-4 py-2.5">
              <a class="flex w-36 shrink-0 items-center gap-2 font-medium text-foreground no-underline" href={href({ view: "apps", app: app.name })}><AppWindow class="size-4 text-primary" />{app.name}</a>
              <span class="text-muted-foreground">{(app.actions ?? []).map((x) => x.description).join(" · ")}</span>
            </li>
          {/each}
        </ul>
      </section>
    {/if}
</div>

<Dialog bind:open={otherOpen} title={other ? `${other.app} · ${other.action.description}` : ""} wide testid="ask-other-dialog">
  {#if other}{#key `${other.app}/${other.action.name}`}<ActionTry app={other.app} action={other.action} initial={other.initial} />{/key}{/if}
</Dialog>
