<script lang="ts">
  // The person's inbox: what handler told you, newest first, by day. Apps' notifications (H.9) and
  // automations' results and failures (I.3), the results of runs your apps started (H.11), plans
  // stopped (D.27), the hosts Handler's network filter refused to a run or to a session while you
  // were away (F.9: *Allow*, and run again for a run, or *Keep blocked*); an agent's result opens
  // as its run, shown from its schema, and a message tied to an app opens it too. Like mail:
  // unread is bold with a dot, opening a message reads it. Apps' nudges (H.17), what an app asks
  // you to do, come first while open, under *To do* (NudgeCard: its form or its page, Dismiss,
  // how often it reminds you); ended, they say so in a word among the others.
  import AppWindow from "@lucide/svelte/icons/app-window";
  import Bot from "@lucide/svelte/icons/bot";
  import Check from "@lucide/svelte/icons/check";
  import CheckCheck from "@lucide/svelte/icons/check-check";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import ExternalLink from "@lucide/svelte/icons/external-link";
  import CircleX from "@lucide/svelte/icons/circle-x";
  import InboxIcon from "@lucide/svelte/icons/inbox";
  import ListTodo from "@lucide/svelte/icons/list-todo";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import Workflow from "@lucide/svelte/icons/workflow";
  import { Button } from "$lib/components/ui/button";
  import LoadingCards from "../components/LoadingCards.svelte";
  import NudgeCard from "../components/NudgeCard.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import RefusedHosts from "../components/RefusedHosts.svelte";
  import When from "../components/When.svelte";
  import { onChange } from "../lib/events.svelte";
  import { api } from "../lib/api";
  import type { ActionRun, InboxMessage, Voice } from "../lib/contracts.gen";
  import { inbox } from "../lib/inbox.svelte";
  import { href } from "../lib/router.svelte";
  import { menuUse } from "../lib/menuuse.svelte";
  import { dayOf } from "../lib/agents";
  import { endedWords, isOpen, type NudgeSetting } from "../lib/nudges";
  import { canRecord } from "../lib/voice";

  let messages = $state<InboxMessage[] | null>(null);
  let error = $state<string | null>(null);
  let busy = $state(false);

  const unread = $derived((messages ?? []).filter((m) => !m.read));
  const todo = $derived((messages ?? []).filter(isOpen));
  // Voice, for the microphone on a nudge's form; what an action sent from here answered, by message
  let voice = $state<Voice | null>(null);
  let answers = $state<Record<string, ActionRun>>({});
  const listens = $derived(Boolean(voice?.model && !voice.problem && canRecord()));

  $effect(() => {
    if (!todo.length || voice) return;
    api.voice().then(
      (v) => (voice = v),
      () => {},
    );
  });

  /** How often that nudge of its app reminds you, held for its next ones (H.17). */
  async function setSetting(m: InboxMessage, to: NudgeSetting): Promise<void> {
    if (!m.app || !m.nudge) return;
    await api.setNudgeSetting(m.app, m.nudge.name, to);
    await load();
  }

  async function load(): Promise<void> {
    try {
      messages = await api.inbox();
      inbox.count(messages);
      error = null;
    } catch (e) {
      error = (e as Error).message;
    }
  }

  $effect(() => {
    const stop = onChange(["inbox"], () => void load());
    void load();
    return stop;
  });

  async function markRead(list: InboxMessage[]): Promise<void> {
    busy = true;
    try {
      await Promise.all(list.map((m) => api.markRead(m.id)));
      await load();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  /** Opening a message reads it, as in mail (the page it leads to loads meanwhile). */
  function opened(m: InboxMessage): void {
    if (!m.read) api.markRead(m.id).then(() => inbox.refresh(), () => {});
  }

  /** The app a message is tied to, opened in a new tab (a one-time link, H.4). */
  async function openApp(m: InboxMessage): Promise<void> {
    opened(m);
    const tab = window.open("about:blank", "_blank"); // now, while the click counts (popup blockers)
    try {
      const link = await api.openApp(m.app!);
      if (tab) {
        tab.opener = null;
        tab.location.href = link.url;
      }
    } catch (e) {
      tab?.close();
      error = (e as Error).message;
    }
  }

  /** Its hosts refused allowed (its plan or automation run again) or kept blocked (F.9). */
  async function answer(m: InboxMessage, hosts: string[], decision: "allowed" | "kept blocked"): Promise<void> {
    busy = true;
    try {
      await api.answerInbox(m.id, { decision, hosts: hosts as [string, ...string[]], again: decision === "allowed" && m.source !== "session" });
      await load();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  /** What *Allow* does beside allowing: a run's runs again; a session's agent is told. */
  function again(m: InboxMessage): { agent?: string | null; step?: number | null } | null {
    if (m.source === "session") return null;
    return { agent: m.agent, step: m.source === "plan" ? m.step : null };
  }

  /** Where a message leads: a plan, a session, an agent's run, the automation, Ask, the apps. */
  function link(m: InboxMessage): { label: string; url: string } {
    if (m.source === "plan" && m.planId) return { label: "Open the plan", url: href({ view: "plan", id: m.planId }) };
    if (m.source === "session" && m.sessionId) return { label: "Open the session", url: href({ view: "session", key: m.sessionId }) };
    if (m.sessionId) return { label: "See the result", url: href({ view: "run", id: m.sessionId }) };
    if (m.source === "automation") return { label: "Open the automation", url: href({ view: "automation", name: m.name }) };
    if (m.source === "ask") return { label: "Open Ask's history", url: href({ view: "ask" }) };
    if (m.source === "notes") return { label: "Open the folder", url: href(m.name === "." ? { view: "knowledge" } : { view: "knowledge", path: m.name }) };
    return { label: "Open Apps", url: href({ view: "apps" }) };
  }

  /** Who told you: the app, or the automation and its agent. */
  function from(m: InboxMessage): string {
    const who =
      m.source === "app"
        ? m.agent
          ? `app ${menuUse.title(m.name)} · agent ${m.agent}`
          : `app ${menuUse.title(m.name)}`
        : m.source === "plan"
          ? `plan ${m.name}${m.agent ? ` · agent ${m.agent}` : ""}`
          : m.source === "notes"
            ? `notes ${m.name}`
            : m.source === "ask"
            ? m.app ? `Ask · app ${menuUse.title(m.app)}` : "Ask"
            : m.agent
            ? `${m.name} · agent ${m.agent}`
            : `automation ${m.name}`;
    return m.person === "owner" ? who : `${who} · for ${m.person}`;
  }

  /** The icon tile: a failure or a result to look at says so, else where it comes from. */
  function tile(m: InboxMessage): { icon: typeof Bot; tone: string } {
    if (isOpen(m)) return { icon: ListTodo, tone: "bg-primary/10 text-primary" };
    if (m.status === "failed") return { icon: CircleX, tone: "bg-danger/10 text-danger" };
    if (m.status === "attention") return { icon: TriangleAlert, tone: "bg-warn/10 text-warn" };
    if (m.source === "app") return { icon: AppWindow, tone: "bg-muted text-muted-foreground" };
    return { icon: m.agent ? Bot : Workflow, tone: "bg-muted text-muted-foreground" };
  }

  const STATUS: Record<string, { label: string; tone: string }> = {
    failed: { label: "failed", tone: "bg-danger/10 text-danger" },
    attention: { label: "needs a look", tone: "bg-warn/10 text-warn" },
  };

  const days = $derived.by(() => {
    const groups: { day: string; messages: InboxMessage[] }[] = [];
    for (const m of (messages ?? []).filter((x) => !isOpen(x))) {
      const d = dayOf(m.at);
      if (groups.at(-1)?.day === d) groups.at(-1)!.messages.push(m);
      else groups.push({ day: d, messages: [m] });
    }
    return groups;
  });
</script>

{#snippet markReadButton(m: InboxMessage)}
  {#if !m.read}
    <Button size="sm" variant="secondary" disabled={busy} onclick={() => markRead([m])} data-testid="inbox-read"><Check />Mark read</Button>
  {/if}
{/snippet}

{#snippet row(m: InboxMessage)}
  {@const to = link(m)}
  {@const t = tile(m)}
  {@const ended = m.nudge && !isOpen(m) ? endedWords(m.nudge) : null}
  <li class="group enter relative flex gap-4 px-4 py-3.5 transition-colors hover:bg-muted/40" data-testid={m.kind === "nudge" ? "inbox-nudge" : "inbox-message"}>
    <span class="relative hidden size-9 shrink-0 items-center justify-center rounded-lg sm:flex {t.tone}">
      <t.icon class="size-4" />
    </span>
    <div class="min-w-0 flex-1 space-y-1">
      <div class="flex items-baseline gap-3">
        <p class="flex min-w-0 items-center gap-2 {m.read ? 'text-foreground/80' : 'font-semibold'}">
          {#if !m.read}<span class="size-2 shrink-0 rounded-full bg-primary" aria-label="unread"></span>{/if}
          <span class="truncate">{m.title}</span>
          {#if m.status && STATUS[m.status]}
            {@const st = STATUS[m.status]!}
            <span class="shrink-0 rounded-md px-1.5 py-0.5 text-xs font-normal {st.tone}" data-testid="inbox-status">{st.label}</span>
          {/if}
          {#if ended}
            <span class="shrink-0 rounded-md bg-muted px-1.5 py-0.5 text-xs font-normal text-muted-foreground" data-testid="nudge-state">{ended}</span>
          {/if}
        </p>
        <span class="fact ml-auto shrink-0"><When at={m.at} /></span>
      </div>
      <p class="fact truncate">{from(m)}</p>
      {#if m.summary}<p class="line-clamp-4 pt-0.5 whitespace-pre-wrap text-muted-foreground" title={m.summary}>{m.summary}</p>{/if}
      {#if m.refused?.length}
        <div class="pt-1.5">
          <RefusedHosts
            hosts={m.refused}
            said={m.said}
            completed={m.source !== "session" && m.status !== "failed"}
            {busy}
            again={again(m)}
            onallow={(hosts) => answer(m, hosts, "allowed")}
            onkeep={(hosts) => answer(m, hosts, "kept blocked")}
          />
        </div>
      {/if}
      {#if m.nudge}
        <NudgeCard
          {m}
          nudge={m.nudge}
          setting={m.nudge.setting ?? "default"}
          {listens}
          answer={answers[m.id]}
          onran={(run) => (answers[m.id] = run)}
          onchanged={() => void load()}
          onsetting={(to) => setSetting(m, to)}
        >
          {#snippet more()}{@render markReadButton(m)}{/snippet}
        </NudgeCard>
      {/if}
      {#if !isOpen(m)}
        <div class="flex flex-wrap items-center gap-2 pt-2">
          {#if m.app}
            <Button size="sm" onclick={() => openApp(m)} data-testid="inbox-open-app"><ExternalLink />Open {menuUse.title(m.app)}</Button>
          {/if}
          {#if !m.app || m.sessionId || m.source === "ask"}
            <Button variant="outline" size="sm" href={to.url} onclick={() => opened(m)} data-testid="inbox-open">{to.label}<ChevronRight data-icon="inline-end" /></Button>
          {/if}
          {@render markReadButton(m)}
        </div>
      {/if}
    </div>
  </li>
{/snippet}

<PageHeader width="max-w-4xl" title="Inbox">
  {#snippet actions()}
    {#if unread.length}
      <Button variant="outline" size="sm" disabled={busy} onclick={() => markRead(unread)} data-testid="inbox-read-all"><CheckCheck />Mark all read</Button>
    {/if}
  {/snippet}
</PageHeader>
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-4xl space-y-8 px-8 py-10">
        {#if error}<p class="text-sm text-danger" data-testid="inbox-error">{error}</p>{/if}

    <div class="space-y-8" data-testid="inbox">
      {#if !messages}
        <div class="space-y-3"><LoadingCards count={3} height="h-16" /></div>
      {:else}
        {#if messages.length}
          <p class="fact" data-testid="inbox-count">
            {unread.length ? `${unread.length} unread` : "all read"} · {messages.length} message{messages.length === 1 ? "" : "s"}
          </p>
        {/if}
        {#if todo.length}
          <section class="space-y-2.5" data-testid="inbox-todo">
            <h2 class="section-label px-1">to do</h2>
            <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
              {#each todo as m (m.id)}{@render row(m)}{/each}
            </ul>
          </section>
        {/if}
        {#each days as group (group.day)}
          <section class="space-y-2.5">
            <h2 class="section-label px-1">{group.day}</h2>
            <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
              {#each group.messages as m (m.id)}{@render row(m)}{/each}
            </ul>
          </section>
        {/each}
        {#if !messages.length}
          <div class="flex flex-col items-center gap-3 rounded-[10px] border border-dashed px-6 py-12 text-center" data-testid="inbox-empty">
            <span class="flex size-10 items-center justify-center rounded-lg bg-muted text-muted-foreground"><InboxIcon class="size-5" /></span>
            <p class="font-medium">Nothing here yet</p>
            <p class="max-w-md text-sm text-muted-foreground">
              When an app notifies you or asks you to do something, an automation's agent finishes, a run or a plan fails, or the network filter blocks a host while you are away, it comes here, to your desktop and to your phone.
            </p>
            <Button variant="outline" size="sm" href={href({ view: "library", shelf: "automations" })}><Workflow />See your automations</Button>
          </div>
        {/if}
      {/if}
    </div>
  </div>
</div>
