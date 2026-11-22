<script lang="ts">
  // What an inbox message that is a nudge (H.17) shows under its title and text. Open: the form
  // of the action it points at (drawn from its schema, filled with what the app drafted), a
  // microphone whose words fill the form (never sent: the person presses Send), Send (the action,
  // with the nudge's id: its success marks it done); or Open, for a page of the app (a one-time
  // link). Then Dismiss, how often it reminds you, and when it comes (one Handler sends at a time). Ended: what the action answered, when it was
  // sent from here; expired: what the app said happens then.
  import type { Snippet } from "svelte";
  import ExternalLink from "@lucide/svelte/icons/external-link";
  import Send from "@lucide/svelte/icons/send";
  import X from "@lucide/svelte/icons/x";
  import BellOff from "@lucide/svelte/icons/bell-off";
  import Ellipsis from "@lucide/svelte/icons/ellipsis";
  import Popover from "./Popover.svelte";
  import { Button } from "$lib/components/ui/button";
  import { api } from "../lib/api";
  import type { ActionRun, InboxMessage, InboxNudge } from "../lib/contracts.gen";
  import type { NudgeSetting } from "../lib/nudges";
  import { fieldsOf, formValues, type Schema } from "../lib/runs";
  import { clock, type Recording } from "../lib/voice";
  import ActionAnswer from "./ActionAnswer.svelte";
  import ActionForm from "./ActionForm.svelte";
  import MicButton from "./MicButton.svelte";
  import NudgeReminders from "./NudgeReminders.svelte";
  import NudgeWhen from "./NudgeWhen.svelte";

  let {
    m,
    nudge,
    setting,
    listens,
    answer,
    onran,
    onchanged,
    onsetting,
    more,
  }: {
    m: InboxMessage;
    nudge: InboxNudge;
    setting: NudgeSetting;
    listens: boolean;
    answer: ActionRun | undefined; // what it answered, sent from this page
    onran: (run: ActionRun) => void;
    onchanged: () => void;
    onsetting: (to: NudgeSetting) => Promise<void>;
    more?: Snippet; // the inbox's own buttons (Mark read), beside Dismiss
  } = $props();

  const open = $derived((nudge.state ?? "open") === "open");
  const schema = $derived(nudge.form as Schema | null | undefined);
  // the props give the initial values only: what the app drafted (H.17)
  // svelte-ignore state_referenced_locally
  let values = $state<Record<string, unknown>>(formValues(fieldsOf(nudge.form as Schema | null | undefined), nudge.fields ?? {}));
  let recording = $state<Recording | null>(null);
  let hearing = $state(false);
  let filling = $state(false);
  let heard = $state<{ said: string; question?: string | null } | null>(null);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let now = $state(Date.now());

  $effect(() => {
    if (!recording) return;
    now = Date.now();
    const tick = setInterval(() => (now = Date.now()), 250);
    return () => clearInterval(tick);
  });

  /** What was said fills the form, never sends it (rule nudge.voice-fills-never-sends). */
  async function fill(said: string): Promise<void> {
    filling = true;
    error = null;
    try {
      const got = await api.fillNudge(m.id, said, Intl.DateTimeFormat().resolvedOptions().timeZone);
      if (got.fields) values = { ...values, ...formValues(fieldsOf(schema), got.fields) };
      heard = { said: got.said, question: got.question };
    } catch (e) {
      error = (e as Error).message;
    } finally {
      filling = false;
    }
  }

  let stopping = $state(false); // "Stop these nudges" asked: its confirm replaces the footer
  let menuOpen = $state(false);

  /** Its name's nudges turned off (none comes; this one stays, reminding no more), or on. */
  function setOff(off: boolean): Promise<void> {
    const app = m.app;
    if (!app) return Promise.resolve();
    return doing(async () => (await api.setNudgeOff(app, nudge.name, off), (stopping = false), onchanged()));
  }

  async function doing(what: () => Promise<unknown>): Promise<void> {
    busy = true;
    error = null;
    try {
      await what();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  /** The page of the app it opens, in a new tab (a one-time link). */
  async function openPage(): Promise<void> {
    const tab = window.open("about:blank", "_blank"); // now, while the click counts (popup blockers)
    try {
      const link = await api.openNudge(m.id);
      if (tab) {
        tab.opener = null;
        tab.location.href = link.url;
      }
    } catch (e) {
      tab?.close();
      error = (e as Error).message;
    }
  }

  function ran(run: ActionRun): void {
    onran(run);
    onchanged();
  }
</script>

<div class="space-y-3 pt-2" data-testid="nudge">
  {#if open}
    {#if nudge.action && m.app}
      <div class="rounded-lg border bg-background p-3.5">
        {#if recording}
          <p class="mb-3 text-xs text-muted-foreground" data-testid="nudge-listening">
            <span class="font-mono text-danger">● {clock(now - recording.started)}</span> Listening · click the microphone to stop · Esc cancels
          </p>
        {:else if hearing || filling}
          <p class="mb-3 fact">{hearing ? "Writing down what you said…" : "Filling the form with it…"}</p>
        {:else if heard}
          <div class="mb-3 space-y-1 text-xs" data-testid="nudge-heard">
            <p class="text-muted-foreground">You said: “{heard.said}”. Check the form, then Send.</p>
            {#if heard.question}<p class="text-foreground" data-testid="nudge-question">{heard.question}</p>{/if}
          </div>
        {/if}
        {#if nudge.runId}<p class="mb-3 fact" data-testid="nudge-running">Its job is working on what you sent.</p>{/if}
        <ActionForm
          app={m.app}
          action={nudge.action}
          {schema}
          bind:values
          nudge={m.id}
          label="Send"
          again="Send again"
          icon={Send}
          onran={ran}
          testid="nudge-form"
          submitTestid="nudge-send"
        >
          {#snippet extra()}
            <MicButton {listens} disabled={filling} bind:recording bind:hearing stopLabel="stop and fill the form" onheard={fill} onerror={(e) => (error = e)} testid="nudge-mic" />
          {/snippet}
        </ActionForm>
      </div>
    {/if}
    {#if stopping}
      <div class="flex flex-wrap items-center gap-2 rounded-md bg-muted/50 px-3 py-2 text-sm" data-testid="nudge-stop-confirm">
        <span class="min-w-0 flex-1">Stop “{m.title}”? No more will come. This one stays until you send or dismiss it.</span>
        <Button size="sm" variant="destructive" disabled={busy} onclick={() => setOff(true)} data-testid="nudge-stop-yes">Stop them</Button>
        <Button size="sm" variant="ghost" onclick={() => (stopping = false)}>Cancel</Button>
      </div>
    {:else}
      <div class="flex flex-wrap items-center gap-2">
        {#if nudge.open}
          <Button size="sm" onclick={openPage} data-testid="nudge-open"><ExternalLink />Open</Button>
        {/if}
        <Button size="sm" variant="outline" disabled={busy} onclick={() => doing(async () => (await api.dismissNudge(m.id), onchanged()))} data-testid="nudge-dismiss"><X />Dismiss</Button>
        {@render more?.()}
        {#if !nudge.off}
          <div class="ml-auto flex items-center gap-1">
            <NudgeReminders {setting} remind={nudge.remind} disabled={busy} onchange={(to) => doing(() => onsetting(to))} />
            {#if m.app}
              <Popover bind:open={menuOpen} align="end" label="More" width="15rem" testid="nudge-menu">
                {#snippet trigger(props)}
                  <Button size="icon" variant="ghost" class="size-7 text-muted-foreground" {...props} aria-label="More" data-testid="nudge-more"><Ellipsis /></Button>
                {/snippet}
                {#snippet children(close)}
                  <button type="button" class="menu-item text-danger" onclick={() => (close(), (stopping = true))} data-testid="nudge-stop"
                    ><BellOff /><span class="text-left"><span class="block">Stop these nudges</span><span class="block text-xs text-muted-foreground">none come after this one</span></span></button
                  >
                {/snippet}
              </Popover>
            {/if}
          </div>
        {/if}
      </div>
      {#if nudge.off}
        <p class="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground" data-testid="nudge-stopped">
          <BellOff class="size-3.5" />Stopped: no more will come, and this one won't remind you.
          <button type="button" class="text-link hover:underline" disabled={busy} onclick={() => setOff(false)} data-testid="nudge-turn-on">Turn back on</button>
        </p>
      {/if}
    {/if}
    {#if nudge.when && m.app}
      {@const app = m.app}
      <NudgeWhen when={nudge.when} ownWhen={nudge.ownWhen} disabled={busy} onchange={(to) => doing(async () => (await api.setNudgeWhen(app, nudge.name, to), onchanged()))} />
    {/if}
  {:else}
    {#if answer}<ActionAnswer run={answer} />{/if}
    {#if nudge.state === "expired" && nudge.ifIgnored}
      <p class="text-sm text-muted-foreground" data-testid="nudge-if-ignored">Not done in time: {nudge.ifIgnored}</p>
    {/if}
  {/if}
  {#if error}<p class="text-sm text-danger" data-testid="nudge-error">{error}</p>{/if}
</div>
