<script lang="ts">
  // One agent's workspace, beside the list of its place (a project, or outside projects): who it
  // is (how it is used, what comes in and out of it, its schedules, Edit), how it starts, in one
  // dark console (a request for a chat; its form for a brief or a job), what it is in three
  // blocks (AgentReceipt: who works, what it is given, what it may do), then what it did, a
  // timeline (its sessions and terminals; a job's runs, each with its result). In a project's
  // Sessions tab (`tabbed`: the agents are tabs, its name and Edit on their row) only the box,
  // who works and what it gets and may do as chips in its footer (what it uses: no list of it),
  // and what it did.
  import Pencil from "@lucide/svelte/icons/pencil";
  import Play from "@lucide/svelte/icons/play";
  import type { Snippet } from "svelte";
  import { Button } from "$lib/components/ui/button";
  import { Textarea } from "$lib/components/ui/textarea";
  import AgentChecks from "./AgentChecks.svelte";
  import AgentChips from "./AgentChips.svelte";
  import AgentReceipt from "./AgentReceipt.svelte";
  import AgentSchedules from "./AgentSchedules.svelte";
  import InterfaceStrip from "./InterfaceStrip.svelte";
  import ModelChoice from "./ModelChoice.svelte";
  import RunForm from "./RunForm.svelte";
  import Timeline, { type TimelineEntry } from "./Timeline.svelte";
  import UseChip from "./UseChip.svelte";
  import UsesPanel from "./UsesPanel.svelte";
  import { accessLabel } from "../lib/access";
  import { terminalsOf } from "../lib/agents";
  import type { Agent, AutomationView, ModelAccess, Project, Session } from "../lib/contracts.gen";
  import { useOfAgent } from "../lib/interface";
  import { agentLabel, makeModelDefault } from "../lib/projects.svelte";
  import { href, navigate } from "../lib/router.svelte";
  import { inputSummary, runState, startedBy, verdictOf, type Schema } from "../lib/runs";
  import { sessions, STATUS_LABEL, type SessionStatus as Status } from "../lib/sessions.svelte";

  let {
    agent,
    list,
    automations,
    edit,
    tags,
    onstarted,
    onchanged,
    partOf = null,
    say,
    tabbed = false,
    caches,
    waiting,
  }: {
    agent: Agent;
    list: Session[]; // its place's sessions and runs, any state: this agent's are shown
    automations: AutomationView[];
    edit: string; // its settings
    tags?: Snippet; // beside its name: what it is in its place (its project's default, what uses it)
    onstarted?: () => void; // a session or a run started here
    onchanged?: () => void; // the agent changed here (an improvement's attempt kept, D.21)
    partOf?: string | null; // the app it is one of the parts of (H.14): started by it, never here
    say?: string; // a chat's first message, typed in its box (Ask's "Start a chat about it")
    tabbed?: boolean; // a project's Sessions tab: the box and what it did, nothing above
    caches?: Project["caches"]; // its project's (a shared one is said in amber)
    waiting?: Snippet; // under the box: what waits for you in its place
  } = $props();

  /** The model picked for a session, made the agent's own. */
  async function makeDefault(m: ModelAccess): Promise<void> {
    await makeModelDefault(agent, m);
    onchanged?.();
  }

  let request = $state("");
  $effect(() => {
    if (say) request = say;
  });
  let model = $state<ModelAccess | undefined>(); // the model chosen; undefined: the agent's first (D.1, D.19)
  let starting = $state(false);
  let error = $state<string | null>(null);

  // where it was started, when not here
  const ORIGIN: Record<string, string> = { cli: "from the terminal", editor: "from an editor", phone: "from your phone", automation: "by an automation" };

  const isLive = (s: Session) => (s.state === "running" || s.state === "starting") && !sessions.stopping.has(s.id);
  const statusOf = (s: Session): Status => (s.pendingPermissions ? "needs-you" : s.busy ? "working" : s.state === "starting" ? "starting" : "idle");
  const chats = $derived(list.filter((s) => s.agentId === agent.id && !s.unattended && s.state !== "failed"));
  // its runs, not its checks' (D.20: shown with them)
  const runs = $derived(list.filter((s) => s.agentId === agent.id && s.unattended && s.origin !== "check"));
  const terminals = $derived(terminalsOf([agent]));

  // what it did: its sessions (open ones to open, ended ones to resume) and terminals
  const sessionEntries = $derived<TimelineEntry[]>([
    ...chats.map((s): TimelineEntry => {
      const live = isLive(s);
      const status = statusOf(s);
      const origin = ORIGIN[s.origin ?? "ui"];
      return {
        key: s.id,
        at: s.lastActivityAt,
        dot: !live ? "ended" : status === "needs-you" || status === "idle" ? status : "working",
        title: s.title ?? "untitled",
        note: [live ? STATUS_LABEL[status] : null, origin].filter(Boolean).join(" · ") || undefined,
        fact: accessLabel(s),
        action: live
          ? { label: "Open", onclick: () => open(s), primary: true, testid: "open-session" }
          : s.canResume
            ? { label: "Resume", onclick: () => open(s), testid: "resume-session" }
            : undefined,
        testid: live ? "agent-session" : "ended-session",
      };
    }),
    ...terminals.map(
      (t): TimelineEntry => ({
        key: t.conn.id,
        at: t.conn.since,
        dot: "working",
        title: "a terminal",
        note: "handler terminal",
        fact: accessLabel(t.conn.terminal),
        action: { label: "Open", href: href({ view: "terminal", agent: t.agent.id, connection: t.conn.id }), primary: true },
        testid: "live-terminal",
      }),
    ),
  ]);
  // and a job: its runs, each with its result
  const runEntries = $derived<TimelineEntry[]>(
    runs.map((r): TimelineEntry => {
      const state = runState(r);
      const verdict = verdictOf(agent.interface?.result as Schema | undefined, r.output?.value);
      return {
        key: r.id,
        at: r.createdAt,
        dot: state === "running" ? "working" : verdict && verdict.tone !== "muted" ? verdict.tone : state === "done" ? "ended" : "danger",
        title: inputSummary(r) ?? "a run",
        note: verdict?.value ?? (r.waitingFor ? "waiting for its turn" : state),
        fact: [startedBy(r), accessLabel(r)].join(" · "),
        action: { label: "Result", href: href({ view: "run", id: r.id }), testid: "run-link" },
      };
    }),
  );

  async function start(): Promise<void> {
    starting = true;
    error = null;
    try {
      const session = await sessions.start(agent, request.trim() || undefined, model);
      request = "";
      onstarted?.();
      navigate({ view: "session", key: session.key });
    } catch (e) {
      error = (e as Error).message;
    } finally {
      starting = false;
    }
  }

  function open(s: Session): void {
    navigate({ view: "session", key: sessions.open(s, agent).key });
  }

  function requestKey(e: KeyboardEvent): void {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      void start();
    }
  }
</script>

<section class="min-w-0 space-y-5" aria-label={agentLabel(agent)} data-testid="agent-panel">
  {#snippet chips()}
    {#if tabbed}<AgentChips {agent} {caches} {edit} />{/if}
  {/snippet}
  {#if !tabbed}
  <header class="flex items-start gap-3">
    <div class="min-w-0 flex-1 space-y-1.5">
      <div class="flex flex-wrap items-center gap-2">
        <h2 class="text-xl font-semibold tracking-[-0.01em]">{agentLabel(agent)}</h2>
        <UseChip use={useOfAgent(agent)} />
        {@render tags?.()}
      </div>
      {#if agent.description}<p class="text-sm text-muted-foreground">{agent.description}</p>{/if}
      <div class="flex flex-wrap items-center gap-2">
        <AgentSchedules {automations} agentId={agent.id} />
      </div>
      <InterfaceStrip iface={agent.interface} />
    </div>
    <Button variant="ghost" size="sm" href={edit} data-testid="agent-edit"><Pencil />Edit</Button>
  </header>
  {/if}
  {#if error}<p class="text-sm text-danger" data-testid="project-error">{error}</p>{/if}

  {#snippet byItsApp(app: string)}
    <p class="rounded-lg bg-muted px-4 py-3 text-sm text-muted-foreground" data-testid="agent-part-of">
      One of <a class="text-link hover:underline" href={href({ view: "apps", app })}>{app}</a>'s parts: it runs when you use {app} (what you ask it, its screen, what it runs by
      itself), never on its own here.
    </p>
  {/snippet}
  {#if agent.interface?.result}
    {#if partOf}
      {@render byItsApp(partOf)}
    {:else}
      <div class="console term-surface p-4">
        <div class="font-sans">{#key agent.id}<RunForm {agent} ondefault={makeDefault} {chips} onstarted={(run) => (onstarted?.(), navigate({ view: "run", id: run.id }))} />{/key}</div>
      </div>
    {/if}
    {#if !tabbed}
      <AgentReceipt {agent} {edit} />
    {/if}
    <AgentChecks {agent} {onchanged} />
    {#if !tabbed}<UsesPanel kind="agent" id={agent.id} />{/if}
    {@render waiting?.()}
    <section class="space-y-2">
      <h3 class="section-label">Its runs</h3>
      <Timeline entries={runEntries} empty="No run yet." />
    </section>
  {:else}
    {#if partOf}
      {@render byItsApp(partOf)}
    {:else if agent.interface}
      <div class="console term-surface p-4" data-testid="project-brief">
        <div class="font-sans">{#key agent.id}<RunForm {agent} ondefault={makeDefault} {chips} onstarted={(s) => (onstarted?.(), open(s))} />{/key}</div>
      </div>
    {:else}
      <form
        class="console term-surface"
        onsubmit={(e) => {
          e.preventDefault();
          void start();
        }}
        data-testid="project-start"
      >
        <div class="flex gap-2.5 px-4 pt-3.5">
          <span class="font-bold text-primary select-none" aria-hidden="true">›</span>
          <Textarea
            bind:value={request}
            onkeydown={requestKey}
            rows={2}
            placeholder="What should {agentLabel(agent)} do?"
            aria-label="request"
            aria-describedby="project-request-hint"
            class="min-h-14 resize-y rounded-none border-0 bg-transparent p-0 font-mono text-[13.5px] leading-[1.55] shadow-none focus-visible:ring-0 dark:bg-transparent"
            data-testid="project-request"
          />
        </div>
        <div class="console-run">
          <ModelChoice {agent} bind:value={model} ondefault={makeDefault} />
          {@render chips()}
          <span id="project-request-hint" class="ml-auto text-xs text-muted-foreground max-lg:hidden">{tabbed ? "" : "↵ to start · empty: an open chat"}</span>
          <Button type="submit" size="sm" class="max-lg:ml-auto" disabled={starting} data-testid="project-start-button"><Play />Start</Button>
        </div>
      </form>
    {/if}
    {#if !tabbed}
      <AgentReceipt {agent} {edit} />
      <UsesPanel kind="agent" id={agent.id} />
    {/if}
    {@render waiting?.()}
    <section class="space-y-2">
      {#if !tabbed}<h3 class="section-label">Its sessions</h3>{/if}
      <Timeline entries={sessionEntries} empty={agent.interface ? "No session yet: fill in the brief above." : "No session yet: say what to do above."} />
    </section>
  {/if}
</section>

<style>
  /* the start: a dark console, in the colours of the session it opens */
  .console {
    border-radius: 0.75rem;
    box-shadow: var(--float-shadow);
    overflow: hidden;
  }
  /* the session's own select style is for its terminal: here the chevron needs its room */
  .console :global(select) {
    padding: 0.25rem 2rem 0.25rem 0.625rem;
  }
  .console-run {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.75rem;
    padding: 0.5rem 0.75rem 0.625rem 1rem;
    border-top: 1px solid var(--border);
  }
</style>
