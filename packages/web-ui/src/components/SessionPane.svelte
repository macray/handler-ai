<script lang="ts">
  // One running session, a pane of Running (views/RunningView.svelte). The agent lives in the
  // daemon and the attachment in the session store, so leaving the page or reloading does not
  // stop it; the pane attaches it while shown (`sessions.watch`). `full` (One): its caption with
  // its actions as icons, the panel they open beside it (Files, Network…) and its draft's bar;
  // else a compact header (its state's pill, ⋯, ⤢; the title on up to two lines; project · agent ·
  // since when; outlined in amber while it needs you). Only the pane with the focus has the
  // composer; the others say "Click to type here". Its permission cards are answered in
  // place either way.
  import { ask } from "../lib/ask.svelte";
  import AreaTag from "./AreaTag.svelte";
  import FolderOpen from "@lucide/svelte/icons/folder-open";
  import Smartphone from "@lucide/svelte/icons/smartphone";
  import Pencil from "@lucide/svelte/icons/pencil";
  import Library from "@lucide/svelte/icons/library-big";
  import ListChecks from "@lucide/svelte/icons/list-checks";
  import Play from "@lucide/svelte/icons/play";
  import PlugZap from "@lucide/svelte/icons/plug-zap";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import Plus from "@lucide/svelte/icons/plus";
  import Ellipsis from "@lucide/svelte/icons/ellipsis";
  import EyeOff from "@lucide/svelte/icons/eye-off";
  import Maximize2 from "@lucide/svelte/icons/maximize-2";
  import { untrack, type Snippet } from "svelte";
  import Workflow from "@lucide/svelte/icons/workflow";
  import Square from "@lucide/svelte/icons/square";
  import ShieldAlert from "@lucide/svelte/icons/shield-alert";
  import ShieldCheck from "@lucide/svelte/icons/shield-check";
  import AppWindow from "@lucide/svelte/icons/app-window";
  import SquareArrowOutUpRight from "@lucide/svelte/icons/square-arrow-out-up-right";
  import StartSteps from "./StartSteps.svelte";
  import MissingImage from "./MissingImage.svelte";
  import OutputView from "./OutputView.svelte";
  import type { Schema } from "../lib/runs";
  import { Button } from "$lib/components/ui/button";
  import Composer from "@handler/acp-view/components/Composer.svelte";
  import { FollowEnd } from "@handler/acp-view/lib/follow";
  import NetworkPanel from "./NetworkPanel.svelte";
  import Popover from "./Popover.svelte";
  import SaveSkillPanel from "./SaveSkillPanel.svelte";
  import SessionFiles from "./SessionFiles.svelte";
  import SessionAutomationRuns from "./SessionAutomationRuns.svelte";
  import PermissionPrompt from "@handler/acp-view/components/PermissionPrompt.svelte";
  import SessionControls from "./SessionControls.svelte";
  import SessionStatus from "./SessionStatus.svelte";
  import Plan from "@handler/acp-view/components/Plan.svelte";
  import Timeline from "@handler/acp-view/components/Timeline.svelte";
  import { contextFill, type HostDecision } from "@handler/acp-view/lib/session.svelte";
  import { activity, askedAtStep } from "@handler/acp-view/lib/tools";
  import { nextMode } from "../lib/agents";
  import { accessLabel, sessionModel } from "../lib/access";
  import { productName } from "../lib/harnesses.svelte";
  import { href, navigate } from "../lib/router.svelte";
  import { LIGHT_LABEL, lightTone, remote } from "../lib/remote.svelte";
  import { agentLabel, projects } from "../lib/projects.svelte";
  import { safetyLine, widenings } from "../lib/safety";
  import { areas } from "../lib/areas.svelte";
  import { PILL_LABEL, pillOf, sinceLabel } from "../lib/running.svelte";
  import { sessions, STATUS_LABEL, type LiveSession } from "../lib/sessions.svelte";
  import { onChange } from "../lib/events.svelte";
  import { api } from "../lib/api";
  import { menuUse } from "../lib/menuuse.svelte";
  import type { AutomationRun, SessionChanges } from "../lib/contracts.gen";
  import { openDraft, useDraft } from "../lib/drafts";

  let {
    session,
    full = false,
    opens,
    focused = false,
    back = false,
    onfocus,
    onhide,
    onalone,
    onended,
    title,
    lead,
    dragstart,
  }: {
    session: LiveSession;
    full?: boolean; // One: its caption and actions, its side panel
    opens?: "files" | "network"; // full: the panel it opens with (the route's: a compact pane's ⋯ asked)
    focused?: boolean; // the composer is here
    back?: boolean; // hidden, and back while it needs you
    onfocus?: () => void; // a click in it
    onhide?: () => void; // ⋯ Hide from All running
    onalone?: () => void; // ⤢ shown alone (One)
    onended?: (key: string) => void; // End session: it leaves
    title?: Snippet; // full: the title, a switcher (else a heading)
    lead?: Snippet; // full: before the title (full screen's control)
    dragstart?: (e: DragEvent) => void; // its header dragged (reordering)
  } = $props();

  const key = $derived(session.key);
  let menuOpen = $state(false);

  // its state and since when, ticking ("working · 6m", "idle · 2m ago")
  let now = $state(Date.now());
  $effect(() => {
    const timer = setInterval(() => (now = Date.now()), 15000);
    return () => clearInterval(timer);
  });
  const stateSince = $derived(sinceLabel(session, now));
  const pill = $derived(pillOf(session.status)); // the compact header's state
  // stopped because its agent program or the network filter is not built yet: it starts once it
  // is (MissingImage says so below), so its state says that, not "stopped"
  const WAITS = "can't start yet";
  const waits = $derived(session?.status === "stopped" && Boolean(session.info.missingImage));

  // What a screen reader is told when the session changes state: one short sentence, never the
  // streamed text (a live region beside the caption; the first state is the page's, not news).
  const NEWS: Partial<Record<string, string>> = {
    "needs-you": "The agent needs you.",
    replied: "The agent replied.",
    idle: "The agent finished.",
    working: "The agent is working.",
    elsewhere: "This session is open in another tab.",
    stopped: "The session stopped.",
    failed: "The session failed.",
  };
  // what the page shows under it, said the same: a turn that ended otherwise, a start waiting
  // for an image (F.1)
  function newsOf(status: string): string {
    if (status === "idle" && session.conn?.session.lastStop) return "The agent's turn ended early.";
    if (status === "stopped" && session.info.missingImage) return "The session can't start yet.";
    return NEWS[status] ?? "";
  }
  let news = $state("");
  let lastStatus: string | undefined;
  $effect(() => {
    const status = session?.status;
    if (lastStatus !== undefined && status && status !== lastStatus) news = newsOf(status);
    lastStatus = status;
  });
  const found = $derived(session ? projects.of(session.agent) : undefined); // its project and agent
  // a run of an app's job (H.11): no agent; its settings are the job's, on its app's page
  const jobApp = $derived(session?.info.job ? (session.info.app ?? null) : null);
  const settingsHref = $derived(
    jobApp ? href({ view: "apps", app: jobApp }) : found ? href({ view: "edit-agent", project: found.project.id, id: found.agent.id }) : href({ view: "agent", id: session?.agent.id ?? "" }),
  );
  const FILES_OPEN = "handler.files-open"; // the files pane stays open from a session to the next
  const FILES_WIDTH = "handler.files-width";
  let panel = $state<"files" | "network" | "save" | "automations" | null>(
    untrack(() => (full && opens) || (localStorage.getItem(FILES_OPEN) ? "files" : null)),
  ); // the side panel shown
  let automationRuns = $state<AutomationRun[]>([]); // what ran on it when it stopped (I)
  const isRun = $derived(Boolean(session?.info.unattended)); // a job's run (D.18): no prompt
  const folderless = $derived(Boolean(session && !session.agent.scope)); // its own folder (D.18)
  // its folder is a draft of an app's code (H.15): Use it makes it the app's next version, or a
  // new app, and the session goes with it
  const draft = $derived(session?.info.appDraft ?? null);
  // a plan builder's session (D.27): its folder is a plan draft, reviewed from here
  const planDraft = $derived(session?.info.planDraft ?? null);
  let using = $state(false);
  let drafted = $state<{ what: string; why: string } | null>(null); // why Open or Use it failed
  async function useIt(id: string): Promise<void> {
    using = true;
    drafted = null;
    try {
      await useDraft(id);
    } catch (e) {
      drafted = { what: draft?.app ? "Use it" : "Install it", why: (e as Error).message };
    } finally {
      using = false;
    }
  }
  function openIt(id: string): void {
    drafted = null;
    openDraft(id).catch((e: Error) => (drafted = { what: "Open the draft", why: e.message }));
  }
  /** The failure, in the input for the App creator (not sent: the person may add to it). */
  function askToFix(): void {
    if (!session || !drafted) return;
    const told = `${drafted.what} failed: ${drafted.why}\nFix it.`;
    session.draft = session.draft.trim() ? `${session.draft.trim()}\n\n${told}` : told;
    drafted = null;
  }
  const showNetwork = $derived(panel === "network");
  const label = $derived(session ? (found ? agentLabel(found.agent) : projects.label(session.agent)) : "");
  const where = $derived(found ? `${found.project.name} · ${label}` : session?.title ? label : "");

  // The terminal whatever the state, its conversation kept: stopped, failed or attached
  // elsewhere, what happened and how to go on takes the prompt's place.
  const running = $derived(session ? !["stopped", "failed", "elsewhere"].includes(session.status) : false);
  const failed = $derived(session?.info.state === "failed");

  // attached while shown (one started elsewhere: only while shown)
  $effect(() => {
    const s = session;
    return untrack(() => sessions.watch(s)); // once per session shown, whatever it then reads
  });

  // the focused pane's turns are seen as they end; the others' are "replied" until focused
  $effect(() => {
    if (!focused) return;
    sessions.viewing = session.key;
    sessions.seen(session);
    const visible = () => {
      if (!document.hidden) sessions.seen(session);
    };
    document.addEventListener("visibilitychange", visible);
    return () => {
      document.removeEventListener("visibilitychange", visible);
      if (sessions.viewing === session.key) sessions.viewing = null;
    };
  });

  $effect(() => {
    if (!full) return;
    const load = () =>
      void api
        .sessionAutomationRuns(key)
        .then((found) => (automationRuns = found))
        .catch(() => {});
    load();
    return onChange(["automations"], load); // they run after a stop
  });

  // Its folder's changes since it started (F.8): fetched every 10 s while the page is seen, and
  // soon after the agent finishes a tool call or a turn.
  let changes = $state<SessionChanges | null>(null);
  let seen = $state(new Set<string>()); // the changes looked at, shown in the files pane
  const changeKeys = $derived((changes?.files ?? []).map((c) => `${c.path}:${c.change}:${c.at}`));
  const unseen = $derived(panel !== "files" && changeKeys.some((k) => !seen.has(k)));
  let filesWidth = $state(Number(localStorage.getItem(FILES_WIDTH)) || 0); // px; 0: the default

  function loadChanges(): void {
    if (document.hidden) return;
    void api
      .sessionChanges(key)
      .then((found) => (changes = found))
      .catch(() => {});
  }

  $effect(() => {
    void key;
    changes = null;
    if (!full) return;
    loadChanges();
    const timer = setInterval(loadChanges, 10000);
    return () => clearInterval(timer);
  });

  $effect(() => {
    const conn = session?.conn;
    const done = conn?.session.entries.filter((e) => e.kind === "tool" && (e.status === "completed" || e.status === "failed")).length;
    void [done, conn?.busy];
    if (!full) return;
    const timer = setTimeout(loadChanges, 800);
    return () => clearTimeout(timer);
  });

  $effect(() => {
    if (panel === "files") seen = new Set(changeKeys);
  });

  /** From a compact pane's ⋯: the session in One, with the panel open. */
  function openInOne(which: "files" | "network"): void {
    if (which === "files") localStorage.setItem(FILES_OPEN, "1");
    navigate({ view: "session", key: session.key, panel: which });
  }

  function togglePanel(which: NonNullable<typeof panel>): void {
    panel = panel === which ? null : which;
    if (panel === "files") localStorage.setItem(FILES_OPEN, "1");
    else localStorage.removeItem(FILES_OPEN);
  }

  // The frame says what the agent's sandbox lets it do: its network and what weakens its sandbox
  // beyond what a new agent starts with ("4 sites · Runs containers"); amber when something does
  // (Any site, learning the sites, more than a plain container, windows on the screen).
  // what it runs on, the account or provider by its name alone (its kind is said where it is made)
  const runsOn = $derived.by(() => {
    const i = session?.info;
    return i ? [i.harness ? productName(i.harness) : "?", i.account ?? i.provider ?? "?", ...(i.model ? [i.model] : [])].join(" · ") : "";
  });

  const sandbox = $derived.by(() => {
    const a = session?.agent;
    if (!a) return { label: "", weak: false };
    const sites = new Set([...(a.model.requiredHosts ?? []).map((r) => r.host), ...(a.allow ?? [])]).size;
    return { label: safetyLine(a, sites), weak: a.network === "open" || widenings(a).length > 0 };
  });

  // hosts its network filter refused in this session that are neither allowed nor kept blocked
  // yet: a badge on its network button, a card each in the timeline (F.9)
  const undecided = $derived.by(() => {
    const a = session?.agent;
    return (session?.conn?.session.undecided ?? []).filter((h) => !a?.allow?.includes(h) && !a?.blocked?.includes(h));
  });
  async function decideHost(host: string, decision: HostDecision): Promise<void> {
    const s = session;
    if (!s?.conn) return;
    await s.conn.decideHost(host, decision);
    if (s.agent.id) sessions.updateAgent(await api.agent(s.agent.id));
  }


  // a path clicked in the conversation: shown in the files pane
  let fileRequest = $state<{ path: string; n: number } | null>(null);
  // the questions about a step the timeline does not show (yet): pinned under it; the others
  // are under their step
  const unplaced = $derived(
    session?.live && session.conn
      ? session.conn.permissions.filter((p) => !askedAtStep(session.conn!.session.entries, p.request.toolCall.toolCallId))
      : [],
  );

  /** Shift+Tab (or the phone's mode key): the harness's next mode, as Claude Code cycles them. */
  function cycleMode(): void {
    const conn = session?.conn;
    const next = conn && nextMode(conn.session.modes, conn.session.currentMode);
    if (conn && next) conn.setMode(next).catch((e: Error) => session && (session.error = e.message));
  }

  function openFile(path: string): void {
    if (panel !== "files") togglePanel("files");
    fileRequest = { path, n: (fileRequest?.n ?? 0) + 1 };
  }

  // the files pane's left edge: dragged (the pointer captured, so a gesture the browser takes
  // back ends it too), or moved with the arrow keys; a double click goes back to the default
  const FILES_MIN = 280;
  const filesMax = () => window.innerWidth - 360;
  function setFilesWidth(px: number): void {
    filesWidth = Math.min(Math.max(px, FILES_MIN), filesMax());
    localStorage.setItem(FILES_WIDTH, String(Math.round(filesWidth)));
  }
  function resize(event: PointerEvent): void {
    if (event.button !== 0) return;
    const grip = event.currentTarget as HTMLElement;
    const right = grip.parentElement!.getBoundingClientRect().right;
    const move = (e: PointerEvent) => (filesWidth = Math.min(Math.max(right - e.clientX, FILES_MIN), filesMax()));
    const ends = ["pointerup", "pointercancel", "lostpointercapture"] as const;
    const end = () => {
      grip.removeEventListener("pointermove", move);
      for (const type of ends) grip.removeEventListener(type, end);
      if (grip.hasPointerCapture(event.pointerId)) grip.releasePointerCapture(event.pointerId);
      setFilesWidth(filesWidth);
    };
    grip.setPointerCapture(event.pointerId);
    grip.addEventListener("pointermove", move);
    for (const type of ends) grip.addEventListener(type, end);
  }
  function resizeKey(event: KeyboardEvent): void {
    const step = event.shiftKey ? 96 : 24;
    const now = filesWidth || (event.currentTarget as HTMLElement).parentElement!.getBoundingClientRect().width;
    if (event.key === "ArrowLeft") setFilesWidth(now + step);
    else if (event.key === "ArrowRight") setFilesWidth(now - step);
    else if (event.key === "Home") setFilesWidth(filesMax());
    else if (event.key === "End") setFilesWidth(FILES_MIN);
    else return;
    event.preventDefault();
  }
  function resetFilesWidth(): void {
    filesWidth = 0;
    localStorage.removeItem(FILES_WIDTH);
  }

  // Follow new output (streamed text too) while the view is at its end; scrolled up, a button
  // goes back there, with how many entries came since.
  const follow = new FollowEnd();
  let away = $state<number | null>(null); // entries when the view left the end; null: following
  follow.onchange = (following) => (away = following ? null : (session?.conn?.session.entries.length ?? 0));
  const since = $derived(away === null ? 0 : Math.max(0, (session?.conn?.session.entries.length ?? 0) - away));
  const plan = $derived(session?.conn?.session.plan ?? []);
  const planLeft = $derived(plan.some((e) => e.status !== "completed"));
  $effect(() => {
    void key; // another session: at its end
    follow.resume();
  });
  $effect(() => {
    const conn = session?.conn;
    const last = conn?.session.entries.at(-1);
    void [conn?.session.entries.length, last && "text" in last ? last.text.length : 0, conn?.permissions.length, conn?.session.lastStop, session?.status];
    follow.toEnd();
  });

  async function another(): Promise<void> {
    if (!session) return;
    try {
      // with the model this one ran with
      navigate({ view: "session", key: (await sessions.start(session.agent, undefined, sessionModel(session.info))).key });
    } catch (e) {
      session.error = (e as Error).message;
    }
  }

  // Remote: share this session with the paired devices (remote design); off after a
  // stop.
  const shared = $derived(session ? remote.shared(session.key) : false);
  const remoteReady = $derived(Boolean(remote.status?.gatewayUrl));
  const remoteTitle = $derived(
    !remoteReady
      ? "To share it with your phone, set a gateway first: Settings → Your phone"
      : shared
        ? `Shared with your paired devices (${LIGHT_LABEL[remote.light ?? "off"]}). Click to stop sharing.`
        : "Share this session with your paired devices (phone, tablet)",
  );

  async function toggleRemote(): Promise<void> {
    if (!session) return;
    try {
      await remote.share(session.key, !shared);
    } catch (e) {
      session.error = (e as Error).message;
    }
  }

  async function end(): Promise<void> {
    if (!session) return;
    const busy = session.status === "working" || session.status === "needs-you";
    const who = found ? agentLabel(found.agent) : label;
    const where = found ? `${found.project.name}'s sessions` : `${who}'s sessions`;
    const detail = `${who} stops now${busy ? ", mid-task" : ""}. The conversation stays in ${where}, to read or continue later.`;
    if (!(await ask({ title: "End this session?", detail, yes: "End session", danger: true }))) return;
    const ending = session.key; // gone from the list once closed
    void sessions.close(session);
    onended?.(ending);
  }
</script>

<!-- What can be done with it, on its caption's right (One): its folder, its sandbox and network,
     the phone, its agent, the end. -->
{#snippet actionRow()}
  {#if session}
      <div class="actions">
        <Button
          variant={panel === "files" ? "secondary" : "ghost"}
          size="icon-sm"
          class="badged"
          onclick={() => togglePanel("files")}
          aria-pressed={panel === "files"}
          title={changes?.files?.length
            ? `Files: ${changes.files.length} file${changes.files.length === 1 ? "" : "s"} changed in the session's folder since it started`
            : "Files: the session's folder, and what changed since it started"}
          aria-label="Files"
          data-testid="files-toggle"
        >
          <FolderOpen />
          {#if changes?.files?.length}<span class="count tabular-nums" class:unseen data-testid="files-count">{changes.files.length}</span>
          {:else if unseen}<span class="dot bg-primary" aria-label="new changes"></span>{/if}
        </Button>
        {#if !jobApp}<Button
          variant={showNetwork ? "secondary" : "ghost"}
          size="icon-sm"
          class={["badged", sandbox.weak ? "text-warn hover:text-warn" : ""]}
          onclick={() => togglePanel("network")}
          aria-pressed={showNetwork}
          title="Network: what it reached, what was refused. Its sandbox: {sandbox.label}.{undecided.length
            ? ` ${undecided.length} site${undecided.length === 1 ? "" : "s"} blocked, not answered yet.`
            : ''}"
          aria-label="Network"
          data-testid="session-sandbox"
        >
          {#if sandbox.weak}<ShieldAlert />{:else}<ShieldCheck />{/if}
          {#if undecided.length}<span class="count waits tabular-nums" aria-label="{undecided.length} blocked" data-testid="blocked-count">{undecided.length}</span>{/if}
        </Button>{/if}
        {#if session.live && !remoteReady}
          <Button variant="ghost" size="icon-sm" href={href({ view: "settings", section: "phone" })} title={remoteTitle} aria-label="On your phone" data-testid="remote-toggle">
            <Smartphone />
          </Button>
        {:else if session.live}
          <Button variant={shared ? "secondary" : "ghost"} size="icon-sm" class={["badged", shared && "text-primary hover:text-primary"]} onclick={toggleRemote} aria-pressed={shared} title={remoteTitle} aria-label="On your phone" data-testid="remote-toggle">
            <Smartphone />{#if shared}<span class="dot {lightTone(remote.light)}" aria-hidden="true"></span>{/if}
          </Button>
        {/if}
        {#if automationRuns.length}
          <Button
            variant={panel === "automations" ? "secondary" : "ghost"}
            size="icon-sm"
            onclick={() => togglePanel("automations")}
            aria-pressed={panel === "automations"}
            title="The automations that ran on this conversation"
            aria-label="Automations"
            data-testid="session-automations-toggle"
          >
            <Workflow />
          </Button>
        {/if}
        {#if isRun}
          <Button variant="ghost" size="icon-sm" href={href({ view: "run", id: session.key })} title="What it was given and what it gave back" aria-label="Run" data-testid="session-run">
            <ListChecks />
          </Button>
        {/if}
        {#if !draft && !planDraft && folderless && !isRun}
          <Button
            variant={panel === "save" ? "secondary" : "ghost"}
            size="icon-sm"
            onclick={() => togglePanel("save")}
            aria-pressed={panel === "save"}
            title="The skill in this session's folder, into your library"
            aria-label="Save to library"
            data-testid="save-skill-toggle"
          >
            <Library />
          </Button>
        {/if}
        <Button
          variant="ghost"
          size="icon-sm"
          href={settingsHref}
          title={jobApp ? "Its job's settings: on the app's page" : found ? "Agent settings" : "Agent settings: on the agent's page"}
          aria-label={jobApp ? "The app's page" : "Agent settings"}
          data-testid="session-settings"
        >
          <Pencil />
        </Button>
        <span class="divider" aria-hidden="true"></span>
        <Button variant="ghost" size="icon-sm" class="end text-danger hover:text-danger" onclick={end} title="End session: it stops the agent and its sandbox; the conversation stays" aria-label="End session" data-testid="end-session">
          <Square />
        </Button>
      </div>
  {/if}
{/snippet}

<!-- what a session started from its agent's form was given: the form filled in, not the request
     the agent read (its instructions, the input as JSON) -->
{#snippet started()}
  {#if session?.info.input}
    <div class="started" data-testid="session-brief">
      <p class="started-label">{isRun ? "Its form" : "The brief"}</p>
      <OutputView schema={session.agent.interface?.fields as Schema | undefined} value={session.info.input.fields ?? {}} />
    </div>
  {/if}
{/snippet}

<!-- svelte-ignore a11y_no_static_element_interactions (a click anywhere in it gives it the focus; its composer is the control) -->
<div
  class="room term-surface"
  class:pane={!full}
  class:focused={focused && !full}
  class:needs={!full && session.status === "needs-you"}
  class:back
  onpointerdown={() => !focused && onfocus?.()}
  data-testid="session-pane"
  data-session={session.key}
  data-focused={focused}
>
  {#if full}
    <header class="caption" data-testid="session-header">
      {@render lead?.()}
      <!-- what it runs on: said when pointed at -->
      <div class="title" title={session.info.harnessVersion ? `${runsOn} · installed in its image: ${session.info.harnessVersion}` : runsOn} data-testid="session-caption">
        {#if title}{@render title()}{:else}<h1>{session.title ?? label}</h1>{/if}<span class="where"
          >{#if found}<a href={href({ view: "project", id: found.project.id })} class="where-project" data-testid="session-project">{found.project.name}</a> · {agentLabel(found.agent)}{:else}{label}{/if}</span
        >{#if found?.project.area}<AreaTag name={found.project.area} />{/if}
      </div>
      <SessionStatus status={session.status} label text={waits ? WAITS : undefined} />
      {#if stateSince}<span class="since tabular-nums">{stateSince}</span>{/if}
      {#if focused}<p class="sr-only" role="status" data-testid="session-news">{news}</p>{/if}
      {@render actionRow()}
    </header>
  {:else}
    <!-- the compact header: dragged to reorder; its ⋯ the header's actions (and Hide), ⤢ shows it alone -->
    <header class="bar" draggable={dragstart ? "true" : undefined} ondragstart={dragstart} data-testid="pane-header" title={runsOn}>
      <div class="bar-top">
      <span class="pill {pill}" title={STATUS_LABEL[session.status]} data-testid="pane-state" data-pill={pill}
        >{#if pill === "working"}<span class="pill-dot" aria-hidden="true"></span>{/if}{waits ? WAITS : PILL_LABEL[pill]}</span
      >
      {#if back}<span class="bar-hidden" title="Hidden from All running: back while it needs you" data-testid="pane-hidden">hidden</span>{/if}
      <span class="flex-1"></span>
      <Popover bind:open={menuOpen} align="end" label="Session" width="15rem" testid="pane-menu">
        {#snippet trigger(props)}
          <button type="button" class="bar-icon" {...props} aria-label="More" title="More" data-testid="pane-more"><Ellipsis class="size-4" /></button>
        {/snippet}
        {#snippet children(close)}
          <!-- the header's actions, in its order (Files and Network open in One, with the panel) -->
          <button type="button" class="menu-item" onclick={() => (close(), openInOne("files"))} data-testid="pane-files"
            ><FolderOpen />Files</button
          >
          {#if !jobApp}<button type="button" class="menu-item" onclick={() => (close(), openInOne("network"))} data-testid="pane-network"
            >{#if sandbox.weak}<ShieldAlert class="text-warn" />{:else}<ShieldCheck />{/if}Network<span class="menu-hint" class:text-warn={undecided.length}
              >{undecided.length ? `${undecided.length} blocked` : sandbox.label}</span
            ></button
          >{/if}
          {#if session.live && !remoteReady}
            <a class="menu-item" href={href({ view: "settings", section: "phone" })} title={remoteTitle} onclick={close} data-testid="pane-remote"><Smartphone />On your phone<span class="menu-hint">set up</span></a>
          {:else if session.live}
            <button type="button" class="menu-item" role="switch" aria-checked={shared} title={remoteTitle} onclick={toggleRemote} data-testid="pane-remote"
              ><Smartphone />On your phone<span class="menu-switch" class:on={shared} aria-hidden="true"><span></span></span></button
            >
          {/if}
          <a class="menu-item" href={settingsHref} onclick={close} data-testid="pane-agent-settings"><Pencil />{jobApp ? "The app's page" : "Agent settings"}</a>
          {#if onhide}<button type="button" class="menu-item" onclick={() => (close(), onhide())} data-testid="pane-hide"><EyeOff />Hide</button>{/if}
          <div class="menu-divider" role="separator"></div>
          <button type="button" class="menu-item menu-end" onclick={() => (close(), end())} data-testid="pane-end"><Square />End session…</button>
        {/snippet}
      </Popover>
      {#if onalone}<button type="button" class="bar-icon" onclick={onalone} aria-label="Show it alone" title="Show it alone" data-testid="pane-alone"><Maximize2 class="size-4" /></button>{/if}
      </div>
      <h2 class="bar-title" title={session.title ?? label} data-testid="pane-title">{session.title ?? label}</h2>
      <p class="bar-where {areas.colorClass(found?.project.area)}" data-testid="pane-where"
        ><span class="swatch" aria-hidden="true"></span><span class="bar-where-text"
          >{[found ? found.project.name : "outside projects", found ? agentLabel(found.agent) : label, stateSince].filter(Boolean).join(" · ")}</span
        ></p
      >
    </header>
  {/if}
    {#if full && draft}
      <!-- what an App creator's session is for: its draft, tried and used from here -->
      <div class="draft-bar" data-testid="session-draft">
        <AppWindow class="size-4 flex-none text-muted-foreground" />
        <p class="draft-what">
          {draft.app ? `Draft of ${menuUse.title(draft.app)}` : "A new app"}
          <span class="text-muted-foreground">· {draft.app ? "opened on copies of its data and folders" : "its code is kept by Handler until you install it"}</span>
        </p>
        <div class="draft-actions">
          <Button
            size="sm"
            variant="outline"
            title="The app as this draft makes it, in a new tab, on copies of its data and folders"
            onclick={() => session && openIt(session.key)}
            data-testid="draft-open">Open the draft<SquareArrowOutUpRight /></Button
          >
          <Button
            size="sm"
            disabled={using}
            title={draft.app ? `This draft becomes ${menuUse.title(draft.app)}'s next version, deployed; this session ends` : "This draft becomes a new app (its install page); this session ends"}
            onclick={() => session && useIt(session.key)}
            data-testid="draft-use">{using ? "Using it…" : draft.app ? `Use it for ${menuUse.title(draft.app)}` : "Install it"}</Button
          >
        </div>
        {#if drafted}
          <div class="draft-problem" role="alert" data-testid="draft-error">
            <p><b>{drafted.what} failed.</b> <code>{drafted.why}</code></p>
            {#if !isRun}
              <button type="button" class="cursor-pointer text-link hover:underline" onclick={askToFix} data-testid="draft-fix">Ask the App creator to fix it</button>
            {/if}
          </div>
        {/if}
      </div>
    {/if}
    {#if full && planDraft}
      <!-- what a plan builder's session is for: its draft, reviewed (and approved) from here -->
      <div class="draft-bar" data-testid="session-plan-draft">
        <ListChecks class="size-4 flex-none text-muted-foreground" />
        <p class="draft-what">
          A plan for {projects.list.find((p) => p.id === planDraft.projectId)?.name ?? planDraft.folder}
          <span class="text-muted-foreground">· a draft Handler keeps; the project is seen read-only</span>
        </p>
        <div class="draft-actions">
          <Button size="sm" href={href({ view: "review-plan", draft: planDraft.id })} data-testid="plan-draft-review"><ListChecks />Review this plan</Button>
        </div>
      </div>
    {/if}
  <div
    class="session"
    class:with-network={panel !== null && panel !== "files"}
    class:with-files={panel === "files"}
    style:--files-width={filesWidth ? `${filesWidth}px` : null}
  >
    <div class="term">
      <div class="screen-box">
        <div class="screen" {@attach follow.attach}>
          {#if session.conn}
            <Timeline
              session={session.conn.session}
              root={session.info.scope}
              onopen={openFile}
              pinPlan
              busy={session.conn.busy}
              asking={session.conn.permissions.map((p) => p.request.toolCall.toolCallId)}
              permissions={session.live ? session.conn.permissions : []}
              first={session.info.input ? started : undefined}
              ondecide={decideHost}
              agent={label}
              tells={!isRun}
              providers={href({ view: "settings", section: "models" })}
            >
              {#snippet empty()}
                <!-- what it is ready with; stopped before its first turn, the footer says why -->
                {#if running}
                  <div class="start" data-testid="session-start">
                    <p class="start-title">{found ? agentLabel(found.agent) : projects.label(session.agent)} is ready</p>
                    <dl>
                      <dt>Folder</dt><dd>{session.info.scope}</dd>
                      <dt>Model</dt><dd>{accessLabel(session.info)}</dd>
                      <dt>Can do</dt><dd>{sandbox.label}</dd>
                    </dl>
                    {#if !isRun && session.conn?.session.commands.length}
                      <div class="commands">
                        {#each session.conn.session.commands.slice(0, 8) as c (c.name)}
                          <button type="button" title={c.description} onclick={() => (session.draft = `/${c.name} `)}>/{c.name}</button>
                        {/each}
                      </div>
                    {/if}
                    {#if !isRun}<p class="hint">Type <kbd>@</kbd> to name a file of its folder, <kbd>/</kbd> for its commands.</p>{/if}
                  </div>
                {/if}
              {/snippet}
            </Timeline>
          {:else if running}
            {#if session.startup}<StartSteps startup={session.startup} access={accessLabel(session.info)} />{:else}<p class="text-muted-foreground">Starting a sandbox for {accessLabel(session.info)}…</p>{/if}
          {:else}
            <p class="text-muted-foreground">The conversation is shown again once the agent runs.</p>
          {/if}

          {#if session.error && running}<p class="text-danger" data-testid="error">✗ {session.error}</p>{/if}
        </div>
        {#if away !== null}
          <button type="button" class="latest" onclick={() => follow.resume()} data-testid="to-latest">
            ↓ Latest{#if since}&nbsp;<span class="tabular-nums">· {since} new</span>{/if}
          </button>
        {/if}
      </div>

      {#if session.live && planLeft}<Plan entries={plan} />{/if}

      {#if unplaced.length}
        <div class="asks" data-testid="pinned-permissions">
          {#each unplaced as pending (pending.request.toolCall.toolCallId)}
            <PermissionPrompt {pending} root={session.info.scope} />
          {/each}
        </div>
      {/if}

      {#if session.live && session.conn && isRun}
        <footer>
          <p class="text-sm text-muted-foreground" data-testid="run-note">
            An unattended run: it takes no prompt. <a class="text-link hover:underline" href={href({ view: "run", id: session.key })}>Its result</a>
          </p>
        </footer>
      {:else if session.live && session.conn && !focused}
        <footer>
          <button type="button" class="type-here" onclick={() => onfocus?.()} data-testid="click-to-type">{session.draft.trim() ? session.draft.trim().split("\n")[0] : "Click to type here"}</button>
        </footer>
      {:else if session.live && session.conn}
        <footer>
          <Composer
            autofocus
            bind:text={session.draft}
            bind:images={session.draftImages}
            takesImages={session.conn.takesImages}
            busy={session.conn.busy}
            commands={session.conn.session.commands}
            onsend={(prompt) => {
              follow.resume();
              void sessions.send(session, prompt);
            }}
            oncancel={() => session.conn?.cancel()}
            turnStartedAt={session.conn.turnStartedAt}
            interrupting={session.conn.interrupting}
            waiting={session.conn.permissions.length > 0}
            queued={session.queued}
            onqueue={(prompt) => sessions.queue(session, prompt)}
            onsendnow={() => {
              follow.resume();
              void sessions.sendNow(session);
            }}
            ondeletequeued={() => (session.queued = null)}
            findFiles={async (q) => (await api.sessionFind(session.key, q)).paths}
            activity={activity(session.conn.session.entries, session.info.scope)}
            onmode={session.conn.session.modes.length ? cycleMode : undefined}
            context={session.conn.session.usage ? contextFill(session.conn.session.usage).percent : null}
          >
            {#snippet tools()}<SessionControls conn={session.conn!} harness={session.info.harness} own={session.agent.permissions} />{/snippet}
          </Composer>
        </footer>
      {:else if session.conn && session.status === "starting"}
        <footer>
          <div class="text-sm" data-testid="starting">
            {#if session.startup}<StartSteps startup={session.startup} access={accessLabel(session.info)} />{:else}<p class="text-muted-foreground">Starting a sandbox for {accessLabel(session.info)}…</p>{/if}
          </div>
        </footer>
      {:else if !running && session.status !== "elsewhere" && session.info.missingImage}
        <!-- its start refused: an image it needs is not built yet (F.1); prepared from here -->
        <footer class="ended" data-testid="closed">
          <MissingImage target={session.info.missingImage} agent={label} refused={session.info.lastActivityAt} request={session.info.request} error={session.info.error ?? session.error} onstart={() => sessions.connect(session)} />
        </footer>
      {:else if !running}
        <!-- stopped, failed or attached elsewhere: what happened and how to go on, in place of the prompt -->
        <footer class="ended" data-testid="closed">
          <div class="flex flex-wrap items-center gap-x-4 gap-y-3">
            <span class="grid size-8 shrink-0 place-items-center rounded-full {session.error || failed ? 'bg-danger/10 text-danger' : 'bg-muted text-foreground'}">
              {#if session.error || failed}<TriangleAlert class="size-4" />{:else if session.status === "elsewhere"}<PlugZap class="size-4" />{:else}<Play class="size-4" />{/if}
            </span>
            <div class="min-w-0 flex-1 basis-64 space-y-0.5">
              {#if session.status === "elsewhere"}
                <h2 class="text-sm font-semibold">Open in other tabs</h2>
                <p class="text-sm text-muted-foreground">
                  Too many clients were attached to this session, so this tab was detached. The agent keeps running.
                </p>
              {:else if failed}
                <h2 class="text-sm font-semibold">The session failed</h2>
                <p class="text-sm text-muted-foreground">Its agent stopped with an error. Start a new session with it, or stop this one.</p>
              {:else}
                <h2 class="text-sm font-semibold">The agent is stopped</h2>
                <p class="text-sm text-muted-foreground">
                  {session.conn?.closed?.reason ? `${session.conn.closed.reason}. ` : ""}Resuming restarts it in a new sandbox and continues this
                  conversation.
                </p>
              {/if}
              {#if session.draft.trim() || session.draftImages.length}
                <p class="text-sm text-muted-foreground" data-testid="draft-kept">Your unsent message is kept: it is back in the input when the agent runs.</p>
              {/if}
            </div>
            {#if session.status === "elsewhere"}
              <Button onclick={() => sessions.connect(session)} data-testid="reconnect">Reattach</Button>
            {:else if failed}
              {#if !jobApp}<Button onclick={another}><Plus />New session</Button>{/if}
            {:else}
              <Button onclick={() => sessions.connect(session)} data-testid="reconnect"><Play />Resume</Button>
            {/if}
          </div>
          {#if session.error}
            <pre
              class="w-full rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-left text-xs whitespace-pre-wrap text-danger [overflow-wrap:anywhere]"
              data-testid="error">{session.error}</pre>
          {/if}
        </footer>
      {/if}
    </div>

    {#if panel && full}
      <!-- beside the session -->
      <aside class:files={panel === "files"}>
        {#if panel === "files"}
          <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions (a focusable separator is a control: ARIA's window splitter) -->
          <div
            class="grip"
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize the files panel"
            aria-valuemin={FILES_MIN}
            aria-valuemax={filesMax()}
            aria-valuenow={filesWidth ? Math.round(filesWidth) : undefined}
            tabindex="0"
            title="Drag or use the arrow keys to resize; double-click for the default width"
            onpointerdown={resize}
            onkeydown={resizeKey}
            ondblclick={resetFilesWidth}
          ></div>
          <SessionFiles sessionId={session.key} folder={session.info.scope} {changes} request={fileRequest} onclose={() => togglePanel("files")} />
        {:else if showNetwork}
          <NetworkPanel agent={session.agent} session={session.info} onchange={(r) => sessions.updateAgent(r)} />
        {:else if panel === "save"}
          <SaveSkillPanel sessionId={session.key} />
        {:else if panel === "automations"}
          <SessionAutomationRuns runs={automationRuns} />
        {/if}
      </aside>
    {/if}
  </div>
</div>

<style>
  /* The session is one dark room from the menu's edge to the window's: its caption, the terminal,
     and the panel it opens (Files, Network…) beside it, divided by a line, never a card. */
  .room {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .caption {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    height: 3rem;
    flex: none;
    padding: 0 1rem 0 0.75rem;
    border-bottom: 1px solid var(--border);
    font-family: var(--sans);
    font-size: 0.875rem;
  }
  /* A pane of Running (not One): a dark card on the stage; the focused one ringed in the
     accent; one that needs you (first on the stage) outlined in amber, ringed too if focused. */
  .room.pane {
    height: 100%;
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
  }
  .room.pane.focused {
    border-color: var(--primary);
    box-shadow: 0 0 0 1px var(--primary);
  }
  .room.pane.needs {
    border-color: var(--warn);
    box-shadow: inset 0 0 0 1px var(--warn);
  }
  .room.pane.needs.focused {
    box-shadow:
      inset 0 0 0 1px var(--warn),
      0 0 0 2px var(--primary);
  }
  /* the compact header: the state pill, ⋯ and ⤢; the title on up to two lines; project · agent ·
     since when */
  .bar {
    display: flex;
    flex-direction: column;
    flex: none;
    padding: 0.5rem 0.4rem 0.55rem 0.75rem;
    border-bottom: 1px solid var(--border);
    font-family: var(--sans);
    font-size: 0.8125rem;
  }
  .bar[draggable="true"] {
    cursor: grab;
  }
  .bar-top {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    min-width: 0;
  }
  .pill {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    height: 1.35rem;
    flex: none;
    padding: 0 0.5rem;
    border-radius: 6px;
    font-family: var(--mono);
    font-size: 0.72rem;
    font-weight: 600;
    white-space: nowrap;
    background: var(--muted);
    color: var(--muted-foreground);
  }
  .pill.needs-you {
    background: color-mix(in oklab, var(--warn) 22%, transparent);
    color: var(--warn);
  }
  .pill.working {
    background: color-mix(in oklab, var(--ok) 18%, transparent);
    color: var(--ok);
  }
  .pill.stopped {
    background: color-mix(in oklab, var(--danger) 18%, transparent);
    color: var(--danger);
  }
  .pill-dot {
    width: 0.4rem;
    height: 0.4rem;
    border-radius: 50%;
    background: currentColor;
  }
  .bar-hidden {
    font-family: var(--mono);
    font-size: 0.72rem;
    color: var(--warn);
  }
  .bar-title {
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    overflow: hidden;
    margin: 0.3rem 0.35rem 0 0;
    font-size: 0.875rem;
    font-weight: 600;
    line-height: 1.3;
    overflow-wrap: anywhere;
  }
  .bar-where {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    min-width: 0;
    margin: 0.15rem 0.35rem 0 0;
    font-family: var(--mono);
    font-size: 0.72rem;
    color: var(--muted-foreground);
  }
  .bar-where-text {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .swatch {
    width: 0.45rem;
    height: 0.45rem;
    flex: none;
    border-radius: 2px;
    background: var(--area, var(--muted-foreground));
  }
  .bar-icon {
    display: grid;
    place-items: center;
    width: 1.6rem;
    height: 1.6rem;
    flex: none;
    border-radius: 6px;
    color: var(--muted-foreground);
  }
  .bar-icon:hover {
    background: var(--muted);
    color: var(--foreground);
  }
  /* the compact header's ⋯ (Popover's rows): a hint or a switch on a row's right, End apart */
  .menu-hint {
    min-width: 0;
    margin-left: auto;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 12px;
    color: var(--muted-foreground);
  }
  .menu-switch {
    position: relative;
    flex: none;
    width: 28px;
    height: 16px;
    margin-left: auto;
    border-radius: 999px;
    background: color-mix(in oklab, var(--foreground) 16%, transparent);
    transition: background var(--dur-1) var(--ease);
  }
  .menu-switch span {
    position: absolute;
    top: 2px;
    left: 2px;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: var(--background);
    box-shadow: 0 1px 2px rgb(0 0 0 / 0.2);
    transition: transform var(--dur-1) var(--ease);
  }
  .menu-switch.on {
    background: var(--primary);
  }
  .menu-switch.on span {
    transform: translateX(12px);
  }
  .menu-divider {
    margin: 4px 0;
    border-top: 1px solid var(--border);
  }
  .menu-item.menu-end,
  .menu-item.menu-end :global(svg) {
    color: var(--danger);
  }
  .since {
    font-family: var(--mono);
    font-size: 0.75rem;
    color: var(--muted-foreground);
  }
  .where-project {
    color: inherit;
    text-decoration: underline;
    text-decoration-color: var(--border);
    text-underline-offset: 3px;
  }
  .type-here {
    width: 100%;
    padding: 0.45rem 0.7rem;
    overflow: hidden;
    border: 1px dashed var(--border);
    border-radius: 6px;
    text-align: left;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--muted-foreground);
  }
  .type-here:hover {
    border-color: var(--primary);
  }
  .draft-bar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem 0.75rem;
    flex: none;
    padding: 0.5rem 1rem;
    border-bottom: 1px solid var(--border);
    background: var(--muted);
    font-family: var(--sans);
    font-size: 0.875rem;
  }
  .draft-what {
    flex: 1;
    min-width: 12rem;
  }
  .draft-actions {
    display: flex;
    gap: 0.375rem;
  }
  .draft-problem {
    flex-basis: 100%;
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0.25rem 0.75rem;
    padding: 0.4rem 0.6rem;
    border-radius: 7px;
    background: color-mix(in srgb, var(--danger) 8%, transparent);
    font-size: 0.8rem;
  }
  .draft-problem p {
    flex: 1;
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .draft-problem b {
    color: var(--danger);
    font-weight: 600;
  }
  .draft-problem code {
    font-family: var(--mono);
    font-size: 0.75rem;
  }
  .draft-problem button {
    margin-left: auto;
    white-space: nowrap;
  }
  .title {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.2rem 0.5rem;
    border-radius: 8px;
    text-align: left;
    font-size: inherit;
  }
  .title h1 {
    min-width: 0;
    flex: none;
    max-width: 60%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-weight: 500;
  }
  .where {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--muted-foreground);
  }
  .session {
    flex: 1;
    min-height: 0;
    display: grid;
    grid-template-columns: minmax(0, 1fr);
  }
  .session.with-network {
    grid-template-columns: minmax(0, 1fr) 320px;
  }
  .session.with-files {
    grid-template-columns: minmax(0, 1fr) var(--files-width, min(42%, 720px));
  }
  .term {
    display: flex;
    flex-direction: column;
    min-height: 0;
  }
  .actions {
    display: flex;
    flex: none;
    align-items: center;
    gap: 0.125rem;
    margin: 0 -0.25rem 0 0.5rem;
    color: var(--muted-foreground);
  }
  /* End session apart from the everyday actions: after a divider, red-tinted (UI-UX guide: red
     when it loses something) */
  .actions .divider {
    width: 1px;
    height: 1.25rem;
    margin: 0 0.375rem;
    background: var(--border);
  }
  .actions :global(.end) {
    border: 1px solid color-mix(in oklab, var(--danger) 45%, transparent);
  }
  /* what an action has to tell (files changed, shared) sits on its corner: every action keeps one
     size, the row never moves */
  .actions :global(.badged) {
    position: relative;
  }
  .actions .count {
    position: absolute;
    top: -0.2rem;
    right: -0.2rem;
    min-width: 0.9rem;
    height: 0.9rem;
    padding: 0 0.2rem;
    border-radius: 999px;
    background: var(--muted);
    color: var(--foreground);
    font-size: 0.625rem;
    line-height: 0.9rem;
    text-align: center;
  }
  /* hosts blocked that wait for an answer: amber, as what waits for you */
  .actions .count.waits {
    background: var(--warn);
    color: var(--background);
  }
  .actions .count.unseen {
    background: var(--primary);
    color: var(--primary-foreground);
  }
  .actions .dot {
    position: absolute;
    top: 0.2rem;
    right: 0.2rem;
    width: 0.4rem;
    height: 0.4rem;
    border-radius: 999px;
  }
  .screen {
    flex: 1;
    min-height: 8rem;
    overflow-y: auto;
    padding: 0.75rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
    scrollbar-width: thin;
    scrollbar-color: var(--border) transparent;
  }
  .started {
    margin: 0 0 1rem;
    padding: 0.75rem 1rem;
    border: 1px solid var(--border);
    border-radius: 0.5rem;
    font-family: var(--sans);
    color: var(--foreground);
  }
  .started-label {
    margin: 0 0 0.5rem;
    font-size: 0.75rem;
    color: var(--muted-foreground);
  }
  .start {
    padding: 1rem 0 1.5rem;
    max-width: 44rem;
    color: var(--muted-foreground);
  }
  .start-title {
    margin: 0 0 0.6rem;
    color: var(--foreground);
    font-family: var(--sans);
    font-size: 1.15rem;
    font-weight: 600;
  }
  .start dl {
    display: grid;
    grid-template-columns: max-content minmax(0, 1fr);
    gap: 0.15rem 2ch;
    margin: 0 0 0.9rem;
  }
  .start dd {
    margin: 0;
    color: var(--foreground);
    overflow-wrap: anywhere;
  }
  .commands {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    margin-bottom: 0.7rem;
  }
  .commands button {
    padding: 0.1rem 0.6rem;
    border: 1px solid var(--border);
    border-radius: 999px;
    color: var(--link);
  }
  .commands button:hover {
    border-color: var(--primary);
  }
  .hint {
    margin: 0;
  }
  .hint kbd {
    font: inherit;
    color: var(--foreground);
  }
  .screen-box {
    position: relative;
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .latest {
    position: absolute;
    bottom: 0.75rem;
    left: 50%;
    translate: -50% 0;
    padding: 0.2rem 0.8rem;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--card);
    color: var(--foreground);
    box-shadow: 0 6px 20px -4px rgb(0 0 0 / 0.5);
    animation: rise var(--dur-3) var(--ease-spring) backwards;
    transition: border-color var(--dur-1);
  }
  .latest:hover {
    border-color: var(--primary);
  }
  .asks {
    padding: 0 1rem;
    max-height: 50%;
    overflow-y: auto;
    flex: none;
  }
  footer {
    padding: 0.6rem 1rem 0.75rem;
    background: var(--background);
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }
  footer.ended {
    padding: 0.75rem 1rem;
    gap: 0.6rem;
  }
  aside {
    overflow-y: auto;
    border-left: 1px solid var(--border);
    padding: 1rem;
    background: var(--card);
    font-family: var(--sans);
    font-size: 0.875rem;
    animation: panel-in var(--dur-3) var(--ease) backwards;
  }
  @keyframes panel-in {
    from {
      opacity: 0;
      transform: translateX(16px);
    }
  }
  aside.files {
    position: relative;
    padding: 0;
    overflow: hidden;
  }
  /* 10px to grab, a 2px line to see: the border on hover, the ring when focused */
  .grip {
    position: absolute;
    inset: 0 auto 0 0;
    width: 10px;
    cursor: col-resize;
    touch-action: none;
    z-index: 1;
    outline: none;
  }
  .grip::after {
    content: "";
    position: absolute;
    inset: 0 auto 0 0;
    width: 2px;
    transition: background-color var(--dur-1) var(--ease);
  }
  .grip:hover::after {
    background: var(--border);
  }
  .grip:focus-visible::after,
  .grip:active::after {
    background: var(--ring);
  }
</style>
