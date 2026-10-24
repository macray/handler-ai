<script lang="ts">
  // The person's inbox: what handler told you, newest first, by day. Apps' notifications (H.9) and
  // automations' results and failures (I.3), the results of runs your apps started (H.11); an
  // agent's result opens as its run, shown from its schema, and a message tied to an app opens it
  // too. Like mail: unread is bold with a dot, opening a message reads it.
  import AppWindow from "@lucide/svelte/icons/app-window";
  import Bot from "@lucide/svelte/icons/bot";
  import Check from "@lucide/svelte/icons/check";
  import CheckCheck from "@lucide/svelte/icons/check-check";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import ExternalLink from "@lucide/svelte/icons/external-link";
  import CircleX from "@lucide/svelte/icons/circle-x";
  import InboxIcon from "@lucide/svelte/icons/inbox";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import Workflow from "@lucide/svelte/icons/workflow";
  import { Button } from "$lib/components/ui/button";
  import LoadingCards from "../components/LoadingCards.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import PageTitle from "../components/PageTitle.svelte";
  import When from "../components/When.svelte";
  import { api } from "../lib/api";
  import type { InboxMessage } from "../lib/contracts.gen";
  import { inbox } from "../lib/inbox.svelte";
  import { href } from "../lib/router.svelte";

  let messages = $state<InboxMessage[] | null>(null);
  let error = $state<string | null>(null);
  let busy = $state(false);

  const unread = $derived((messages ?? []).filter((m) => !m.read));

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
    void load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
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

  /** Where a message leads: an agent's run, the automation, the apps. */
  function link(m: InboxMessage): { label: string; url: string } {
    if (m.sessionId) return { label: "See the result", url: href({ view: "run", id: m.sessionId }) };
    if (m.source === "automation") return { label: "Open the automation", url: href({ view: "automation", name: m.name }) };
    return { label: "Open Apps", url: href({ view: "apps" }) };
  }

  /** Who told you: the app, or the automation and its agent. */
  function from(m: InboxMessage): string {
    const who =
      m.source === "app" ? (m.agent ? `app ${m.name} · agent ${m.agent}` : `app ${m.name}`) : m.agent ? `${m.name} · agent ${m.agent}` : `automation ${m.name}`;
    return m.person === "owner" ? who : `${who} · for ${m.person}`;
  }

  /** The icon tile: a failure or a result to look at says so, else where it comes from. */
  function tile(m: InboxMessage): { icon: typeof Bot; tone: string } {
    if (m.status === "failed") return { icon: CircleX, tone: "bg-danger/10 text-danger" };
    if (m.status === "attention") return { icon: TriangleAlert, tone: "bg-warn/10 text-warn" };
    if (m.source === "app") return { icon: AppWindow, tone: "bg-muted text-muted-foreground" };
    return { icon: m.agent ? Bot : Workflow, tone: "bg-muted text-muted-foreground" };
  }

  const STATUS: Record<string, { label: string; tone: string }> = {
    failed: { label: "failed", tone: "bg-danger/10 text-danger" },
    attention: { label: "needs a look", tone: "bg-warn/10 text-warn" },
  };

  /** The day a message is filed under: today, yesterday, a weekday this week, else its date. */
  function day(at: string): string {
    const d = new Date(at);
    const start = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
    const days = Math.round((start(new Date()) - start(d)) / 86_400_000);
    if (days <= 0) return "Today";
    if (days === 1) return "Yesterday";
    if (days < 7) return d.toLocaleDateString(undefined, { weekday: "long" });
    const year = d.getFullYear() === new Date().getFullYear() ? undefined : "numeric";
    return d.toLocaleDateString(undefined, { day: "numeric", month: "long", year });
  }

  const days = $derived.by(() => {
    const groups: { day: string; messages: InboxMessage[] }[] = [];
    for (const m of messages ?? []) {
      const d = day(m.at);
      if (groups.at(-1)?.day === d) groups.at(-1)!.messages.push(m);
      else groups.push({ day: d, messages: [m] });
    }
    return groups;
  });
</script>

<PageHeader titled title="Inbox">
  {#snippet actions()}
    {#if unread.length}
      <Button variant="outline" size="sm" disabled={busy} onclick={() => markRead(unread)} data-testid="inbox-read-all"><CheckCheck />Mark all read</Button>
    {/if}
  {/snippet}
</PageHeader>
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-4xl space-y-8 px-8 py-10">
    <PageTitle
      title="Inbox"
      description="What Handler tells you: your apps' notifications, your agents' results (run by an automation or by one of your apps) and the runs that failed. Your agents cannot write here."
    />
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
        {#each days as group (group.day)}
          <section class="space-y-2.5">
            <h2 class="section-label px-1">{group.day}</h2>
            <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
              {#each group.messages as m (m.id)}
                {@const to = link(m)}
                {@const t = tile(m)}
                <li class="group enter relative flex gap-4 px-4 py-3.5 transition-colors hover:bg-muted/40" data-testid="inbox-message">
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
                      </p>
                      <span class="fact ml-auto shrink-0"><When at={m.at} /></span>
                    </div>
                    <p class="fact truncate">{from(m)}</p>
                    {#if m.summary}<p class="line-clamp-4 pt-0.5 whitespace-pre-wrap text-muted-foreground" title={m.summary}>{m.summary}</p>{/if}
                    <div class="flex flex-wrap items-center gap-2 pt-2">
                      {#if m.app}
                        <Button size="sm" onclick={() => openApp(m)} data-testid="inbox-open-app"><ExternalLink />Open {m.app}</Button>
                      {/if}
                      {#if !m.app || m.sessionId}
                        <Button variant="outline" size="sm" href={to.url} onclick={() => opened(m)} data-testid="inbox-open">{to.label}<ChevronRight data-icon="inline-end" /></Button>
                      {/if}
                      {#if !m.read}
                        <Button size="sm" variant="secondary" disabled={busy} onclick={() => markRead([m])} data-testid="inbox-read"><Check />Mark read</Button>
                      {/if}
                    </div>
                  </div>
                </li>
              {/each}
            </ul>
          </section>
        {:else}
          <div class="flex flex-col items-center gap-3 rounded-[10px] border border-dashed px-6 py-12 text-center" data-testid="inbox-empty">
            <span class="flex size-10 items-center justify-center rounded-lg bg-muted text-muted-foreground"><InboxIcon class="size-5" /></span>
            <p class="font-medium">Nothing here yet</p>
            <p class="max-w-md text-sm text-muted-foreground">
              When an app notifies you, or an automation's agent finishes or a run fails, it comes here, to your desktop and to your phone.
            </p>
            <Button variant="outline" size="sm" href={href({ view: "automations" })}><Workflow />See your automations</Button>
          </div>
        {/each}
      {/if}
    </div>
  </div>
</div>
