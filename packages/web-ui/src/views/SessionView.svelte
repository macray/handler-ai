<script lang="ts">
  // One chat session of the sidebar. The agent lives in the daemon and the attachment in the
  // session store, so leaving this view (to watch another agent) or reloading does not stop it.
  import ContextTag from "../components/ContextTag.svelte";
  import FolderOpen from "@lucide/svelte/icons/folder-open";
  import Globe from "@lucide/svelte/icons/globe";
  import Smartphone from "@lucide/svelte/icons/smartphone";
  import Pencil from "@lucide/svelte/icons/pencil";
  import Library from "@lucide/svelte/icons/library-big";
  import ListChecks from "@lucide/svelte/icons/list-checks";
  import Play from "@lucide/svelte/icons/play";
  import PlugZap from "@lucide/svelte/icons/plug-zap";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import Plus from "@lucide/svelte/icons/plus";
  import Workflow from "@lucide/svelte/icons/workflow";
  import Square from "@lucide/svelte/icons/square";
  import { Button } from "$lib/components/ui/button";
  import Composer from "@handler/acp-view/components/Composer.svelte";
  import { FollowEnd } from "@handler/acp-view/lib/follow";
  import PageHeader from "../components/PageHeader.svelte";
  import NetworkPanel from "../components/NetworkPanel.svelte";
  import SaveSkillPanel from "../components/SaveSkillPanel.svelte";
  import SessionFiles from "../components/SessionFiles.svelte";
  import SessionAutomationRuns from "../components/SessionAutomationRuns.svelte";
  import PermissionPrompt from "@handler/acp-view/components/PermissionPrompt.svelte";
  import SessionControls from "../components/SessionControls.svelte";
  import SessionStatus from "../components/SessionStatus.svelte";
  import Timeline from "@handler/acp-view/components/Timeline.svelte";
  import { accessLabel, sessionModel } from "../lib/access";
  import { href, navigate } from "../lib/router.svelte";
  import { LIGHT_LABEL, lightTone, remote } from "../lib/remote.svelte";
  import { agentLabel, projects } from "../lib/projects.svelte";
  import { sessions } from "../lib/sessions.svelte";
  import { api } from "../lib/api";
  import type { AutomationRun, SessionChanges } from "../lib/contracts.gen";

  let { key }: { key: string } = $props();

  const session = $derived(sessions.get(key));
  const found = $derived(session ? projects.of(session.agent) : undefined); // its project and agent
  const FILES_OPEN = "handler.files-open"; // the files pane stays open from a session to the next
  const FILES_WIDTH = "handler.files-width";
  let panel = $state<"files" | "network" | "save" | "automations" | null>(
    localStorage.getItem(FILES_OPEN) ? "files" : null,
  ); // the side panel shown
  let automationRuns = $state<AutomationRun[]>([]); // what ran on it when it stopped (I)
  const isRun = $derived(Boolean(session?.info.input)); // a run (D.18): unattended, no prompt
  const folderless = $derived(Boolean(session && !session.agent.scope)); // its own folder (D.18)
  const showNetwork = $derived(panel === "network");
  // The terminal while the agent starts or runs; stopped, failed or attached elsewhere: what
  // happened and how to go on, centred on the page.
  const running = $derived(session ? session.status !== "stopped" && session.status !== "elsewhere" : false);
  const failed = $derived(session?.info.state === "failed");

  // a session started elsewhere, or opened from a link: shown, and attached while it runs
  $effect(() => {
    if (!sessions.restored) return;
    if (session) sessions.view(session);
    else void sessions.adopt(key);
  });

  $effect(() => {
    if (!session) return;
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
    const load = () =>
      void api
        .sessionAutomationRuns(key)
        .then((found) => (automationRuns = found))
        .catch(() => {});
    load();
    const timer = setInterval(load, 10000); // they run after a stop
    return () => clearInterval(timer);
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
    loadChanges();
    const timer = setInterval(loadChanges, 10000);
    return () => clearInterval(timer);
  });

  $effect(() => {
    const conn = session?.conn;
    const done = conn?.session.entries.filter((e) => e.kind === "tool" && (e.status === "completed" || e.status === "failed")).length;
    void [done, conn?.busy];
    const timer = setTimeout(loadChanges, 800);
    return () => clearTimeout(timer);
  });

  $effect(() => {
    if (panel === "files") seen = new Set(changeKeys);
  });

  function togglePanel(which: NonNullable<typeof panel>): void {
    panel = panel === which ? null : which;
    if (panel === "files") localStorage.setItem(FILES_OPEN, "1");
    else localStorage.removeItem(FILES_OPEN);
  }

  // the files pane's left edge, dragged
  function resize(event: PointerEvent): void {
    const pane = (event.currentTarget as HTMLElement).parentElement!;
    const right = pane.getBoundingClientRect().right;
    const move = (e: PointerEvent) => (filesWidth = Math.min(Math.max(right - e.clientX, 280), window.innerWidth - 360));
    const up = () => {
      window.removeEventListener("pointermove", move);
      localStorage.setItem(FILES_WIDTH, String(Math.round(filesWidth)));
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up, { once: true });
  }

  // Follow new output (streamed text too) while the view is at its end.
  const follow = new FollowEnd();
  $effect(() => {
    const conn = session?.conn;
    const last = conn?.session.entries.at(-1);
    void [conn?.session.entries.length, last && "text" in last ? last.text.length : 0, conn?.permissions.length];
    follow.toEnd();
  });

  async function another(): Promise<void> {
    if (!session) return;
    try {
      // with the model this one ran with
      navigate({ view: "session", key: (await sessions.start(session.agent, undefined, undefined, sessionModel(session.info))).key });
    } catch (e) {
      session.error = (e as Error).message;
    }
  }

  // Remote: share this session with the paired devices (docs/dev/design/remote.md); off after a
  // stop.
  const shared = $derived(session ? remote.shared(session.key) : false);
  const remoteReady = $derived(Boolean(remote.status?.gatewayUrl));
  const remoteTitle = $derived(
    !remoteReady
      ? "To share it with your phone, set a gateway first: Settings → Remote"
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

  function end(): void {
    if (!session) return;
    const busy = session.status === "working" || session.status === "needs-you";
    const question = busy
      ? "The agent is working. End this session? Its turn is stopped, and its sandbox."
      : "End this session? Its sandbox is stopped.";
    if (!confirm(question)) return;
    const back = found ? { view: "project" as const, id: found.project.id } : { view: "home" as const };
    void sessions.close(session); // it leaves the list: read its project before
    navigate(back);
  }
</script>

{#if !session && !sessions.restored}
  <PageHeader title="Session" />
  <p class="p-6 text-sm text-muted-foreground">Loading…</p>
{:else if !session}
  <PageHeader title="Session" />
  <div class="grid flex-1 place-items-center p-6 text-center text-sm">
    <div class="space-y-3">
      <p class="text-muted-foreground">This session is not open any more.</p>
      <Button variant="outline" size="sm" href={href({ view: "home" })}>Projects</Button>
    </div>
  </div>
{:else}
  <PageHeader
    title={found ? agentLabel(found.agent) : projects.label(session.agent)}
    parent={found ? { label: found.project.name, href: href({ view: "project", id: found.project.id }) } : undefined}
  >
    {#snippet meta()}
      {#if found?.project.context}<ContextTag name={found.project.context} />{/if}
      <SessionStatus status={session.status} label />
      {#if session.info.harnessVersion}<span class="truncate text-xs text-muted-foreground max-md:hidden">{session.info.harnessVersion}</span>{/if}
    {/snippet}
    {#snippet actions()}
      {#if session.live && !remoteReady}
        <Button variant="ghost" size="sm" href={href({ view: "settings", section: "remote" })} title={remoteTitle} data-testid="remote-toggle">
          <Smartphone /><span class="max-md:sr-only">Remote</span>
        </Button>
      {:else if session.live}
        <Button
          variant={shared ? "secondary" : "ghost"}
          size="sm"
          onclick={toggleRemote}
          aria-pressed={shared}
          title={remoteTitle}
          data-testid="remote-toggle"
        >
          <Smartphone /><span class="max-md:sr-only">Remote</span>
          {#if shared}<span class="size-2 rounded-full {lightTone(remote.light)}" aria-hidden="true"></span>{/if}
        </Button>
      {/if}
      <Button
        variant={panel === "files" ? "secondary" : "ghost"}
        size="sm"
        onclick={() => togglePanel("files")}
        aria-pressed={panel === "files"}
        title={changes?.files?.length
          ? `The session's folder: ${changes.files.length} file${changes.files.length === 1 ? "" : "s"} changed since it started`
          : "The session's folder: its files, and what changed since it started"}
        data-testid="files-toggle"
      >
        <FolderOpen /><span class="max-md:sr-only">Files</span>
        {#if changes?.files?.length}<span class="text-xs text-muted-foreground tabular-nums" data-testid="files-count">{changes.files.length}</span>{/if}
        {#if unseen}<span class="size-2 rounded-full bg-primary" aria-label="new changes"></span>{/if}
      </Button>
      <Button variant={showNetwork ? "secondary" : "ghost"} size="sm" onclick={() => togglePanel("network")} aria-pressed={showNetwork}>
        <Globe /><span class="max-md:sr-only">Network</span>
      </Button>
      {#if automationRuns.length}
        <Button
          variant={panel === "automations" ? "secondary" : "ghost"}
          size="sm"
          onclick={() => togglePanel("automations")}
          aria-pressed={panel === "automations"}
          title="The automations that ran on this conversation"
          data-testid="session-automations-toggle"
        >
          <Workflow /><span class="max-md:sr-only">Automations</span>
        </Button>
      {/if}
      {#if isRun}
        <Button variant="ghost" size="sm" href={href({ view: "run", id: session.key })} title="What it was given and what it gave back" data-testid="session-run">
          <ListChecks /><span class="max-md:sr-only">Run</span>
        </Button>
      {/if}
      {#if folderless && !isRun}
        <Button
          variant={panel === "save" ? "secondary" : "ghost"}
          size="sm"
          onclick={() => togglePanel("save")}
          aria-pressed={panel === "save"}
          title="The skill in this session's folder, into your library"
          data-testid="save-skill-toggle"
        >
          <Library /><span class="max-md:sr-only">Save to library</span>
        </Button>
      {/if}
      {#if found}
        <Button variant="ghost" size="sm" href={href({ view: "edit-agent", project: found.project.id, id: found.agent.id })} title="The agent's settings">
          <Pencil /><span class="max-md:sr-only">Agent</span>
        </Button>
      {:else}
        <Button variant="ghost" size="sm" href={href({ view: "agent", id: session.agent.id })} title="The agent's page">
          <Pencil /><span class="max-md:sr-only">Agent</span>
        </Button>
      {/if}
      {#if !isRun}
        <Button variant="ghost" size="sm" onclick={another} title="Another session with the same agent (its own sandbox)">
          <Plus /><span class="max-md:sr-only">New session here</span>
        </Button>
      {/if}
      <Button variant="ghost" size="sm" onclick={end} title="End the session and stop its sandbox" data-testid="end-session">
        <Square /><span class="max-md:sr-only">End session</span>
      </Button>
    {/snippet}
  </PageHeader>
  <div
    class="session"
    class:with-network={panel !== null && panel !== "files"}
    class:with-files={panel === "files"}
    style:--files-width={filesWidth ? `${filesWidth}px` : null}
  >
    {#if running}
      <div class="term term-surface">
        <header class="titlebar">
          <span class="lights" aria-hidden="true"><i></i><i></i><i></i></span>
          <span class="name" title={session.agent.scope}>{session.title ?? session.agent.scope}</span>
        </header>

        <div class="screen" {@attach follow.attach}>
          {#if session.conn}
            <Timeline session={session.conn.session} />
          {:else}
            <p class="text-muted-foreground">Starting a sandbox for {accessLabel(session.info)}…</p>
          {/if}

          {#if session.lastStop}<p class="text-muted-foreground">── turn ended: {session.lastStop} ──</p>{/if}
          {#if session.error}<p class="text-danger" data-testid="error">✗ {session.error}</p>{/if}
        </div>

        {#if session.conn?.permissions.length}
          <div class="asks" data-testid="pinned-permissions">
            {#each session.conn.permissions as pending (pending.request.toolCall.toolCallId)}
              <PermissionPrompt {pending} />
            {/each}
          </div>
        {/if}

        {#if session.live && session.conn && isRun}
          <footer>
            <p class="text-sm text-muted-foreground" data-testid="run-note">
              An unattended run: it takes no prompt. <a class="text-link hover:underline" href={href({ view: "run", id: session.key })}>Its result</a>
            </p>
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
            />
            <SessionControls conn={session.conn} harness={session.info.harness} />
          </footer>
        {/if}
      </div>
    {:else}
      <div class="grid min-h-0 place-items-center overflow-y-auto p-6" data-testid="closed">
        <div class="flex w-full max-w-lg flex-col items-center gap-4 text-center">
          <span class="grid size-11 place-items-center rounded-full {session.error || failed ? 'bg-danger/10 text-danger' : 'bg-accent-soft text-accent-soft-foreground'}">
            {#if session.error || failed}<TriangleAlert class="size-5" />{:else if session.status === "elsewhere"}<PlugZap class="size-5" />{:else}<Play class="size-5" />{/if}
          </span>
          {#if session.status === "elsewhere"}
            <div class="space-y-1.5">
              <h2 class="text-base font-semibold">Open in other tabs</h2>
              <p class="text-sm text-muted-foreground">
                Too many clients were attached to this session, so this tab was detached. The agent keeps running.
              </p>
            </div>
          {:else if failed}
            <div class="space-y-1.5">
              <h2 class="text-base font-semibold">The session failed</h2>
              <p class="text-sm text-muted-foreground">Its agent stopped with an error. Start a new session with it, or stop this one.</p>
            </div>
          {:else}
            <div class="space-y-1.5">
              <h2 class="text-base font-semibold">The agent is stopped</h2>
              <p class="text-sm text-muted-foreground">
                {session.conn?.closed?.reason ? `${session.conn.closed.reason}. ` : ""}Resuming restarts it in a new sandbox and continues this
                conversation.
              </p>
            </div>
          {/if}
          {#if session.error}
            <pre
              class="w-full rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-left text-xs whitespace-pre-wrap text-danger [overflow-wrap:anywhere]"
              data-testid="error">{session.error}</pre>
          {/if}
          {#if session.status === "elsewhere"}
            <Button onclick={() => sessions.connect(session)} data-testid="reconnect">Reattach</Button>
          {:else if failed}
            <Button onclick={another}><Plus />New session</Button>
          {:else}
            <Button onclick={() => sessions.connect(session)} data-testid="reconnect"><Play />Resume</Button>
          {/if}
        </div>
      </div>
    {/if}

    {#if panel === "files"}
      <aside class="files">
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <div class="grip" onpointerdown={resize} title="Drag to resize"></div>
        <SessionFiles sessionId={session.key} folder={session.info.scope} {changes} onclose={() => togglePanel("files")} />
      </aside>
    {:else if showNetwork}
      <aside><NetworkPanel agent={session.agent} session={session.info} onchange={(r) => sessions.updateAgent(r)} /></aside>
    {:else if panel === "save"}
      <aside><SaveSkillPanel sessionId={session.key} /></aside>
    {:else if panel === "automations"}
      <aside><SessionAutomationRuns runs={automationRuns} /></aside>
    {/if}
  </div>
{/if}

<style>
  .session {
    flex: 1;
    min-height: 0;
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 0.75rem;
    padding: 0.75rem;
  }
  .session.with-network {
    grid-template-columns: minmax(0, 1fr) 300px;
  }
  .session.with-files {
    grid-template-columns: minmax(0, 1fr) var(--files-width, min(42%, 720px));
  }
  .term {
    display: flex;
    flex-direction: column;
    min-height: 0;
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
  }
  .titlebar {
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    height: 2.1rem;
    padding: 0 0.75rem;
    background: var(--card);
    border-bottom: 1px solid var(--border);
    min-width: 0;
  }
  .lights {
    position: absolute;
    left: 0.75rem;
    display: flex;
    gap: 6px;
  }
  .lights i {
    width: 11px;
    height: 11px;
    border-radius: 50%;
    background: #ff5f57;
  }
  .lights i:nth-child(2) {
    background: #febc2e;
  }
  .lights i:nth-child(3) {
    background: #28c840;
  }
  .name {
    color: var(--muted-foreground);
    font-size: 0.85em;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: calc(100% - 10rem);
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
  .asks {
    padding: 0 1rem;
    max-height: 50%;
    overflow-y: auto;
    flex: none;
  }
  footer {
    padding: 0.6rem 1rem 0.5rem;
    border-top: 1px solid var(--border);
    background: var(--background);
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }
  footer :global(.controls) {
    font-size: max(0.9em, 12px);
    color: var(--muted-foreground);
  }
  aside {
    overflow-y: auto;
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1rem;
    background: var(--card);
  }
  aside.files {
    position: relative;
    padding: 0;
    overflow: hidden;
  }
  .grip {
    position: absolute;
    inset: 0 auto 0 0;
    width: 6px;
    cursor: col-resize;
    z-index: 1;
  }
  .grip:hover {
    background: var(--border);
  }
  @media (max-width: 900px) {
    .session.with-network {
      grid-template-columns: 1fr;
    }
    .session.with-files {
      grid-template-columns: 1fr;
    }
    aside.files {
      position: fixed;
      inset: 0;
      z-index: 40;
      border-radius: 0;
    }
    .grip {
      display: none;
    }
  }
</style>
