<script lang="ts">
  // One automation (contract I): what it does in words, its files (read here, edited in your
  // editor), its problems and warnings, a try, on and off (turning it on is your approval), its
  // runs; Change (the form, for one it can say) and Delete (its folder and its runs, confirmed).
  import { Button } from "$lib/components/ui/button";
  import * as Card from "$lib/components/ui/card";
  import * as NativeSelect from "$lib/components/ui/native-select";
  import PageHeader from "../components/PageHeader.svelte";
  import RefusedHosts from "../components/RefusedHosts.svelte";
  import StatusBadge from "../components/StatusBadge.svelte";
  import When from "../components/When.svelte";
  import { api } from "../lib/api";
  import { ended, formOf, missedSentence, onSchedule, RUN_STATE, usage } from "../lib/automations";
  import Pencil from "@lucide/svelte/icons/pencil";
  import Trash from "@lucide/svelte/icons/trash-2";
  import type { AutomationRun, AutomationView, Session } from "../lib/contracts.gen";
  import { decideHosts, projects } from "../lib/projects.svelte";
  import { href, navigate } from "../lib/router.svelte";

  let { name }: { name: string } = $props();

  let view = $state<AutomationView | null>(null);
  let runs = $state<AutomationRun[]>([]);
  let stopped = $state<Session[]>([]); // what a try can run on
  let known = $state<Session[]>([]); // the sessions handlerd still lists: a run names its session by them
  let error = $state<string | null>(null);
  let busy = $state(false);
  let file = $state<{ path: string; text: string } | null>(null);
  let logs = $state<Record<string, string>>({});
  let trySession = $state("");
  let trial = $state<AutomationRun | null>(null); // the try started here, followed

  async function load(): Promise<void> {
    try {
      [view, runs] = await Promise.all([api.automation(name), api.automationRuns(name)]);
      if (trial) trial = runs.find((r) => r.id === trial?.id) ?? trial;
      error = null;
    } catch (e) {
      error = (e as Error).message;
    }
  }

  async function loadSessions(): Promise<void> {
    const all = await api.sessions();
    known = all;
    stopped = all
      .filter((s) => s.state === "stopped" && !s.unattended)
      .sort((a, b) => Date.parse(b.lastActivityAt) - Date.parse(a.lastActivityAt));
    trySession ||= stopped[0]?.id ?? "";
  }

  $effect(() => {
    void load();
    void loadSessions().catch(() => {});
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
  });

  async function act(action: () => Promise<unknown>): Promise<void> {
    busy = true;
    error = null;
    try {
      await action();
      await load();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  let confirming = $state(false); // "Turn on" asked: what it does is shown with the last word
  let deleting = $state(false); // "Delete" asked: what goes is said first

  async function remove(): Promise<void> {
    busy = true;
    error = null;
    try {
      await api.deleteAutomation(name);
      navigate({ view: "automations" }, true);
    } catch (e) {
      error = (e as Error).message;
      busy = false;
    }
  }

  function turnOn(): void {
    confirming = false;
    void act(() => api.enableAutomation(name));
  }

  function trySessionId(): string | undefined {
    return view && onSchedule(view.definition) ? undefined : trySession;
  }

  async function showFile(path: string): Promise<void> {
    if (file?.path === path) {
      file = null;
      return;
    }
    try {
      file = { path, text: await api.automationFile(name, path) };
    } catch (e) {
      error = (e as Error).message;
    }
  }

  async function toggleLog(run: AutomationRun): Promise<void> {
    if (logs[run.id] !== undefined) {
      delete logs[run.id];
      return;
    }
    try {
      logs[run.id] = await api.automationRunLog(name, run.id);
    } catch (e) {
      error = (e as Error).message;
    }
  }

  function sessionLabel(s: Session): string {
    const project = s.projectId ? projects.get(s.projectId)?.name : undefined;
    return `${s.title ?? "untitled"} · ${project ?? "outside projects"}`;
  }
</script>

<PageHeader width="max-w-4xl" title={name} parent={{ label: "Library › Automations", href: href({ view: "automations" }) }}>
  {#snippet meta()}
    {#if view}<StatusBadge status={view.enabled ? "on" : "off"} />{/if}
  {/snippet}
  {#snippet actions()}
    {#if view && formOf(view.definition)}
      <Button size="sm" variant="ghost" href={href({ view: "edit-automation", name })} data-testid="automation-edit"><Pencil />Change</Button>
    {/if}
    {#if view}
      <Button size="sm" variant="ghost" class="text-destructive hover:text-destructive" disabled={busy || deleting} onclick={() => (deleting = true)} data-testid="automation-delete">
        <Trash />Delete
      </Button>
    {/if}
    {#if view?.enabled}
      <Button size="sm" variant="outline" disabled={busy} onclick={() => act(() => api.disableAutomation(name))} data-testid="automation-off">Turn off</Button>
    {:else if view}
      <Button size="sm" disabled={busy || confirming || !view.definition || !!view.problems?.length} onclick={() => (confirming = true)} data-testid="automation-on">Turn on</Button>
    {/if}
  {/snippet}
</PageHeader>
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-4xl space-y-6 px-8 py-10">
        {#if error}<p class="text-sm text-danger" data-testid="automation-error">{error}</p>{/if}

    {#if view && deleting}
      <div class="space-y-2 rounded-md border border-danger/30 bg-danger/5 p-3 text-sm" role="alertdialog" aria-labelledby="delete-title" data-testid="automation-confirm-delete">
        <p id="delete-title" class="font-medium">Delete {name}?</p>
        <ul class="list-disc space-y-0.5 pl-5 text-muted-foreground">
          <li>Its folder, with every file in it: <code class="text-xs">{view.directory}</code></li>
          <li>Its {runs.length} run{runs.length === 1 ? "" : "s"} and their logs. What it told your inbox stays.</li>
          {#if view.enabled || view.pending}<li>It stops now{#if runs.some((r) => !ended(r))}: its run in progress is cancelled{/if}.</li>{/if}
        </ul>
        <div class="flex gap-2">
          <Button size="sm" variant="destructive" disabled={busy} onclick={remove} data-testid="automation-confirm-delete-button">Delete</Button>
          <Button size="sm" variant="ghost" onclick={() => (deleting = false)}>Cancel</Button>
        </div>
      </div>
    {/if}

    {#if view}
      {#if view.problems?.length}
        <div class="rounded-md border border-danger/30 bg-danger/5 p-3 text-sm" data-testid="automation-problems">
          <p class="font-medium text-danger">It cannot run until these are fixed in its files:</p>
          <ul class="mt-1 list-disc pl-5 text-danger">
            {#each view.problems as p (p)}<li>{p}</li>{/each}
          </ul>
        </div>
      {/if}
      {#if view.warnings?.length}
        <div class="rounded-md border border-warn/40 bg-warn/5 p-3 text-sm" data-testid="automation-warnings">
          {#each view.warnings as w (w)}<p>{w}</p>{/each}
        </div>
      {/if}

      <Card.Root data-testid="automation-permissions">
        <Card.Header>
          <Card.Title>What it does</Card.Title>
          <Card.Description>
            {view.enabled ? "On: you turned it on. Your edits of its files apply at its next run." : "Off. Turning it on is your approval of this."}
          </Card.Description>
        </Card.Header>
        <Card.Content class="space-y-2 text-sm">
          {#if view.permissions?.length}
            <ul class="space-y-0.5">
              {#each view.permissions as line (line)}
                <li>{#each line.split("`") as part, i (i)}{#if i % 2}<code class="rounded bg-muted px-1 text-xs">{part}</code>{:else}{part}{/if}{/each}</li>
              {/each}
            </ul>
            {#if view.nextAt}<p class="text-muted-foreground" data-testid="automation-next">Next run <When at={view.nextAt} />.</p>{/if}
            {#if confirming && !view.enabled}
              <div class="space-y-2 rounded-md border border-warn/40 bg-warn/5 p-3" role="alertdialog" aria-labelledby="turn-on-title" data-testid="automation-confirm-on" {@attach (el) => el.scrollIntoView({ block: "center", behavior: "smooth" })}>
                <p id="turn-on-title" class="font-medium">Turn {name} on? It will do what is said above{view.warnings?.length ? ", with the warning above" : ""}.</p>
                <p class="text-xs text-muted-foreground">
                  {onSchedule(view.definition) ? "Its first run is at its next time, not now." : "Only sessions that stop from now on are read."}
                </p>
                <div class="flex gap-2">
                  <Button size="sm" disabled={busy} onclick={turnOn} data-testid="automation-confirm-on-button">Turn on</Button>
                  <Button size="sm" variant="ghost" onclick={() => (confirming = false)}>Cancel</Button>
                </div>
              </div>
            {/if}
            {#if view.definition?.services?.llm?.length}
              <p class="text-xs text-muted-foreground">
                Its script's models are those of your providers (an API key or a local server), never a subscription. Handler calls them for
                the script; the key never enters its sandbox.
              </p>
            {/if}
          {:else}
            <p class="text-muted-foreground">Its automation.toml cannot be read (see the problems above).</p>
          {/if}
        </Card.Content>
      </Card.Root>

      <Card.Root>
        <Card.Header>
          <Card.Title>Files</Card.Title>
          <Card.Description>
            Edit them in your editor, in <code class="select-all" data-testid="automation-directory">{view.directory}</code>{#if formOf(view.definition)},
              or with <a class="text-link hover:underline" href={href({ view: "edit-automation", name })}>Change</a>{/if}.
          </Card.Description>
        </Card.Header>
        <Card.Content class="space-y-2">
          <div class="flex flex-wrap gap-1.5">
            {#each view.files ?? [] as f (f)}
              <Button size="sm" variant={file?.path === f ? "secondary" : "outline"} class="font-mono text-xs" onclick={() => showFile(f)} data-testid="automation-file">{f}</Button>
            {/each}
          </div>
          {#if file}
            <pre class="max-h-96 overflow-auto rounded-md bg-muted p-3 text-xs whitespace-pre-wrap" data-testid="automation-file-text">{file.text}</pre>
          {/if}
        </Card.Content>
      </Card.Root>

      <Card.Root>
        <Card.Header>
          <Card.Title>Try it</Card.Title>
          <Card.Description>
            {#if onSchedule(view.definition)}
              Runs it now, on or off. A script's try adds nothing to your notes: it shows what it would add. An agent's run is a real run: its result comes to your inbox.
            {:else}
              Runs it now on a session's whole conversation, on or off. It adds nothing to your notes: it shows what it would add.
            {/if}
          </Card.Description>
        </Card.Header>
        <Card.Content class="space-y-3 text-sm">
          {#if onSchedule(view.definition)}
            <Button variant="outline" disabled={busy || !!view.problems?.length || (trial !== null && !ended(trial))} onclick={() => act(async () => (trial = await api.tryAutomation(name)))} data-testid="automation-try">Try now</Button>
          {:else if stopped.length}
            <form class="flex flex-wrap items-center gap-2" onsubmit={(e) => (e.preventDefault(), act(async () => (trial = await api.tryAutomation(name, trySessionId()))))}>
              <NativeSelect.Root class="w-96 max-w-full" bind:value={trySession} aria-label="session" data-testid="automation-try-session">
                {#each stopped as s (s.id)}<NativeSelect.Option value={s.id}>{sessionLabel(s)}</NativeSelect.Option>{/each}
              </NativeSelect.Root>
              <Button type="submit" variant="outline" disabled={busy || !trySession || !!view.problems?.length || (trial !== null && !ended(trial))} data-testid="automation-try">Try</Button>
            </form>
          {:else}
            <p class="text-muted-foreground">No stopped session to try it on yet.</p>
          {/if}
          {#if trial}
            <div class="space-y-2 rounded-md border p-3" data-testid="automation-trial">
              <p>
                <StatusBadge status={RUN_STATE[trial.state]} /> {usage(trial)}{#if trial.error}<span class="text-danger"> · {trial.error}</span>{/if}
                {#if trial.agentSessionId}<a class="text-link hover:underline" href={href({ view: "session", key: trial.agentSessionId })}>the agent's run</a>{/if}
              </p>
              {#each trial.appended ?? [] as a (a.to)}
                <p class="text-xs text-muted-foreground">Would add {a.bytes} bytes to <code>{a.to}</code>:</p>
                <pre class="max-h-64 overflow-auto rounded-md bg-muted p-2 text-xs whitespace-pre-wrap">{a.text}</pre>
              {:else}
                {#if trial.state === "succeeded"}<p class="text-xs text-muted-foreground">It would add nothing.</p>{/if}
              {/each}
            </div>
          {/if}
        </Card.Content>
      </Card.Root>

      <section class="space-y-2">
        <h2 class="text-base font-semibold">Runs</h2>
        {#if view.pending || view.capped}
          <p class="text-sm text-muted-foreground">
            {#if view.pending}{view.pending} run{view.pending === 1 ? "" : "s"} waiting{#if view.behind}, behind {view.behind} (one run at a time){/if}.{/if}
            {#if view.capped}<span class="text-warn">It ran 100 times today: the next runs wait until tomorrow.</span>{/if}
          </p>
        {/if}
        <ul class="divide-y rounded-lg border bg-card text-sm" data-testid="automation-runs">
          {#each runs as run (run.id)}
            {@const session = known.find((s) => s.id === run.sessionId)}
            <li class="space-y-1 px-4 py-2" data-testid="automation-run">
              <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
                <StatusBadge status={RUN_STATE[run.state]} />
                {#if run.trial}<span class="text-xs text-muted-foreground">a try</span>{/if}
                {#if run.sessionId}
                  <span class="text-xs" title={`session ${run.sessionId}, events ${run.seqFrom}–${run.seqTo}`}>
                    {#if session}<a class="text-link hover:underline" href={href({ view: "session", key: session.id })}>{sessionLabel(session)}</a>{:else}a session no longer listed{/if}
                  </span>
                {/if}
                {#if run.slot}<span class="text-xs">for <When at={run.slot} /></span>{/if}
                {#if run.agentSessionId}<a class="text-xs text-link hover:underline" href={href({ view: "session", key: run.agentSessionId })}>the agent's run</a>{/if}
                {#if usage(run)}<span class="text-xs text-muted-foreground">{usage(run)}</span>{/if}
                {#each run.appended ?? [] as a (a.to)}
                  <span class="text-xs text-muted-foreground">{run.trial ? "would add" : "added"} to <code>{a.to}</code></span>
                {/each}
                <span class="ml-auto text-xs text-muted-foreground"><When at={run.createdAt} /></span>
                {#if !ended(run)}
                  <Button size="sm" variant="ghost" onclick={() => act(() => api.cancelAutomationRun(name, run.id))}>Cancel</Button>
                {/if}
                {#if typeof view.definition?.run === "string"}
                  <Button size="sm" variant="ghost" onclick={() => toggleLog(run)}>{logs[run.id] === undefined ? "Log" : "Hide log"}</Button>
                {/if}
              </div>
              {#if missedSentence(run)}<p class="text-xs text-warn" data-testid="automation-run-missed">{missedSentence(run)}.</p>{/if}
              {#if run.error}<p class="text-xs text-danger">{run.error}</p>{/if}
              {#if run.refused?.length && view.agentId}
                {@const agentId = view.agentId}
                <RefusedHosts
                  hosts={run.refused}
                  said={run.said}
                  completed={run.state === "succeeded"}
                  {busy}
                  again="Allow and run again"
                  onallow={(hosts) => act(async () => (trial = await api.tryAutomation(name, run.sessionId ?? undefined, hosts)))}
                  onkeep={(hosts) => act(() => decideHosts(agentId, hosts, "blocked"))}
                />
              {/if}
              {#if logs[run.id] !== undefined}
                <pre class="max-h-80 overflow-auto rounded-md bg-muted p-3 text-xs whitespace-pre-wrap">{logs[run.id] || "(no output)"}</pre>
              {/if}
            </li>
          {:else}
            <li class="px-4 py-6 text-center text-muted-foreground">No run yet.</li>
          {/each}
        </ul>
      </section>
    {/if}
  </div>
</div>
