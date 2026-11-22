<script lang="ts">
  import PinButton from "../components/PinButton.svelte";
  // An app's page (contract H, apps design), `#/apps/<name>`, under Library › Apps (E6: reached
  // from Library or Apps' ⋯ → Manage). Its header: its title, its state (running, asleep, failed),
  // version and where it comes from, what waits (a version to deploy, a change of the App
  // creator, something to give it: a chip leading to Settings), Pin, its ⋯ (Change it with the
  // App creator, Export, Stop, Uninstall…) and Open. Then two tabs, one per reason to come:
  // Activity, what it did (AppActivity: its runs, the changes to its folders, what it sent you,
  // its versions, its log), and Settings, what you chose, with an index: its Version (the one in
  // use, the next one to deploy and what it adds, a waiting draft of the App creator (H.15, H.16:
  // Try it, Continue, Use it, Throw away), the one kept and Go back; nothing is deployed by
  // itself, only here or with `handler app deploy`: agents write apps, people install them), What
  // it uses (its folders and secrets, each Change…), Who works (the app's, then each job's: as
  // the app or its own, H.1, H.2; why one cannot run), What you can ask it (H.12: Try, in Ask per
  // action), What it asks you (its nudges, H.17: on, when, reminders), Runs by itself (its
  // suggested automations: made, then on or off here), Who can use it (the phones it opens on)
  // and What it may touch (its permissions and its jobs' Can do, rule app-job.can-do-is-the-app-s).
  // Without a tab in its address it opens on Settings while it lacks something, else Activity.
  import AppWindow from "@lucide/svelte/icons/app-window";
  import ArrowUp from "@lucide/svelte/icons/arrow-up";
  import CircleCheck from "@lucide/svelte/icons/circle-check";
  import Clock from "@lucide/svelte/icons/clock";
  import Repeat from "@lucide/svelte/icons/repeat";
  import Square from "@lucide/svelte/icons/square";
  import FileText from "@lucide/svelte/icons/file-text";
  import Folder from "@lucide/svelte/icons/folder";
  import History from "@lucide/svelte/icons/history";
  import KeyRound from "@lucide/svelte/icons/key-round";
  import Lock from "@lucide/svelte/icons/lock";
  import Play from "@lucide/svelte/icons/play";
  import Trash from "@lucide/svelte/icons/trash-2";
  import Pencil from "@lucide/svelte/icons/pencil";
  import Undo2 from "@lucide/svelte/icons/undo-2";
  import Users from "@lucide/svelte/icons/user-round-cog";
  import Zap from "@lucide/svelte/icons/zap";
  import ExternalLink from "@lucide/svelte/icons/external-link";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import Download from "@lucide/svelte/icons/download";
  import FilePenLine from "@lucide/svelte/icons/file-pen-line";
  import Upload from "@lucide/svelte/icons/upload";
  import WandSparkles from "@lucide/svelte/icons/wand-sparkles";
  import Eye from "@lucide/svelte/icons/eye";
  import Ellipsis from "@lucide/svelte/icons/ellipsis";
  import DisabledReason from "../components/DisabledReason.svelte";
  import Popover from "../components/Popover.svelte";
  import ActionTry from "../components/ActionTry.svelte";
  import NudgeReminders from "../components/NudgeReminders.svelte";
  import NudgeWhen from "../components/NudgeWhen.svelte";
  import Switch from "../components/Switch.svelte";
  import Dialog from "../components/Dialog.svelte";
  import FolderPicker from "../components/FolderPicker.svelte";
  import LoadingCards from "../components/LoadingCards.svelte";
  import NotesHistoryPanel from "../components/NotesHistoryPanel.svelte";
  import HelperCard from "../components/HelperCard.svelte";
  import PageHeader, { type PageTab } from "../components/PageHeader.svelte";
  import AppActivity from "../components/AppActivity.svelte";
  import AppFailure from "../components/AppFailure.svelte";
  import AppWhoWorks from "../components/AppWhoWorks.svelte";
  import WhoWorksView from "../components/WhoWorks.svelte";
  import When from "../components/When.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { addedWords, appTitle, automationApp, jobAutomations, jobLimits, suggested, touchWords } from "../lib/apps";
  import { unattendedBlocked } from "../lib/blocked";
  import { harnesses } from "../lib/harnesses.svelte";
  import { runtime } from "../lib/runtime.svelte";
  import { fromSourceWords } from "../lib/sources";
  import { onChange } from "../lib/events.svelte";
  import { api } from "../lib/api";
  import { whenSentence } from "../lib/automations";
  import type { AccountInfo, App, AppAction, AppFileNeed, AppJob, AppRun, AppSecret, AutomationView, DraftCopy, AppManifestSuggestedAutomation, Session, WhoWorks } from "../lib/contracts.gen";
  import { continueDraft, copyLabel, draftsOf, openDraft, startDraft, throwAway, useDraft } from "../lib/drafts";
  import { href, navigate, type AppTab } from "../lib/router.svelte";
  import { projects } from "../lib/projects.svelte";
  import { remote } from "../lib/remote.svelte";
  import { homePath } from "../lib/text";

  let { name, tab }: { name: string; tab?: AppTab } = $props();
  let app = $state<App | null>(null);
  const title = $derived(app ? appTitle(app) : name); // what it is called (H.1)
  let error = $state<string | null>(null);
  let busy = $state<string | null>(null); // what it is doing ("deploying…")
  let problem = $state<string | null>(null);
  let problemLogged = $state(false); // a deploy, an update, going back: its log shown under it
  let creatorCard = $state(false); // no App creator yet: its set-up card
  let automations = $state<AutomationView[]>([]); // which of its suggestions are made
  let draft = $state<Session | null>(null); // a draft of its code waiting (H.15)
  let copies = $state<DraftCopy[] | null>(null); // the draft opened (H.16): what it works on
  let scroller = $state<HTMLElement | null>(null); // the page's scrolling part (the index jumps in it)
  let menuOpen = $state(false); // its ⋯
  // its parts (H.14): its jobs, and what runs them by itself
  const schedules = $derived(automations.filter((x) => automationApp(x.definition) === name));
  let trying = $state<AppAction | null>(null); // the action of the Try dialog
  let tryOpen = $state(false);
  // the need being changed, in its dialog, and what is typed or picked there
  let editing = $state<
    { kind: "folder"; need: AppFileNeed } | { kind: "secret"; need: AppSecret } | { kind: "who"; job: AppJob | null } | null
  >(null);
  let whoInput = $state<WhoWorks | null>(null); // who works, as picked in its dialog
  let runs = $state<AppRun[]>([]); // its runs (H.11), newest first
  let accounts = $state<AccountInfo[]>([]); // their harnesses: whose terms refuse runs nobody follows
  let editOpen = $state(false);
  let folderInput = $state("");
  let secretInput = $state("");
  // what asks to be confirmed, in a dialog: going back a version, deploying one that reaches more, removing
  let confirming = $state<"rollback" | "deploy" | "update" | "uninstall" | null>(null);
  let confirmOpen = $state(false);

  // Apps are shared with persons, not devices: you ("owner") and the persons family members'
  // devices were paired for (Settings → Your phone).
  const devicesOf = $derived.by(() => {
    const out: Record<string, string[]> = { owner: [] };
    for (const d of remote.status?.devices ?? []) (out[d.person ?? "owner"] ??= []).push(d.name);
    return out;
  });

  async function load(): Promise<void> {
    try {
      let list: Session[];
      [app, automations, list, runs, accounts] = await Promise.all([
        api.app(name),
        api.automations().catch(() => []),
        api.sessions().catch(() => []),
        api.appRuns(name).catch(() => []),
        api.accounts().catch(() => []),
        harnesses.load(),
      ]);
      draft = draftsOf(list, name)[0] ?? null;
      error = null;
    } catch (e) {
      error = (e as Error).message;
    }
  }

  $effect(() => {
    const stop = onChange(["apps", "sessions"], () => void load()); // its state, its runs and drafts
    void load();
    return stop;
  });

  /** `logged`: a step written in the app's log (deploy, update, going back), shown with its
   * failure. */
  async function act(doing: string, action: () => Promise<unknown>, logged = false): Promise<void> {
    busy = doing;
    problem = null;
    try {
      await action();
    } catch (e) {
      problem = (e as Error).message;
      problemLogged = logged;
    } finally {
      busy = null;
      await load();
    }
  }

  const deployable = $derived(!!app && !app.source.error && !!app.source.version && app.source.version !== app.current?.version);
  // what it lacks: folders and secrets not given, nobody chosen to work on its jobs
  const filesLeft = $derived(app ? (app.files ?? []).filter((f) => !f.path).length + (app.secrets ?? []).filter((s) => !s.set).length : 0);
  const left = $derived(filesLeft + (app?.jobs?.length && !app.whoWorks ? 1 : 0));
  const needs = $derived((app?.files?.length ?? 0) + (app?.secrets?.length ?? 0));
  const shownTab = $derived<AppTab>(tab ?? (left > 0 || !app?.current ? "settings" : "activity"));
  const asked = $derived(app?.current?.needs ?? app?.source.needs); // what it may touch: its version's
  const settingsHref = $derived(href({ view: "apps", app: name, tab: "settings" }));
  const tabs = $derived<PageTab[]>([
    { label: "Activity", href: href({ view: "apps", app: name, tab: "activity" }), active: shownTab === "activity", testid: "app-tab-activity" },
    { label: "Settings", href: settingsHref, active: shownTab === "settings", testid: "app-tab-settings" },
  ]);
  // Settings' index: the sections it has, a dot on one that waits for you
  const index = $derived.by(() => {
    const a = app;
    if (!a) return [];
    const waits = ((deployable || !!a.offered) && !!a.current) || !!draft;
    return [
      { id: "version", label: "Version", dot: waits ? "bg-primary" : "" },
      ...(needs ? [{ id: "uses", label: "What it uses", dot: filesLeft ? "bg-warn" : "" }] : []),
      ...(a.jobs?.length ? [{ id: "who", label: "Who works", dot: a.whoWorks ? "" : "bg-warn" }] : []),
      ...(a.actions?.length ? [{ id: "ask", label: "What you can ask it", dot: "" }] : []),
      ...(a.nudges?.length ? [{ id: "asks-you", label: "What it asks you", dot: "" }] : []),
      ...(a.suggests?.length ? [{ id: "itself", label: "Runs by itself", dot: "" }] : []),
      ...(a.current ? [{ id: "phone", label: "Who can use it", dot: "" }] : []),
      { id: "touch", label: "What it may touch", dot: "" },
    ];
  });

  function jump(id: string): void {
    document.getElementById(`app-s-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function update(a: App): void {
    if (a.offered?.addedNeeds?.length) ask("update");
    else void act("updating (gets it, tests, health check)…", () => api.updateApp(a.name), true);
  }

  function deploy(a: App): void {
    if (a.source.addedNeeds?.length) ask("deploy");
    else void act("deploying (tests, health check)…", () => api.deployApp(a.name), true);
  }

  function ask(what: "rollback" | "deploy" | "update" | "uninstall"): void {
    confirming = what;
    confirmOpen = true;
  }

  function confirmed(a: App): void {
    confirmOpen = false;
    if (confirming === "rollback") void act("going back…", () => api.rollbackApp(a.name), true);
    else if (confirming === "deploy") void act("deploying (tests, health check)…", () => api.deployApp(a.name), true);
    else if (confirming === "update") void act("updating (gets it, tests, health check)…", () => api.updateApp(a.name), true);
    else if (confirming === "uninstall") void uninstall(a);
  }

  async function uninstall(a: App): Promise<void> {
    busy = "uninstalling…";
    try {
      await api.uninstallApp(a.name);
      navigate({ view: "apps" }, true);
    } catch (e) {
      problem = (e as Error).message;
      busy = null;
    }
  }

  async function open(a: App): Promise<void> {
    // opened now, while the click still counts as a user action (popup blockers), filled after
    const tab = window.open("about:blank", "_blank");
    try {
      const link = await api.openApp(a.name);
      if (tab) {
        tab.opener = null;
        tab.location.href = link.url;
      }
    } catch (e) {
      tab?.close();
      problem = (e as Error).message;
    }
  }

  function change(e: NonNullable<typeof editing>): void {
    editing = e;
    folderInput = e.kind === "folder" ? (e.need.path ?? "") : "";
    secretInput = "";
    whoInput = e.kind === "who" ? ((e.job ? e.job.whoWorks : app?.whoWorks) ?? null) : null;
    editOpen = true;
  }

  /** Why a job cannot run now (rule app-job.runs-as-its-who-works): handlerd's (nobody chosen,
   *  the model alone for a job reaching folders, one that cannot run here), else an automation
   *  running it on an account whose terms refuse runs nobody follows (I.7). */
  function jobProblem(a: App, job: AppJob): string | null {
    if (job.problem) return job.problem;
    const by = jobAutomations(a.name, job.name, automations);
    const w = job.whoWorks;
    const refused = by.length && w ? unattendedBlocked({ account: w.account, harness: w.program }, accounts, harnesses.list, "") : null;
    return refused ? `${refused.reason}, and the automation ${by[0]!.name} runs it` : null;
  }

  /** What a Who works choice may not be, for the app's (the jobs running as the app) or a job's. */
  function limitsOf(a: App, job: AppJob | null): ReturnType<typeof jobLimits> {
    const jobs = job ? [job] : (a.jobs ?? []).filter((j) => !j.own);
    return jobLimits(jobs, jobs.some((j) => jobAutomations(a.name, j.name, automations).length > 0));
  }

  const sameWho = (x: WhoWorks | null | undefined, y: WhoWorks | null | undefined): boolean => JSON.stringify(x ?? null) === JSON.stringify(y ?? null);

  function saved(action: () => Promise<unknown>): void {
    editOpen = false;
    void act("saving…", action);
  }

  /** Its code as one file, saved by the browser (H.15). */
  async function exportIt(): Promise<void> {
    try {
      const { file, filename } = await api.exportApp(name);
      const link = Object.assign(document.createElement("a"), { href: URL.createObjectURL(file), download: filename });
      link.click();
      URL.revokeObjectURL(link.href);
    } catch (e) {
      problem = (e as Error).message;
    }
  }

  /** The automation made from a suggestion (at Install or here): by its name, running this app's
   *  job; two suggestions running the same job are two automations. */
  function madeFrom(a: App, s: AppManifestSuggestedAutomation): AutomationView | undefined {
    const name = suggested(a, s).name;
    return automations.find((x) => x.name === name && automationApp(x.definition) === a.name);
  }

  function make(a: App, s: AppManifestSuggestedAutomation): void {
    const { name: made, definition } = suggested(a, s); // off: turning it on is yours
    void act("making the automation…", () => api.createAutomation(made, { definition, agentId: null, enable: false }));
  }

  function togglePerson(a: App, person: string, on: boolean): void {
    const persons = new Set(a.persons ?? []);
    if (on) persons.add(person);
    else persons.delete(person);
    void act("saving…", () => api.setAppPersons(a.name, [...persons]));
  }

  const plural = (n: number, word: string): string => `${n} ${word}${n === 1 ? "" : "s"}`;
  /** Its state, said once, in words: an app stopped is asleep until it is opened (idle timeout). */
  const stateWords = (a: App): string => (a.state === "stopped" ? "asleep, starts when opened" : a.state === "failed" ? "failed" : a.state);
</script>

{#snippet stateDot(a: App)}
  {@const tone = a.state === "failed" ? "bg-danger" : a.state === "running" ? "bg-ok" : "bg-muted-foreground/50"}
  <span class="inline-flex items-center gap-1.5" data-testid="app-state"><span class="size-2 rounded-full {tone}"></span>{a.current ? stateWords(a) : "not installed"}</span>
{/snippet}

<PageHeader width="max-w-5xl" title={title} parent={{ label: "Library › Apps", href: href({ view: "library", shelf: "apps" }) }} tabs={app ? tabs : undefined}>
  {#snippet sub()}
    {#if app}
      {@const a = app}
      {@render stateDot(a)}
      <span class="fact">{a.current ? a.current.version : ""}{a.current ? " · " : ""}{fromSourceWords(a.fromSource, []) ?? "made by you"}</span>
      {#if a.offered && a.current}
        <a class="inline-flex items-center gap-1 rounded-md bg-primary/10 px-1.5 py-0.5 text-primary no-underline" href={settingsHref} data-testid="app-update"><ArrowUp class="size-3" />{a.offered.version} available</a>
      {:else if deployable && a.current}
        <a class="inline-flex items-center gap-1 rounded-md bg-primary/10 px-1.5 py-0.5 text-primary no-underline" href={settingsHref} data-testid="app-update">{a.source.version} to deploy</a>
      {:else if draft}
        <a class="inline-flex items-center gap-1 rounded-md bg-primary/10 px-1.5 py-0.5 text-primary no-underline" href={settingsHref} data-testid="app-draft-chip"><FilePenLine class="size-3" />your change waiting</a>
      {/if}
      {#if left}
        <a class="inline-flex items-center gap-1 rounded-md bg-warn/10 px-1.5 py-0.5 text-warn no-underline" href={settingsHref} data-testid="app-needs-missing"
          ><TriangleAlert class="size-3" />{left === 1 ? "one thing" : `${left} things`} to give it</a
        >
      {/if}
      {#if a.description ?? a.source.description}<span class="basis-full text-sm">{a.description ?? a.source.description}</span>{/if}
    {/if}
  {/snippet}
  {#snippet menu()}
    {#if app}
      {@const a = app}
      <PinButton kind="app" id={name} label={title} />
      <Popover bind:open={menuOpen} align="end" label="More" width="16rem" testid="app-page-menu">
        {#snippet trigger(props)}
          <Button variant="ghost" size="icon" class="size-8 text-muted-foreground" {...props} aria-label="More" data-testid="app-page-more"><Ellipsis /></Button>
        {/snippet}
        {#snippet children(close)}
          {#if !draft}
            <button
              type="button"
              class="menu-item"
              disabled={!!busy}
              title={a.fromSource ? "On a draft of its code: once used, it is yours (its source no longer offers it a new version)" : "On a draft of its code"}
              onclick={() => (close(), void act("opening the App creator…", async () => (creatorCard = !(await startDraft(name)))))}
              data-testid="app-improve"><WandSparkles />Change it with the App creator</button
            >
          {/if}
          <button type="button" class="menu-item" title="Its code as one file, to share or keep" onclick={() => (close(), void exportIt())} data-testid="app-export"><Download />Export</button>
          {#if a.state === "running"}
            <button type="button" class="menu-item" disabled={!!busy} title="It starts again when it is opened" onclick={() => (close(), void act("stopping…", () => api.stopApp(a.name)))} data-testid="app-stop"
              ><Square />Stop it</button
            >
          {/if}
          <div class="my-1 border-t"></div>
          <button type="button" class="menu-item text-danger" disabled={!!busy} onclick={() => (close(), ask("uninstall"))} data-testid="app-uninstall"><Trash />Uninstall…</button>
        {/snippet}
      </Popover>
      {#if !a.current}
        <Button size="sm" class="ml-2" href={href({ view: "install-app", name: a.name })} data-testid="app-install"><Upload />Install</Button>
      {:else}
        <Button size="sm" class="ml-2" disabled={filesLeft > 0} title={filesLeft ? "Give it what it needs first" : undefined} onclick={() => open(a)} data-testid="app-open"><ExternalLink />Open {title}</Button>
      {/if}
    {/if}
  {/snippet}
</PageHeader>
<div class="flex-1 overflow-y-auto" bind:this={scroller}>
  <div class="mx-auto w-full max-w-5xl px-8 py-8" data-testid="app-page">
    {#if error}<p class="text-sm text-danger" data-testid="apps-error">{error}</p>{/if}
    {#if creatorCard}
      <div class="mb-8">
        <HelperCard need="app-creator" title={`Change ${title}`} onready={() => ((creatorCard = false), void act("opening the App creator…", () => startDraft(name)))} />
      </div>
    {/if}
    {#if busy}<p class="mb-4 fact" data-testid="app-busy">{busy}</p>{/if}
    {#if problem && problemLogged}
      <div class="mb-6"><AppFailure {name} message={problem} testid="app-problem" /></div>
    {:else if problem}<p class="mb-4 text-sm text-danger" data-testid="app-problem">{problem}</p>{/if}
    {#if app?.error && !busy}
      <div class="mb-6"><AppFailure {name} message={app.error} from="start" testid="app-error" /></div>
    {/if}
    {#if !app}
      {#if !error}<LoadingCards count={2} height="h-24" />{/if}
    {:else if shownTab === "activity"}
      <AppActivity app={app} {runs} />
    {:else}
      {@const a = app}
      <div class="grid items-start gap-10 lg:grid-cols-[10.5rem_1fr]">
        <nav class="sticky top-0 hidden space-y-0.5 text-[13px] lg:block" aria-label="settings" data-testid="app-settings-index">
          {#each index as s (s.id)}
            <button type="button" class="flex w-full cursor-pointer items-center gap-2 rounded-md px-2 py-1 text-left text-muted-foreground hover:bg-muted hover:text-foreground" onclick={() => jump(s.id)}
              >{s.label}{#if s.dot}<span class="ml-auto size-1.5 rounded-full {s.dot}"></span>{/if}</button
            >
          {/each}
        </nav>
        <div class="min-w-0 space-y-9 text-sm">
          <section id="app-s-version" class="scroll-mt-4 space-y-2" data-testid="app-version">
            <h2 class="font-semibold">Version</h2>
            <div class="divide-y overflow-hidden rounded-[10px] border bg-card shadow-panel">
              <div class="flex flex-wrap items-center gap-3 px-4 py-3">
                <AppWindow class="size-4 text-muted-foreground" />
                <div class="min-w-0 flex-1">
                  {#if a.current}
                    <p><span class="font-mono font-medium">{a.current.version}</span> in use</p>
                    <p class="text-xs text-muted-foreground">{fromSourceWords(a.fromSource, []) ?? "made by you"} · deployed <When at={a.current.deployedAt} /></p>
                  {:else}
                    <p class="font-medium">Not installed yet</p>
                  {/if}
                </div>
              </div>
              {#if a.source.error}<p class="px-4 py-3 text-danger">Its code: {a.source.error}</p>{/if}
              {#if a.offered && a.current}
                {@const o = a.offered}
                <div class="space-y-3 bg-primary/5 px-4 py-3" data-testid="app-offered">
                  <p><span class="font-mono font-medium">{o.version}</span> is available <span class="text-muted-foreground">· {fromSourceWords(o.source, [])}</span></p>
                  {#if o.changes}<p class="text-[13px] whitespace-pre-line" data-testid="app-offered-changes"><span class="text-muted-foreground">What's new:</span> {o.changes}</p>{/if}
                  {#if o.addedNeeds?.length}
                    <div class="rounded-lg bg-warn/10 px-3 py-2 text-[13px]" data-testid="app-offered-adds">
                      <p class="flex items-center gap-1.5 font-medium text-warn"><TriangleAlert class="size-3.5" />This version also asks for:</p>
                      <ul class="mt-1 space-y-0.5 pl-5 text-warn">
                        {#each o.addedNeeds as added (added)}<li>+ {addedWords(added, a)}</li>{/each}
                      </ul>
                    </div>
                  {/if}
                  <div class="flex flex-wrap items-center gap-3">
                    <Button size="sm" disabled={!!busy} onclick={() => update(a)} data-testid="app-update-go"><ArrowUp />Update to {o.version}</Button>
                    <p class="min-w-0 flex-1 text-xs text-muted-foreground">Handler gets it, tests it first and keeps {a.current.version}: if anything fails, nothing changes. You can go back.</p>
                  </div>
                </div>
              {/if}
              {#if deployable && a.current}
                <div class="space-y-3 bg-primary/5 px-4 py-3" data-testid="app-next-version">
                  <p><span class="font-mono font-medium">{a.source.version}</span> is ready to deploy <span class="text-muted-foreground">· {a.fromSource ? fromSourceWords(a.fromSource, []) : "made by you"}</span></p>
                  {#if a.source.changes}<p class="text-[13px] whitespace-pre-line"><span class="text-muted-foreground">What's new:</span> {a.source.changes}</p>{/if}
                  {#if a.source.addedNeeds?.length}
                    <div class="rounded-lg bg-warn/10 px-3 py-2 text-[13px]" data-testid="app-next-adds">
                      <p class="flex items-center gap-1.5 font-medium text-warn"><TriangleAlert class="size-3.5" />This version also asks for:</p>
                      <ul class="mt-1 space-y-0.5 pl-5 text-warn">
                        {#each a.source.addedNeeds as added (added)}<li>+ {addedWords(added, a)}</li>{/each}
                      </ul>
                    </div>
                  {/if}
                  <div class="flex flex-wrap items-center gap-3">
                    <Button size="sm" disabled={!!busy} onclick={() => deploy(a)} data-testid="app-deploy"><Upload />Deploy {a.source.version}</Button>
                    <p class="min-w-0 flex-1 text-xs text-muted-foreground">Handler tests it first and keeps {a.current.version}: if anything fails, nothing changes. You can go back.</p>
                  </div>
                </div>
              {/if}
              {#if draft}
                {@const d = draft}
                <div class="space-y-2 bg-primary/5 px-4 py-3" data-testid="app-draft">
                  <p class="flex items-center gap-2"><FilePenLine class="size-4 shrink-0 text-primary" /><b class="font-semibold">Your change, waiting:</b> “{d.title ?? "untitled"}”, with the App creator</p>
                  <p class="text-xs text-muted-foreground">{title} as you use it is untouched until you use it: Handler tests it first and keeps {a.current?.version ?? "the version in use"}.</p>
                  <div class="flex flex-wrap items-center gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={!!busy}
                      title="The changed app, in a new tab, on copies of its data and folders"
                      onclick={() => act("opening the draft…", async () => (copies = await openDraft(d.id)))}
                      data-testid="draft-open"><Eye />Try it</Button
                    >
                    <Button size="sm" variant="outline" onclick={() => continueDraft(d)} data-testid="draft-continue"><WandSparkles />Continue</Button>
                    <Button size="sm" disabled={!!busy} onclick={() => act("using it (tests, health check)…", () => useDraft(d.id))} data-testid="draft-use">Use it</Button>
                    <Button size="sm" variant="ghost" class="ml-auto text-danger hover:text-danger" disabled={!!busy} onclick={() => act("throwing it away…", () => throwAway(d))} data-testid="draft-throw"
                      ><Trash />Throw away</Button
                    >
                  </div>
                  {#if copies}
                    <p class="text-xs text-muted-foreground" data-testid="draft-copies">Opened in a new tab, on copies: {copies.map(copyLabel).join(" · ")}. Opening it again takes new copies.</p>
                  {/if}
                </div>
              {/if}
              {#if a.previous}
                <div class="flex flex-wrap items-center gap-3 px-4 py-3">
                  <History class="size-4 text-muted-foreground" />
                  <div class="min-w-0 flex-1">
                    <p>Kept: <span class="font-mono">{a.previous.version}</span></p>
                    <p class="text-xs text-muted-foreground">Going back brings its data back as it was then; your folders stay as they are.</p>
                  </div>
                  <Button size="sm" variant="ghost" disabled={!!busy} onclick={() => ask("rollback")} data-testid="app-rollback"><Undo2 />Go back to {a.previous.version}…</Button>
                </div>
              {/if}
              <p class="bg-muted px-4 py-2.5 text-xs text-muted-foreground">
                {#if a.fromSource}New versions come from {fromSourceWords(a.fromSource, [])?.replace(/^from /, "") ?? "its source"} (read again each day: shown here, then
                  Update), from an app file you import in Library › Apps, or a change you make with the App creator.{:else}New versions come from an app file you import in Library › Apps, or a change you make with the App creator.{/if} Nothing is deployed by itself.
              </p>
            </div>
          </section>

          {#if needs}
            <section id="app-s-uses" class="scroll-mt-4 space-y-2" data-testid="app-needs">
              <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <h2 class="font-semibold">What it uses</h2>
                {#if filesLeft}
                  <span class="inline-flex items-center gap-1 self-center rounded-md bg-warn/10 px-1.5 py-0.5 text-xs text-warn"><TriangleAlert class="size-3" />{filesLeft} to give</span>
                {:else}
                  <span class="inline-flex items-center gap-1 self-center text-xs text-ok" data-testid="app-needs-set"><CircleCheck class="size-3.5" />all set</span>
                {/if}
                <span class="text-xs text-muted-foreground">what {title} asks for; you choose what you give it</span>
              </div>
              {#if (a.files?.length ?? 0) + (a.secrets?.length ?? 0)}
                <ul class="divide-y overflow-hidden rounded-[10px] border bg-card shadow-panel">
                  {#each a.files ?? [] as f (f.name)}
                    {@const home = f.path ? projects.list.find((p) => p.folder === f.path) : undefined}
                    <li class="flex items-center gap-3 px-4 py-3 {f.path ? '' : 'bg-warn/10'}" data-testid="app-need-folder">
                      <span class="flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">{#if f.file}<FileText class="size-4" />{:else}<Folder class="size-4" />{/if}</span>
                      <div class="min-w-0 flex-1">
                        <p><span class="font-medium">{(f.description ?? (f.file ? "A file" : "A folder")).replace(/\.$/, "")}</span> <span class="text-xs text-muted-foreground">· {f.mode === "rw" ? "reads and writes" : "reads"}</span></p>
                        {#if f.path}
                          <p class="truncate font-mono text-[12.5px] text-muted-foreground" title={f.path}>{f.path}</p>
                          {#if f.file}
                            <p class="text-xs text-muted-foreground" data-testid="app-need-file-hint">
                              {title} sees what you change in this file. If your editor replaces the file when it saves, {title} sees your changes after a restart.
                              {#if a.state === "running" && !busy}<button type="button" class="text-link hover:underline" onclick={() => act("restarting…", () => api.stopApp(a.name))} data-testid="app-need-file-restart">Restart</button>{/if}
                            </p>
                          {/if}
                          {#if home}<p class="text-xs text-muted-foreground">the folder of the project <a class="text-link hover:underline" href={href({ view: "project", id: home.id })}>{home.name}</a></p>{/if}
                        {:else}
                          <p class="font-medium text-warn">Not given yet</p>
                        {/if}
                      </div>
                      <Button size="sm" variant={f.path ? "outline" : "default"} disabled={!!busy} onclick={() => change({ kind: "folder", need: f })} data-testid="app-need-change"
                        >{f.path ? "Change…" : "Choose a folder…"}</Button
                      >
                    </li>
                  {/each}
                  {#each a.secrets ?? [] as s (s.name)}
                    <li class="flex items-center gap-3 px-4 py-3 {s.set ? '' : 'bg-warn/10'}" data-testid="app-need-secret">
                      <span class="flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground"><KeyRound class="size-4" /></span>
                      <div class="min-w-0 flex-1">
                        <p class="text-xs text-muted-foreground">A secret: <span class="font-mono">{s.name}</span>, kept by Handler, never in the app's folder</p>
                        {#if s.set}<p class="font-medium">set</p>{:else}<p class="font-medium text-warn">Not set yet</p>{/if}
                      </div>
                      <Button size="sm" variant={s.set ? "outline" : "default"} disabled={!!busy} onclick={() => change({ kind: "secret", need: s })} data-testid="app-need-change"
                        >{s.set ? "Change…" : "Set it…"}</Button
                      >
                    </li>
                  {/each}
                </ul>
              {/if}
            </section>
          {/if}

          {#if a.jobs?.length}
            <section id="app-s-who" class="scroll-mt-4 space-y-2" data-testid="app-jobs">
              <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <h2 class="font-semibold">Who works</h2>
                <span class="text-xs text-muted-foreground">on the work {title} asks a model to do; what each job can do is {title}'s (What it may touch)</span>
              </div>
              <ul class="divide-y overflow-hidden rounded-[10px] border bg-card shadow-panel">
                <li class="flex items-center gap-3 px-4 py-3 {a.whoWorks ? '' : 'bg-warn/10'}" data-testid="app-need-who-works">
                  <span class="flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground"><Users class="size-4" /></span>
                  <div class="min-w-0 flex-1 space-y-1">
                    <p class="font-medium">For its jobs <span class="text-xs font-normal text-muted-foreground">unless one has its own</span></p>
                    {#if a.whoWorks}
                      <WhoWorksView agent={{ model: { harness: a.whoWorks.program ?? null, account: a.whoWorks.account, provider: a.whoWorks.provider, model: a.whoWorks.model }, modelAlone: !a.whoWorks.program }} />
                    {:else}
                      <p class="font-medium text-warn">Not chosen yet</p>
                    {/if}
                  </div>
                  <Button size="sm" variant={a.whoWorks ? "outline" : "default"} disabled={!!busy} onclick={() => change({ kind: "who", job: null })} data-testid="app-who-works-change"
                    >{a.whoWorks ? "Change…" : "Choose who works…"}</Button
                  >
                </li>
                {#each a.jobs as job (job.name)}
                  {@const why = jobProblem(a, job)}
                  <li class="space-y-1 py-2.5 pr-4 pl-15 {why ? 'bg-muted/50' : ''}" data-testid="app-job" data-job={job.name}>
                    <div class="flex flex-wrap items-center gap-2">
                      <p class="min-w-0 flex-1">{job.description}</p>
                      {#if job.own && job.whoWorks}
                        <span class:opacity-60={!!why}
                          ><WhoWorksView agent={{ model: { harness: job.whoWorks.program ?? null, account: job.whoWorks.account, provider: job.whoWorks.provider, model: job.whoWorks.model }, modelAlone: !job.whoWorks.program }} /></span
                        >
                      {:else if !job.whoWorks}
                        <span class="text-muted-foreground">nobody chosen</span>
                      {/if}
                      <span class="text-xs text-muted-foreground" data-testid="app-job-as">{job.own ? "its own" : "as the app"}</span>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        class="text-muted-foreground"
                        disabled={!!busy}
                        title="Change who works on this job"
                        aria-label="Change who works on this job"
                        onclick={() => change({ kind: "who", job })}
                        data-testid="app-job-who-change"><Pencil /></Button
                      >
                      {#if job.own}
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          class="text-muted-foreground"
                          disabled={!!busy}
                          title="Back to the app's Who works"
                          aria-label="Back to the app's Who works"
                          onclick={() => act("saving…", () => api.unsetJobWhoWorks(a.name, job.name))}
                          data-testid="app-job-who-back"><Undo2 /></Button
                        >
                      {/if}
                    </div>
                    {#if why}
                      <p class="flex items-start gap-1.5 text-xs text-warn" data-testid="app-job-problem"><TriangleAlert class="mt-0.5 size-3 shrink-0" />It cannot run now: {why}</p>
                    {/if}
                  </li>
                {/each}
              </ul>
            </section>
          {/if}

          {#if a.actions?.length}
            {@const inAsk = a.actions.filter((x) => x.inAsk !== false).length}
            <section id="app-s-ask" class="scroll-mt-4 space-y-2" data-testid="app-actions">
              <div class="flex items-center gap-3 pr-4">
                <h2 class="font-semibold">What you can ask it</h2>
                {#if inAsk > 0 && inAsk < a.actions.length}<span class="ml-auto text-xs text-muted-foreground" data-testid="app-ask-count">{inAsk} of {a.actions.length}</span>{/if}
                <label class="{inAsk > 0 && inAsk < a.actions.length ? '' : 'ml-auto'} flex cursor-pointer items-center gap-2 text-xs font-medium" title={inAsk === a.actions.length ? "Take all of them out of Ask" : "Put all of them in Ask"}>
                  In Ask
                  <input
                    type="checkbox"
                    class="size-4 accent-primary"
                    checked={inAsk === a.actions.length}
                    indeterminate={inAsk > 0 && inAsk < a.actions.length}
                    disabled={!!busy}
                    onchange={(e) => act("saving…", () => api.setAppAsk(a.name, e.currentTarget.checked ? [] : (a.actions ?? []).map((x) => x.name)))}
                    data-testid="app-ask-all"
                  />
                </label>
              </div>
              <ul class="divide-y overflow-hidden rounded-[10px] border bg-card shadow-panel">
                {#each a.actions as action (action.name)}
                  {@const on = action.inAsk !== false}
                  <li class="flex flex-wrap items-center gap-3 px-4 py-3" data-testid="app-action">
                    <div class="min-w-0 flex-1">
                      <p class="font-medium">{action.description}</p>
                      {#if action.examples?.length}<p class={on ? "text-muted-foreground" : "text-muted-foreground/60"}>“{action.examples[0]}”</p>{/if}
                    </div>
                    {#if action.by === "code"}
                      <span class="inline-flex items-center gap-1 rounded-full bg-ok/10 px-2 py-0.5 text-xs text-ok" title="Done by its code"><Zap class="size-3" />instant</span>
                    {:else}
                      <span class="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground" title="Done by one of its jobs"><Clock class="size-3" />takes a while</span>
                    {/if}
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={!a.current}
                      title={a.current ? undefined : "Install it first"}
                      onclick={() => ((trying = action), (tryOpen = true))}
                      data-testid="app-action-try"><Play />Try</Button
                    >
                    <span class="border-l pl-3" title={on ? "In Ask: Ask can pick it when you say something like this" : "Not in Ask: Try here and its nudges still work"}>
                      <Switch
                        checked={on}
                        disabled={!!busy}
                        label="{action.description}: in Ask"
                        testid="app-action-in-ask"
                        onchange={(to) => act("saving…", () => api.setAppAsk(a.name, (a.actions ?? []).filter((x) => (x.name === action.name ? !to : x.inAsk === false)).map((x) => x.name)))}
                      />
                    </span>
                  </li>
                {/each}
              </ul>
              <p class="text-xs text-muted-foreground">
                Instant: done by its code. Takes a while: one of its jobs works on it, from seconds to minutes as the request needs, and its answer also comes to your
                Inbox. {#if inAsk}In Ask: Ask, on Chat's page and on your phones, can pick it and run it at once.{:else}None of them is in Ask: you use them here with Try, or from its nudges.{/if}
              </p>
            </section>
          {/if}

          {#if a.nudges?.length}
            <section id="app-s-asks-you" class="scroll-mt-4 space-y-2" data-testid="app-nudges">
              <div class="flex items-center gap-3 pr-4">
                <h2 class="font-semibold">What it asks you</h2>
                <span class="ml-auto text-xs font-medium">On</span>
              </div>
              <ul class="divide-y overflow-hidden rounded-[10px] border bg-card shadow-panel">
                {#each a.nudges as n (n.name)}
                  {@const target = n.action ? a.actions?.find((x) => x.name === n.action)?.description : null}
                  <li class="space-y-1.5 px-4 py-3" data-testid="app-nudge">
                    <div class="flex items-start gap-3">
                      <div class="min-w-0 flex-1">
                        <p class="font-medium">{n.description}</p>
                        {#if n.off}
                          <p class="text-muted-foreground" data-testid="nudge-off">Off: none come, and the app isn't asked</p>
                        {:else}
                          <p class="text-muted-foreground">
                            {n.action ? `Opens its form: ${target ?? n.action}` : `Opens its page ${n.open}`}{#if n.ifIgnored}. If not done in time: {n.ifIgnored}{/if}
                          </p>
                        {/if}
                      </div>
                      <span class="pt-0.5" title={n.off ? "Off: none come" : "On: it comes at its time, to your Inbox"}>
                        <Switch checked={!n.off} disabled={!!busy} label="{n.description}: on" testid="app-nudge-on" onchange={(on) => act("saving…", () => api.setNudgeOff(a.name, n.name, !on))} />
                      </span>
                    </div>
                    {#if !n.off}
                      {#if n.when}
                        <NudgeWhen when={n.when} ownWhen={n.ownWhen} nextAt={n.nextAt} disabled={!!busy} onchange={(to) => act("saving…", () => api.setNudgeWhen(a.name, n.name, to))} />
                        {#if n.prepared}<p class="text-xs text-muted-foreground" data-testid="nudge-prepared">The app looks first whether there is anything to ask; if not, nothing comes.</p>{/if}
                      {/if}
                      <NudgeReminders setting={n.setting ?? "default"} remind={n.remind} disabled={!!busy} onchange={(to) => act("saving…", () => api.setNudgeSetting(a.name, n.name, to))} />
                    {/if}
                  </li>
                {/each}
              </ul>
              <p class="text-xs text-muted-foreground">They come to your Inbox and stay there until done. What you choose here holds for the next ones too.</p>
            </section>
          {/if}

          {#if a.suggests?.length}
            <section id="app-s-itself" class="scroll-mt-4 space-y-2" data-testid="app-suggests">
              <div class="flex items-center gap-3 pr-4">
                <h2 class="font-semibold">Runs by itself</h2>
                <span class="text-xs text-muted-foreground">what {title} proposes to run on its own; its results open the app</span>
              </div>
              <ul class="divide-y overflow-hidden rounded-[10px] border bg-card shadow-panel">
                {#each a.suggests as s, i (i)}
                  {@const made = madeFrom(a, s)}
                  {@const given = !!a.whoWorks || !s.run.job}
                  <li class="flex flex-wrap items-center gap-3 px-4 py-3" data-testid="app-suggest">
                    <Repeat class="size-4 shrink-0 text-muted-foreground" />
                    <div class="min-w-0 flex-1">
                      <p class="font-medium">{s.description}</p>
                      <p class="text-xs text-muted-foreground">{whenSentence(suggested(a, s).definition)}{#if made?.lastRun}{" · last ran "}<When at={made.lastRun.createdAt} />{/if}</p>
                    </div>
                    {#if made}
                      <Button variant="ghost" size="icon-sm" class="text-muted-foreground" href={href({ view: "automation", name: made.name })} title="Open the automation {made.name}" aria-label="Open the automation" data-testid="app-suggest-made"
                        ><ExternalLink /></Button
                      >
                      <span title={made.enabled ? "On: it runs at its time" : "Off: it does not run"}>
                        <Switch
                          checked={!!made.enabled}
                          disabled={!!busy}
                          label="{s.description}: on"
                          testid="app-suggest-on"
                          onchange={(on) => act("saving…", () => (on ? api.enableAutomation(made.name) : api.disableAutomation(made.name)))}
                        />
                      </span>
                    {:else if given}
                      <Button size="sm" variant="outline" disabled={!!busy} onclick={() => make(a, s)} data-testid="app-suggest-make">Make it</Button>
                    {:else}
                      <span class="text-xs text-muted-foreground">Choose who works on its jobs first.</span>
                    {/if}
                  </li>
                {/each}
              </ul>
              <p class="text-xs text-muted-foreground">Made here, each is off until you turn it on.</p>
            </section>
          {/if}

          {#if a.current}
            <section id="app-s-phone" class="scroll-mt-4 space-y-2" data-testid="app-persons">
              <h2 class="font-semibold">Who can use it</h2>
              <div class="space-y-2 rounded-[10px] border bg-card px-4 py-3 shadow-panel">
                {#if remote.status && !(remote.status.devices ?? []).length && !a.persons?.length}
                  <p class="text-muted-foreground">You, on this computer.</p>
                  <DisabledReason blocked={{ reason: "To use it on your phone too, pair a phone first", fix: { label: "Your phone", href: href({ view: "settings", section: "phone" }) } }} testid="app-persons-unpaired" />
                {:else}
                  <p class="text-xs text-muted-foreground">It always opens on this computer. Also on the paired phones of the people ticked here (Settings → Your phone).</p>
                  <div class="flex flex-wrap gap-2">
                    {#each [...new Set([...Object.keys(devicesOf), ...(a.persons ?? [])])].sort() as person (person)}
                      {@const names = devicesOf[person] ?? []}
                      <label
                        class="flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 has-checked:border-primary/60 has-checked:bg-primary/5"
                        title={names.length ? names.join(", ") : "no paired phone"}
                      >
                        <input type="checkbox" class="accent-primary" checked={a.persons?.includes(person) ?? false} disabled={!!busy} onchange={(e) => togglePerson(a, person, e.currentTarget.checked)} />
                        {person === "owner" ? "you" : person}
                        <span class="text-xs text-muted-foreground">{names.length ? plural(names.length, "phone") : "no phone paired"}</span>
                      </label>
                    {/each}
                  </div>
                {/if}
              </div>
            </section>
          {/if}

          <section id="app-s-touch" class="scroll-mt-4 space-y-2" data-testid="app-reaches">
            <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h2 class="font-semibold">What it may touch</h2>
              <span class="text-xs text-muted-foreground">set by its version; a version that asks for more says so before it is deployed</span>
            </div>
            <div class="rounded-[10px] border bg-card px-4 py-3 shadow-panel">
              {#if asked}
                {#if !a.current}<p class="mb-1.5 text-xs text-muted-foreground">What {a.source.version} asks for, once installed:</p>{/if}
                <ul class="space-y-1 text-muted-foreground">
                  {#each touchWords(asked, a) as line (line)}<li class="flex items-start gap-2"><Lock class="mt-1 size-3 shrink-0" />{line}</li>{/each}
                </ul>
                {#if runtime.last?.supports?.limits === false}
                  <p class="mt-2 flex items-start gap-2 text-xs text-warn" data-testid="app-no-limits">
                    <TriangleAlert class="mt-0.5 size-3 shrink-0" />Its memory and CPU limits are not applied on this computer: it can use all of them (Settings → Sandboxes says why).
                  </p>
                {/if}
              {:else}
                <p class="text-muted-foreground">Its code cannot be read: {a.source.error}</p>
              {/if}
            </div>
          </section>
        </div>
      </div>
    {/if}
  </div>
</div>


<Dialog bind:open={tryOpen} title={trying ? `Try: ${trying.description}` : ""} wide testid="action-try-dialog">
  {#if trying}{#key trying.name}<ActionTry app={name} action={trying} />{/key}{/if}
</Dialog>

<Dialog
  bind:open={editOpen}
  wide={editing?.kind === "folder" || editing?.kind === "who"}
  title={editing?.kind === "folder"
    ? (editing.need.description ?? "A folder")
    : editing?.kind === "who"
      ? editing.job
        ? `Who works on “${editing.job.description}”`
        : `Who works on ${title}'s jobs`
      : editing
        ? `The secret ${editing.need.name}`
        : ""}
  description={editing?.kind === "folder"
    ? `${title} ${editing.need.mode === "rw" ? "reads and writes" : "reads"} this folder.`
    : editing?.kind === "secret"
      ? "Kept by Handler, never in the app's folder. Changing it restarts the app."
      : editing?.kind === "who"
        ? editing.job
          ? `Its own, instead of ${title}'s. What it can do stays what ${title} says.`
          : `Every job of ${title} but one with its own. What each can do stays what ${title} says.`
        : undefined}
  testid="app-need-dialog"
>
  {#if editing?.kind === "folder"}
    {@const f = editing.need}
    <form class="space-y-3" onsubmit={(e) => (e.preventDefault(), saved(() => api.setAppFile(name, f.name, folderInput.trim())))}>
      <FolderPicker id={`app-folder-${f.name}`} bind:value={folderInput} forApp />
      {#if f.path}<p class="text-xs text-muted-foreground">What is in {f.path} is not moved: {title} works on what the new folder holds.</p>{/if}
      <div class="flex justify-end gap-2">
        <Button variant="outline" onclick={() => (editOpen = false)}>Cancel</Button>
        <Button type="submit" disabled={!folderInput.trim().startsWith("/") || folderInput.trim() === f.path} data-testid="app-need-folder-save">Give this folder</Button>
      </div>
    </form>
  {:else if editing?.kind === "who" && app}
    {@const a = app}
    {@const job = editing.job}
    {@const current = job ? (job.own ? job.whoWorks : null) : a.whoWorks}
    {@const runBy = (job ? [job] : (a.jobs ?? []).filter((j) => !j.own)).some((j) => jobAutomations(a.name, j.name, automations).length > 0)}
    <form
      class="space-y-4"
      onsubmit={(e) => (e.preventDefault(), whoInput && saved(() => (job ? api.setJobWhoWorks(name, job.name, whoInput!) : api.setAppWhoWorks(name, whoInput!))))}
      data-testid="app-who-works-form"
    >
      {#key `${a.name}/${job?.name ?? ""}`}<AppWhoWorks name={job?.description ?? title} value={whoInput} limits={limitsOf(a, job)} unattended={runBy} onchange={(w) => (whoInput = w)} />{/key}
      <div class="flex items-center justify-end gap-2">
        {#if job?.own}
          <Button variant="ghost" class="mr-auto" onclick={() => saved(() => api.unsetJobWhoWorks(name, job.name))} data-testid="app-job-who-back-dialog"><Undo2 />Back to {title}'s</Button>
        {/if}
        <Button variant="outline" onclick={() => (editOpen = false)}>Cancel</Button>
        <Button type="submit" disabled={!whoInput || sameWho(whoInput, current)} data-testid="app-who-works-save">Save</Button>
      </div>
    </form>
  {:else if editing?.kind === "secret"}
    {@const s = editing.need}
    <form class="space-y-3" onsubmit={(e) => (e.preventDefault(), saved(() => api.setAppSecret(name, s.name, secretInput.trim())))}>
      <Input type="password" autocomplete="off" placeholder={s.set ? "its new value" : "its value"} aria-label={`value of ${s.name}`} bind:value={secretInput} />
      <div class="flex items-center justify-end gap-2">
        {#if s.set}
          <Button variant="ghost" class="mr-auto text-danger hover:text-danger" onclick={() => saved(() => api.unsetAppSecret(name, s.name))} data-testid="app-secret-forget">Forget it</Button>
        {/if}
        <Button variant="outline" onclick={() => (editOpen = false)}>Cancel</Button>
        <Button type="submit" disabled={!secretInput.trim()} data-testid="app-secret-save">Save</Button>
      </div>
    </form>
  {/if}
</Dialog>

<Dialog
  bind:open={confirmOpen}
  title={confirming === "uninstall"
    ? `Uninstall ${title}?`
    : confirming === "rollback"
      ? `Go back to ${app?.previous?.version}?`
      : confirming === "update"
        ? `Update to ${app?.offered?.version}?`
        : `Deploy ${app?.source.version}?`}
  testid="app-confirm"
>
  {#if app}
    {@const a = app}
    <div class="space-y-3">
      {#if confirming === "uninstall"}
        <p>These are deleted with it:</p>
        <ul class="list-disc space-y-0.5 pl-5 text-muted-foreground">
          <li>its code and installed versions{a.current ? ` (${[a.current.version, a.previous?.version].filter(Boolean).join(", ")})` : ""}</li>
          <li class="text-danger" data-testid="app-uninstall-data">the data {title} keeps for itself: it cannot be brought back</li>
          {#if a.jobs?.length}<li>its jobs' runs, and what their programs kept for {title}</li>{/if}
          {#if schedules.length}<li>what runs by itself: {schedules.map((x) => x.name).join(", ")}</li>{/if}
        </ul>
        {@const given = (a.files ?? []).filter((f) => f.path)}
        <p class="rounded-lg bg-muted px-3 py-2 text-muted-foreground">
          {#if given.length}Kept: your folders, as they are ({given.map((f) => f.path).join(", ")}).{:else}Nothing of yours is touched.{/if} Export it first to keep its code.
        </p>
      {:else if confirming === "rollback"}
        <p>Its data goes back to how it was before {a.current?.version} was deployed: what changed in it since is lost. Your folders stay as they are.</p>
      {:else if confirming === "update"}
        <p>{a.offered?.version} may reach more than before:</p>
        <ul class="list-disc space-y-0.5 pl-5 text-muted-foreground">
          {#each a.offered?.addedNeeds ?? [] as added (added)}<li>{addedWords(added, a)}</li>{/each}
        </ul>
      {:else if confirming === "deploy"}
        <p>{a.source.version} may reach more than before:</p>
        <ul class="list-disc space-y-0.5 pl-5 text-muted-foreground">
          {#each a.source.addedNeeds ?? [] as added (added)}<li>{addedWords(added, a)}</li>{/each}
        </ul>
      {/if}
      <div class="flex justify-end gap-2 pt-1">
        <Button variant="outline" onclick={() => (confirmOpen = false)}>Cancel</Button>
        {#if confirming === "uninstall"}
          <Button variant="destructive" onclick={() => confirmed(a)} data-testid="app-confirm-go"><Trash />Uninstall {title}</Button>
        {:else}
          <Button onclick={() => confirmed(a)} data-testid="app-confirm-go"
            >{confirming === "rollback" ? `Go back to ${a.previous?.version}` : confirming === "update" ? `Update to ${a.offered?.version}` : `Deploy ${a.source.version}`}</Button
          >
        {/if}
      </div>
    </div>
  {/if}
</Dialog>
