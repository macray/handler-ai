<script lang="ts">
  // An app's Activity (its page's first tab, apps design): what it did, newest first, headed by
  // day, in one list: its jobs' runs (H.11, each opening its run's page), the changes to each
  // folder it writes (D.5, NotesChange: its files and lines, Undo), what it sent you (its nudges,
  // H.17, and messages, from the Inbox's last ones), and its versions deployed; a filter for each,
  // and Problems (a failed run, the app failing to start). Its log (what its code printed) opens
  // from the top and from a problem. Read again every few seconds, as the page.
  import Bell from "@lucide/svelte/icons/bell";
  import Check from "@lucide/svelte/icons/check";
  import FileText from "@lucide/svelte/icons/file-text";
  import Play from "@lucide/svelte/icons/play";
  import Repeat from "@lucide/svelte/icons/repeat";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import Upload from "@lucide/svelte/icons/upload";
  import History from "@lucide/svelte/icons/history";
  import { Button } from "$lib/components/ui/button";
  import Dialog from "./Dialog.svelte";
  import NotesChange from "./NotesChange.svelte";
  import StatusBadge from "./StatusBadge.svelte";
  import { onChange } from "../lib/events.svelte";
  import { api, ApiError } from "../lib/api";
  import type { App, AppRun, InboxMessage, NotesCommit } from "../lib/contracts.gen";
  import { clockTime, dayOf, exactTime } from "../lib/agents";
  import { appTitle, startedByWords } from "../lib/apps";
  import { fieldsSummary } from "../lib/runs";
  import { href } from "../lib/router.svelte";

  let { app: a, runs }: { app: App; runs: AppRun[] } = $props();

  type Folder = { path: string; label: string };
  type Entry =
    | { kind: "run"; at: string; run: AppRun }
    | { kind: "change"; at: string; commit: NotesCommit; folder: Folder }
    | { kind: "sent"; at: string; message: InboxMessage }
    | { kind: "deployed"; at: string; version: string; before?: string }
    | { kind: "down"; at: string; error: string };
  type Filter = "all" | "runs" | "changes" | "sent" | "problems";
  const FILTERS: { id: Filter; label: string }[] = [
    { id: "all", label: "All" },
    { id: "runs", label: "Runs" },
    { id: "changes", label: "Changes to your files" },
    { id: "sent", label: "Sent to you" },
    { id: "problems", label: "Problems" },
  ];
  const SHOWN = 40; // entries before "Show older"
  const RUN_STATE: Record<string, string> = { waiting: "waiting", running: "running", succeeded: "succeeded", failed: "failed", cancelled: "cancelled" };
  const NUDGE_STATE: Record<string, string> = { open: "waiting for you", done: "done", dismissed: "dismissed", expired: "gone" };

  // the folders it writes, each named by what it is for (the path in its tooltip)
  const folders = $derived<Folder[]>(
    (a.files ?? [])
      .filter((f) => f.mode === "rw" && f.path && !f.file)
      .map((f) => ({ path: f.path!, label: (f.description ?? f.name).replace(/\.$/, "") })),
  );
  let changes = $state<{ commit: NotesCommit; folder: Folder }[]>([]);
  let sent = $state<InboxMessage[]>([]);
  let filter = $state<Filter>("all");
  let all = $state(false);
  let told = $state<string | null>(null);
  let error = $state<string | null>(null);
  let log = $state<string | null>(null);
  let logOpen = $state(false);

  async function load(): Promise<void> {
    try {
      const histories = await Promise.all(
        folders.map((f) =>
          api.notesHistory(f.path).then(
            (h) => h.commits.filter((c) => c.kind !== "first").map((commit) => ({ commit, folder: f })),
            (e) => (e instanceof ApiError && e.status === 404 ? [] : Promise.reject(e)),
          ),
        ),
      );
      changes = histories.flat();
      sent = (await api.inbox()).filter((m) => m.source === "app" && (m.app ?? m.name) === a.name);
      error = null;
    } catch (e) {
      error = (e as Error).message;
    }
  }

  $effect(() => {
    void folders;
    void load();
    return onChange(["apps", "sessions", "inbox", "automations"], () => void load());
  });

  async function showLog(): Promise<void> {
    logOpen = true;
    try {
      log = (await api.appLog(a.name)).text;
    } catch (e) {
      log = (e as Error).message;
    }
  }

  const failed = (r: AppRun): boolean => r.state === "failed" || !!r.error || !!r.thenError;

  const entries = $derived.by<Entry[]>(() => {
    const out: Entry[] = [
      ...runs.map((run) => ({ kind: "run" as const, at: run.at, run })),
      ...changes.map((c) => ({ kind: "change" as const, at: c.commit.at, ...c })),
      ...sent.map((message) => ({ kind: "sent" as const, at: message.at, message })),
    ];
    if (a.current) out.push({ kind: "deployed", at: a.current.deployedAt, version: a.current.version, before: a.previous?.version });
    if (a.previous) out.push({ kind: "deployed", at: a.previous.deployedAt, version: a.previous.version });
    if (a.state === "failed" && a.error) out.push({ kind: "down", at: new Date().toISOString(), error: a.error });
    return out.sort((x, y) => Date.parse(y.at) - Date.parse(x.at));
  });

  const kept = $derived(
    entries.filter((e) =>
      filter === "all"
        ? true
        : filter === "runs"
          ? e.kind === "run"
          : filter === "changes"
            ? e.kind === "change"
            : filter === "sent"
              ? e.kind === "sent"
              : e.kind === "down" || (e.kind === "run" && failed(e.run)),
    ),
  );
  const shown = $derived(all ? kept : kept.slice(0, SHOWN));

  // the entries in runs of one day, for their headings
  const days = $derived(
    shown.reduce<{ day: string; entries: Entry[] }[]>((out, e) => {
      const day = dayOf(e.at);
      if (out.at(-1)?.day === day) out.at(-1)!.entries.push(e);
      else out.push({ day, entries: [e] });
      return out;
    }, []),
  );

  function took(r: AppRun): string | null {
    if (!r.endedAt) return null;
    const s = Math.max(0, Math.round((Date.parse(r.endedAt) - Date.parse(r.at)) / 1000));
    return s < 60 ? `${s} s` : s < 3600 ? `${Math.round(s / 60)} min` : `${Math.round(s / 360) / 10} h`;
  }
  function runSummary(r: AppRun): string | null {
    const result = r.result as { summary?: unknown } | null | undefined;
    return typeof result?.summary === "string" ? result.summary : null;
  }
  const job = (r: AppRun): string => a.jobs?.find((j) => j.name === r.job)?.description ?? r.job;
</script>

<section class="space-y-3" data-testid="app-activity">
  <div class="flex flex-wrap items-center gap-2">
    <div class="inline-flex rounded-lg border bg-muted p-0.5 text-[13px]" role="tablist" aria-label="what to show">
      {#each FILTERS as f (f.id)}
        <button
          type="button"
          role="tab"
          aria-selected={filter === f.id}
          class="cursor-pointer rounded-md px-2.5 py-1 {filter === f.id ? 'bg-card font-medium shadow-sm' : 'text-muted-foreground hover:text-foreground'}"
          onclick={() => ((filter = f.id), (all = false))}
          data-testid="app-activity-filter-{f.id}">{f.label}</button
        >
      {/each}
    </div>
    <Button variant="ghost" size="sm" class="ml-auto text-muted-foreground" onclick={showLog} data-testid="app-log-toggle"><FileText />Its log</Button>
  </div>
  {#if error}<p class="text-sm text-danger" data-testid="app-activity-error">{error}</p>{/if}
  {#if told}<p class="flex items-center gap-1.5 text-sm text-ok" data-testid="notes-history-told"><Check class="size-4" />{told}</p>{/if}

  {#if !entries.length}
    <div class="flex flex-col items-center gap-2 rounded-[10px] border border-dashed px-6 py-10 text-center text-muted-foreground" data-testid="app-activity-none">
      <History class="size-5" />
      <p>
        <b class="font-medium text-foreground">Nothing yet.</b> What it does shows here: its runs, what it sends you{#if folders.length}, and the changes to {folders
            .map((f) => f.label)
            .join(", ")}, each one undoable{/if}.
      </p>
    </div>
  {:else if !shown.length}
    <p class="rounded-[10px] border border-dashed px-4 py-3 text-muted-foreground" data-testid="app-activity-none">Nothing of this kind{filter === "problems" ? ": no problem" : ""}.</p>
  {:else}
    <div class="overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
      {#each days as d (d.day)}
        <h3 class="border-b bg-muted/40 px-4 py-1.5 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{d.day}</h3>
        <ul class="divide-y border-b last:border-b-0">
          {#each d.entries as e (e.kind === "run" ? `r${e.run.id}` : e.kind === "change" ? `c${e.folder.path}${e.commit.id}` : e.kind === "sent" ? `s${e.message.id}` : `${e.kind}${e.at}`)}
            <li data-testid="app-activity-entry" data-kind={e.kind}>
              {#if e.kind === "run"}
                {@const r = e.run}
                {@const summary = runSummary(r)}
                {@const asked = fieldsSummary(r.fields)}
                <div data-testid="app-run" data-state={r.state}>
                <a class="flex items-start gap-2 px-4 py-2.5 text-foreground no-underline hover:bg-muted/40 {failed(r) ? 'bg-danger/5' : ''}" href={href({ view: "run", id: r.sessionId })}>
                  {#if r.startedBy.by === "automation"}<Repeat class="mt-0.5 size-4 shrink-0 text-muted-foreground" />{:else}<Play class="mt-0.5 size-4 shrink-0 text-muted-foreground" />{/if}
                  <span class="min-w-0 flex-1 space-y-0.5">
                    <span class="block truncate"><span class="font-medium">{job(r)}</span> <span class="text-muted-foreground">· by {startedByWords(r)} · <span title={exactTime(r.at)}>{clockTime(r.at)}</span></span></span>
                    {#if asked}<span class="block truncate text-xs text-muted-foreground" title={asked} data-testid="app-run-fields">{asked}</span>{/if}
                    {#if r.state === "waiting"}
                      <span class="block text-xs text-muted-foreground" data-testid="app-run-waiting">Waits for the run writing its folder: runs writing a folder take turns.</span>
                    {:else if r.error}
                      <span class="block text-xs text-danger" data-testid="app-run-error">{r.error}</span>
                    {:else if summary}
                      <span class="block truncate text-xs text-muted-foreground" title={summary}>{summary}</span>
                    {/if}
                    {#if r.thenError}<span class="block text-xs text-warn" data-testid="app-run-then-error">{appTitle(a)} was not told it ended: {r.thenError}</span>{/if}
                  </span>
                  <span class="flex shrink-0 items-center gap-2">
                    {#if took(r)}<span class="fact">{took(r)}</span>{/if}
                    <StatusBadge status={RUN_STATE[r.state] ?? r.state} />
                  </span>
                </a>
                </div>
              {:else if e.kind === "change"}
                <NotesChange folder={e.folder.path} commit={e.commit} where={e.folder.label} clock ondone={(t) => ((told = t), void load())} />
              {:else if e.kind === "sent"}
                {@const m = e.message}
                <a class="flex items-start gap-2 px-4 py-2.5 text-foreground no-underline hover:bg-muted/40" href={href({ view: "inbox" })} data-testid="app-activity-sent">
                  <Bell class="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                  <span class="min-w-0 flex-1 space-y-0.5">
                    <span class="block truncate"
                      ><span class="font-medium">{m.kind === "nudge" ? "Nudge: " : ""}{m.title}</span>
                      <span class="text-muted-foreground">· sent <span title={exactTime(m.at)}>{clockTime(m.at)}</span></span></span
                    >
                    {#if m.summary}<span class="block truncate text-xs text-muted-foreground">{m.summary}</span>{/if}
                  </span>
                  {#if m.nudge?.state}<span class="shrink-0 rounded-md bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">{NUDGE_STATE[m.nudge.state] ?? m.nudge.state}</span>{/if}
                </a>
              {:else if e.kind === "deployed"}
                <p class="flex items-start gap-2 px-4 py-2.5">
                  <Upload class="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                  <span class="min-w-0 flex-1"
                    ><span class="font-medium">{e.before ? `${e.before} → ${e.version}` : `${e.version} deployed`}</span>
                    <span class="text-muted-foreground">· <span title={exactTime(e.at)}>{clockTime(e.at)}</span></span></span
                  >
                </p>
              {:else}
                <p class="flex items-start gap-2 bg-danger/5 px-4 py-2.5" data-testid="app-activity-down">
                  <TriangleAlert class="mt-0.5 size-4 shrink-0 text-danger" />
                  <span class="min-w-0 flex-1"><span class="font-medium">It cannot start</span> <span class="text-muted-foreground">· {e.error}</span></span>
                  <button type="button" class="shrink-0 cursor-pointer text-xs text-link hover:underline" onclick={showLog}>Its log</button>
                </p>
              {/if}
            </li>
          {/each}
        </ul>
      {/each}
    </div>
    {#if !all && kept.length > shown.length}
      <Button variant="ghost" size="sm" onclick={() => (all = true)} data-testid="app-activity-older">Show older</Button>
    {/if}
  {/if}
</section>

<Dialog bind:open={logOpen} title="Its log" description="What its code printed, newest last" wide testid="app-log-dialog">
  <pre class="max-h-[60vh] overflow-auto rounded-lg bg-muted p-3 font-mono text-xs whitespace-pre-wrap" data-testid="app-log">{log === null ? "…" : log || "(empty)"}</pre>
</Dialog>
