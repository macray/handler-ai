<script lang="ts">
  import PinButton from "../components/PinButton.svelte";
  // An app's page (contract H, apps design), `#/apps/<name>`: what it is and Open
  // first (a new version to deploy said there); then what you gave it (its folders, agents and
  // secrets: each its value and Change…, a dialog changes it), its actions, what you can ask it (H.12, each
  // with Try), what runs by itself (its suggested automations), Under the hood folded (its code,
  // the version before it, its parts H.14, its log), and Uninstall last; beside them what it may touch
  // (its permissions, always shown) and the phones it opens on. Deploying is only ever done here or
  // with `handler app deploy`: agents write apps, people install them. Its code is kept by Handler
  // (H.15): Export gives it as one file; Change it opens the App creator on a draft of it
  // (lib/drafts.ts), and while one waits a bar says so (Throw away, Continue, Use it).
  import AppWindow from "@lucide/svelte/icons/app-window";
  import Bot from "@lucide/svelte/icons/bot";
  import CalendarClock from "@lucide/svelte/icons/calendar-clock";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import CircleCheck from "@lucide/svelte/icons/circle-check";
  import Clock from "@lucide/svelte/icons/clock";
  import FileText from "@lucide/svelte/icons/file-text";
  import Folder from "@lucide/svelte/icons/folder";
  import History from "@lucide/svelte/icons/history";
  import KeyRound from "@lucide/svelte/icons/key-round";
  import Lock from "@lucide/svelte/icons/lock";
  import Play from "@lucide/svelte/icons/play";
  import Trash from "@lucide/svelte/icons/trash-2";
  import Zap from "@lucide/svelte/icons/zap";
  import ExternalLink from "@lucide/svelte/icons/external-link";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import Download from "@lucide/svelte/icons/download";
  import FilePenLine from "@lucide/svelte/icons/file-pen-line";
  import Upload from "@lucide/svelte/icons/upload";
  import WandSparkles from "@lucide/svelte/icons/wand-sparkles";
  import Eye from "@lucide/svelte/icons/eye";
  import ActionTry from "../components/ActionTry.svelte";
  import Dialog from "../components/Dialog.svelte";
  import FolderPicker from "../components/FolderPicker.svelte";
  import LoadingCards from "../components/LoadingCards.svelte";
  import HelperCard from "../components/HelperCard.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import StatusBadge from "../components/StatusBadge.svelte";
  import When from "../components/When.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { appOf } from "../lib/agents";
  import { agentChoice, reaches, suggested } from "../lib/apps";
  import { runtime } from "../lib/runtime.svelte";
  import { fromSourceWords } from "../lib/sources";
  import { api } from "../lib/api";
  import { whenSentence } from "../lib/automations";
  import type { Agent, App, AppAgentNeed, AppAction, AppFileNeed, AppSecret, AutomationView, DraftCopy, AppManifestSuggestedAutomation, Session } from "../lib/contracts.gen";
  import { continueDraft, copyLabel, draftsOf, openDraft, startDraft, throwAway, useDraft } from "../lib/drafts";
  import { href, navigate } from "../lib/router.svelte";
  import { projects } from "../lib/projects.svelte";
  import { remote } from "../lib/remote.svelte";

  let { name }: { name: string } = $props();
  let app = $state<App | null>(null);
  let error = $state<string | null>(null);
  let busy = $state<string | null>(null); // what it is doing ("deploying…")
  let problem = $state<string | null>(null);
  let creatorCard = $state(false); // no App creator yet: its set-up card
  let log = $state<string | null>(null); // its log, shown under the hood
  let agents = $state<Agent[]>([]); // to name the agents its needs are given
  let automations = $state<AutomationView[]>([]); // which of its suggestions are made
  let draft = $state<Session | null>(null); // a draft of its code waiting (H.15)
  let copies = $state<DraftCopy[] | null>(null); // the draft opened (H.16): what it works on
  let projectNames = $state(new Map<string, string>());
  let unfolded = $state(false); // Under the hood shown
  // its parts (H.14): the agents set up for it, what runs them by itself
  const parts = $derived(agents.filter((x) => appOf(x) === name));
  const schedules = $derived(automations.filter((x) => parts.some((p) => p.id === x.agentId) || x.definition?.app === name));
  let trying = $state<AppAction | null>(null); // the action of the Try dialog
  let tryOpen = $state(false);
  // the need being changed, in its dialog, and what is typed or picked there
  let editing = $state<{ kind: "folder"; need: AppFileNeed } | { kind: "agent"; need: AppAgentNeed } | { kind: "secret"; need: AppSecret } | null>(null);
  let editOpen = $state(false);
  let folderInput = $state("");
  let agentInput = $state("");
  let secretInput = $state("");
  // what asks to be confirmed, in a dialog: going back a version, deploying one that reaches more, removing
  let confirming = $state<"rollback" | "deploy" | "uninstall" | null>(null);
  let confirmOpen = $state(false);
  const agentName = (id: string): string => {
    const a = agents.find((x) => x.id === id);
    return a ? agentChoice(a, projectNames) : id;
  };

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
      [app, agents, automations, list] = await Promise.all([api.app(name), api.agents(), api.automations().catch(() => []), api.sessions().catch(() => [])]);
      draft = draftsOf(list, name)[0] ?? null;
      error = null;
    } catch (e) {
      error = (e as Error).message;
    }
  }

  $effect(() => {
    api.projects().then((list) => (projectNames = new Map(list.map((p) => [p.id, p.name]))), () => {});
    void load();
    const timer = setInterval(load, 5000); // started and stopped backends (idle timeout)
    return () => clearInterval(timer);
  });

  async function act(doing: string, action: () => Promise<unknown>): Promise<void> {
    busy = doing;
    problem = null;
    try {
      await action();
    } catch (e) {
      problem = (e as Error).message;
    } finally {
      busy = null;
      await load();
      if (log !== null) await showLog();
    }
  }

  const deployable = $derived(!!app && !app.source.error && !!app.source.version && app.source.version !== app.current?.version);

  function deploy(a: App): void {
    if (a.source.addedNeeds?.length) ask("deploy");
    else void act("deploying (tests, health check)…", () => api.deployApp(a.name));
  }

  function ask(what: "rollback" | "deploy" | "uninstall"): void {
    confirming = what;
    confirmOpen = true;
  }

  function confirmed(a: App): void {
    confirmOpen = false;
    if (confirming === "rollback") void act("going back…", () => api.rollbackApp(a.name));
    else if (confirming === "deploy") void act("deploying (tests, health check)…", () => api.deployApp(a.name));
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

  async function showLog(): Promise<void> {
    try {
      log = (await api.appLog(name)).text;
    } catch (e) {
      problem = (e as Error).message;
    }
  }

  function change(e: NonNullable<typeof editing>): void {
    editing = e;
    folderInput = e.kind === "folder" ? (e.need.path ?? "") : "";
    agentInput = e.kind === "agent" && e.need.agentId && !e.need.problem ? e.need.agentId : "";
    secretInput = "";
    editOpen = true;
  }

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

  /** The automation made from a suggestion: its results open this app, it runs the agent given. */
  function madeFrom(a: App, s: AppManifestSuggestedAutomation): AutomationView | undefined {
    const given = a.agents?.find((x) => x.name === s.run.agent)?.agentId;
    return automations.find((x) => x.definition?.app === a.name && !!given && x.agentId === given);
  }

  function make(a: App, s: AppManifestSuggestedAutomation): void {
    const agentId = a.agents?.find((x) => x.name === s.run.agent && !x.problem)?.agentId;
    if (!agentId) return;
    const { name: made, definition } = suggested(a, s); // off: turning it on is yours
    void act("making the automation…", () => api.createAutomation(made, { definition, agentId, enable: false }));
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

<PageHeader width="max-w-5xl" title={name} parent={{ label: "Apps", href: href({ view: "apps" }) }}>
  {#snippet actions()}
    {#if app}
      <PinButton kind="app" id={name} label={name} withText />
      {#if !draft}
        <Button
          size="sm"
          variant="ghost"
          title={app.fromSource ? "With the App creator, on a draft of its code: once used, it is yours (its source no longer offers it a new version)" : "With the App creator, on a draft of its code"}
          onclick={() => act("opening the App creator…", async () => (creatorCard = !(await startDraft(name))))}
          data-testid="app-improve"><WandSparkles />Change it</Button
        >
      {/if}
      <Button size="sm" variant="ghost" title="Its code as one file, to share or keep" onclick={exportIt} data-testid="app-export"><Download />Export</Button>
    {/if}
  {/snippet}
</PageHeader>
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-5xl px-8 py-10" data-testid="app-page">
    {#if error}<p class="text-sm text-danger" data-testid="apps-error">{error}</p>{/if}
    {#if creatorCard}
      <div class="mb-8">
        <HelperCard need="app-creator" title={`Change ${name}`} onready={() => ((creatorCard = false), void act("opening the App creator…", () => startDraft(name)))} />
      </div>
    {/if}
    {#if !app}
      {#if !error}<LoadingCards count={2} height="h-24" />{/if}
    {:else}
      {@const a = app}
      {@const filesLeft = (a.files ?? []).filter((f) => !f.path).length + (a.secrets ?? []).filter((s) => !s.set).length}
      {@const left = filesLeft + (a.agents ?? []).filter((n) => !n.agentId || n.problem).length}
      {@const needs = (a.files?.length ?? 0) + (a.agents?.length ?? 0) + (a.secrets?.length ?? 0)}
      <div class="flex flex-wrap items-center gap-4">
        <span class="flex size-14 shrink-0 items-center justify-center rounded-2xl {a.state === 'failed' ? 'bg-danger/10 text-danger' : 'bg-primary/10 text-primary'}"><AppWindow class="size-7" /></span>
        <div class="min-w-0 flex-1 space-y-1.5">
          {#if a.description ?? a.source.description}<p class="text-sm text-muted-foreground">{a.description ?? a.source.description}</p>{/if}
          <p class="flex flex-wrap items-center gap-2 text-xs">
            <span class="fact">{fromSourceWords(a.fromSource, []) ?? "made by you"} · {a.current ? a.current.version : "not installed"}</span>
            {#if a.current && a.state === "failed"}<StatusBadge status={a.state} />{/if}
            {#if left}
              <span class="inline-flex items-center gap-1 rounded-md bg-warn/10 px-1.5 py-0.5 text-warn" data-testid="app-needs-missing"
                ><TriangleAlert class="size-3" />{left === 1 ? "one thing" : `${left} things`} to give it, below</span
              >
            {/if}
          </p>
        </div>
        <div class="flex shrink-0 items-center gap-2">
          {#if busy}
            <span class="fact">{busy}</span>
          {:else if !a.current}
            <Button href={href({ view: "install-app", name: a.name })} data-testid="app-install"><Upload />Install</Button>
          {:else}
            {#if deployable}
              <Button variant="outline" onclick={() => deploy(a)} data-testid="app-deploy"><Upload />Deploy {a.source.version}</Button>
            {/if}
            <Button disabled={filesLeft > 0} title={filesLeft ? "Give it what it needs first" : undefined} onclick={() => open(a)} data-testid="app-open"><ExternalLink />Open {a.name}</Button>
          {/if}
        </div>
      </div>
      {#if a.source.error}
        <p class="mt-3 text-sm text-danger">Its source: {a.source.error}</p>
      {:else if a.current && deployable && a.source.addedNeeds?.length}
        <p class="mt-3 inline-flex items-center gap-1.5 rounded-md bg-warn/10 px-2 py-1 text-xs text-warn">
          <TriangleAlert class="size-3 shrink-0" />{a.source.version} may reach more than before: {a.source.addedNeeds.join(", ")}
        </p>
      {/if}
      {#if a.error}<p class="mt-3 text-sm text-danger">{a.error}</p>{/if}
      {#if draft}
        {@const d = draft}
        <div class="mt-5 flex flex-wrap items-center gap-3 rounded-xl bg-primary/10 px-4 py-3 text-sm" data-testid="app-draft">
          <FilePenLine class="size-4 shrink-0 text-primary" />
          <p class="min-w-0 flex-1"><b class="font-semibold">A change is waiting:</b> “{d.title ?? "untitled"}”, with the App creator. {a.name} as you use it is untouched until you use it.</p>
          <Button size="sm" variant="ghost" disabled={!!busy} onclick={() => act("throwing it away…", () => throwAway(d))} data-testid="draft-throw">Throw away</Button>
          <Button size="sm" variant="outline" onclick={() => continueDraft(d)} data-testid="draft-continue"><WandSparkles />Continue</Button>
          <Button
            size="sm"
            variant="outline"
            disabled={!!busy}
            title="The changed app, in a new tab, on copies of its data and folders"
            onclick={() => act("opening the draft…", async () => (copies = await openDraft(d.id)))}
            data-testid="draft-open"><Eye />Open the draft</Button
          >
          <Button size="sm" disabled={!!busy} onclick={() => act("using it (tests, health check)…", () => useDraft(d.id))} data-testid="draft-use">Use it</Button>
          {#if copies}
            <p class="basis-full text-xs text-muted-foreground" data-testid="draft-copies">Opened in a new tab, on copies: {copies.map(copyLabel).join(" · ")}. Opening it again takes new copies.</p>
          {/if}
        </div>
      {/if}
      {#if problem}<p class="mt-3 text-sm text-danger" data-testid="app-problem">{problem}</p>{/if}

      <div class="mt-8 grid items-start gap-8 lg:grid-cols-[1fr_300px]">
        <div class="min-w-0 space-y-8 text-sm">
          {#if needs}
            <section class="space-y-2" data-testid="app-needs">
              <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <h2 class="font-semibold">What you gave it</h2>
                {#if left}
                  <span class="inline-flex items-center gap-1 self-center rounded-md bg-warn/10 px-1.5 py-0.5 text-xs text-warn"><TriangleAlert class="size-3" />{left} to give</span>
                {:else}
                  <span class="inline-flex items-center gap-1 self-center text-xs text-ok" data-testid="app-needs-set"><CircleCheck class="size-3.5" />all set</span>
                {/if}
                <span class="text-xs text-muted-foreground">what {a.name} asks for; you choose what you give it</span>
              </div>
              <ul class="divide-y overflow-hidden rounded-[10px] border bg-card shadow-panel">
                {#each a.files ?? [] as f (f.name)}
                  {@const home = f.path ? projects.list.find((p) => p.folder === f.path) : undefined}
                  <li class="flex items-center gap-3 px-4 py-3 {f.path ? '' : 'bg-warn/10'}" data-testid="app-need-folder">
                    <span class="flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">{#if f.file}<FileText class="size-4" />{:else}<Folder class="size-4" />{/if}</span>
                    <div class="min-w-0 flex-1">
                      <p class="text-xs text-muted-foreground">{f.description ?? (f.file ? "A file" : "A folder")} · {f.mode === "rw" ? "it reads and writes it" : "it reads it"}</p>
                      {#if f.path}
                        <p class="truncate font-mono text-[13px] font-medium" title={f.path}>{f.path}</p>
                        {#if f.file}
                          <p class="text-xs text-muted-foreground" data-testid="app-need-file-hint">
                            {name} sees what you change in this file. If your editor replaces the file when it saves, {name} sees your changes after a restart.
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
                {#each a.agents ?? [] as n (n.name)}
                  {@const given = !!n.agentId && !n.problem}
                  <li class="flex items-center gap-3 px-4 py-3 {given ? '' : 'bg-warn/10'}" data-testid="app-need-agent">
                    <span class="flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground"><Bot class="size-4" /></span>
                    <div class="min-w-0 flex-1">
                      <p class="text-xs text-muted-foreground">Its agent: {n.description ?? "an agent"}</p>
                      {#if given && n.agentId}
                        <a class="font-medium text-link hover:underline" href={href({ view: "agent", id: n.agentId })} data-testid="app-need-agent-given">{agentName(n.agentId)}</a>
                      {:else if n.agentId}
                        <p class="text-danger">{agentName(n.agentId)}: {n.problem}</p>
                      {:else if n.problem}
                        <p class="text-danger">{n.problem}</p>
                      {:else}
                        <p class="font-medium text-warn">Not given yet</p>
                      {/if}
                    </div>
                    <Button size="sm" variant={given ? "outline" : "default"} disabled={!!busy} onclick={() => change({ kind: "agent", need: n })} data-testid="app-need-change"
                      >{given ? "Change…" : "Choose an agent…"}</Button
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
            </section>
          {/if}

          {#if a.actions?.length}
            <section class="space-y-2" data-testid="app-actions">
              <div class="flex items-center gap-3">
                <h2 class="font-semibold">What you can ask it</h2>
                <label class="ml-auto flex cursor-pointer items-center gap-2 text-xs text-muted-foreground" title="Off: you try its actions here only">
                  Offered in Ask, here and on your phones
                  <input type="checkbox" class="size-4 accent-primary" checked={a.askable} disabled={!!busy} onchange={(e) => act("saving…", () => api.setAppAskable(a.name, e.currentTarget.checked))} data-testid="app-askable" />
                </label>
              </div>
              <ul class="divide-y overflow-hidden rounded-[10px] border bg-card shadow-panel">
                {#each a.actions as action (action.name)}
                  <li class="flex flex-wrap items-center gap-3 px-4 py-3" data-testid="app-action">
                    <div class="min-w-0 flex-1">
                      <p class="font-medium">{action.description}</p>
                      {#if action.examples?.length}<p class="text-muted-foreground">“{action.examples[0]}”</p>{/if}
                    </div>
                    {#if action.by === "code"}
                      <span class="inline-flex items-center gap-1 rounded-full bg-ok/10 px-2 py-0.5 text-xs text-ok" title="Done by its code"><Zap class="size-3" />instant</span>
                    {:else}
                      <span class="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground" title="Done by its agent"><Clock class="size-3" />takes a while</span>
                    {/if}
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={!a.current}
                      title={a.current ? undefined : "Install it first"}
                      onclick={() => ((trying = action), (tryOpen = true))}
                      data-testid="app-action-try"><Play />Try</Button
                    >
                  </li>
                {/each}
              </ul>
              <p class="text-xs text-muted-foreground">Instant: done by its code. Takes a while: its agent works on it, from seconds to minutes as the request needs, and its answer also comes to your Inbox.</p>
            </section>
          {/if}

          {#if a.suggests?.length}
            <section class="space-y-2" data-testid="app-suggests">
              <h2 class="font-semibold">Runs by itself</h2>
              <p class="text-xs text-muted-foreground">What the app proposes to run on its own. Made here, each is off until you turn it on; its results open the app.</p>
              <ul class="divide-y overflow-hidden rounded-[10px] border bg-card shadow-panel">
                {#each a.suggests as s, i (i)}
                  {@const made = madeFrom(a, s)}
                  {@const given = a.agents?.find((x) => x.name === s.run.agent && x.agentId && !x.problem)}
                  <li class="flex flex-wrap items-center gap-2 px-4 py-3" data-testid="app-suggest">
                    <div class="min-w-0 flex-1">
                      <p class="font-medium">{s.description}</p>
                      <p class="fact">{whenSentence({ apiVersion: "handler.automation/v1", when: s.when, run: { agent: s.run.agent } })}</p>
                    </div>
                    {#if made}
                      <a class="text-link hover:underline" href={href({ view: "automation", name: made.name })} data-testid="app-suggest-made">{made.name} ({made.enabled ? "on" : "off"})</a>
                    {:else if given}
                      <Button size="sm" variant="outline" disabled={!!busy} onclick={() => make(a, s)} data-testid="app-suggest-make">Make it</Button>
                    {:else}
                      <span class="text-xs text-muted-foreground">Give it its agent first.</span>
                    {/if}
                  </li>
                {/each}
              </ul>
            </section>
          {/if}

          <section class="space-y-2" data-testid="app-how">
            <button type="button" class="flex cursor-pointer items-baseline gap-2" aria-expanded={unfolded} onclick={() => (unfolded = !unfolded)} data-testid="app-how-toggle">
              <ChevronRight class="size-3.5 self-center transition-transform {unfolded ? 'rotate-90' : ''}" />
              <h2 class="font-semibold">Under the hood</h2>
              <span class="text-xs text-muted-foreground">its code, versions, parts and log</span>
            </button>
            {#if !unfolded}
              <button type="button" class="flex w-full cursor-pointer items-center gap-3 rounded-[10px] border bg-card px-4 py-3 text-left text-muted-foreground shadow-panel hover:bg-muted/50" onclick={() => (unfolded = true)}>
                <span class="min-w-0 flex-1 truncate"
                  >{[
                    a.current ? `its code ${a.current.version}, ${stateWords(a)}` : "not installed yet",
                    a.previous && `${a.previous.version} kept`,
                    parts.length && plural(parts.length, "agent"),
                    schedules.length && plural(schedules.length, "schedule"),
                  ]
                    .filter(Boolean)
                    .join(" · ")}</span
                >
                <span class="text-xs text-link">Show</span>
              </button>
            {:else}
              <div class="overflow-hidden rounded-[10px] border bg-card shadow-panel">
                <ul class="divide-y">
                  <li class="flex flex-wrap items-center gap-3 px-4 py-3">
                    <AppWindow class="size-4 text-muted-foreground" />
                    <div class="min-w-0 flex-1">
                      <p class="font-medium">{a.current ? `Its code, ${a.current.version}` : "Not installed yet"}</p>
                      {#if a.current}
                        <p class="text-xs text-muted-foreground">deployed <When at={a.current.deployedAt} /> · {stateWords(a)} · kept by Handler{a.fromSource ? `, ${fromSourceWords(a.fromSource, [])}: Apps offers its next version` : ""}</p>
                      {/if}
                    </div>
                    {#if a.state === "running" && !busy}
                      <Button size="sm" variant="ghost" onclick={() => act("stopping…", () => api.stopApp(a.name))}>Stop</Button>
                    {/if}
                  </li>
                  {#if a.previous}
                    <li class="flex flex-wrap items-center gap-3 px-4 py-3">
                      <History class="size-4 text-muted-foreground" />
                      <div class="min-w-0 flex-1">
                        <p class="font-medium">{a.previous.version}, the one before</p>
                        <p class="text-xs text-muted-foreground">Going back brings its data back as it was then; your folders stay as they are.</p>
                      </div>
                      <Button size="sm" variant="ghost" disabled={!!busy} onclick={() => ask("rollback")} data-testid="app-rollback">Go back to {a.previous.version}…</Button>
                    </li>
                  {/if}
                  {#each parts as p (p.id)}
                    <li class="flex items-center gap-3 px-4 py-3" data-testid="app-part">
                      <Bot class="size-4 text-muted-foreground" />
                      <div class="min-w-0 flex-1"><p class="font-medium">{p.name}</p><p class="truncate text-xs text-muted-foreground">{p.description ?? ""}{p.scope ? `${p.description ? " · " : ""}works in ${p.scope}` : ""}</p></div>
                      <Button size="sm" variant="ghost" href={href({ view: "agent", id: p.id })}>Open</Button>
                    </li>
                  {/each}
                  {#each schedules as x (x.name)}
                    <li class="flex items-center gap-3 px-4 py-3">
                      <CalendarClock class="size-4 text-muted-foreground" />
                      <div class="min-w-0 flex-1"><p class="font-medium">{x.name}</p><p class="text-xs text-muted-foreground">{x.enabled ? "on" : "off"}</p></div>
                      <Button size="sm" variant="ghost" href={href({ view: "automation", name: x.name })}>Open</Button>
                    </li>
                  {/each}
                  <li class="space-y-2 px-4 py-3">
                    <div class="flex items-center gap-3">
                      <FileText class="size-4 text-muted-foreground" />
                      <div class="min-w-0 flex-1"><p class="font-medium">Its log</p><p class="text-xs text-muted-foreground">what its code printed, newest last</p></div>
                      <Button size="sm" variant="ghost" onclick={() => (log === null ? showLog() : (log = null))} data-testid="app-log-toggle">{log === null ? "Show" : "Hide"}</Button>
                    </div>
                    {#if log !== null}<pre class="ml-7 max-h-72 overflow-auto rounded-lg bg-muted p-3 font-mono text-xs whitespace-pre-wrap" data-testid="app-log">{log || "(empty)"}</pre>{/if}
                  </li>
                </ul>
                <p class="flex items-center gap-1.5 bg-muted px-4 py-2.5 text-xs text-muted-foreground"><Lock class="size-3" />Its parts run only through {a.name}, and are uninstalled with it.</p>
              </div>
            {/if}
          </section>

          <section class="flex flex-wrap items-center gap-4 rounded-[10px] border bg-card px-4 py-3.5 shadow-panel" data-testid="app-uninstall-card">
            <div class="min-w-0 flex-1">
              <h2 class="font-semibold">Uninstall {a.name}</h2>
              <p class="text-xs text-muted-foreground">
                Its versions, the data it keeps for itself{parts.length ? `, ${parts.length === 1 ? "its agent" : "its agents"}` : ""}{schedules.length ? " and what runs by itself" : ""} go. Your folders stay.
              </p>
            </div>
            <Button size="sm" variant="outline" class="border-danger/40 text-danger hover:bg-danger/5 hover:text-danger" disabled={!!busy} onclick={() => ask("uninstall")} data-testid="app-uninstall"
              ><Trash />Uninstall…</Button
            >
          </section>
        </div>

        <aside class="space-y-5 text-sm">
          <section class="space-y-2 rounded-[10px] border bg-card p-4 shadow-panel" data-testid="app-reaches">
            <h2 class="font-semibold">What it may touch</h2>
            {#if a.current}
              <ul class="space-y-1.5 text-muted-foreground">
                {#each reaches(a.current.needs, a, agentName) as line (line)}<li>{line}</li>{/each}
              </ul>
              {#if runtime.last?.supports?.limits === false}
                <p class="text-xs text-warn" data-testid="app-no-limits">
                  Its memory and CPU limits are not applied on this computer: it can use all of them (Settings → Sandboxes says why).
                </p>
              {/if}
              <p class="text-xs text-muted-foreground">What {a.current.version} asked for when you deployed it; a version that asks for more says so before it is deployed.</p>
            {:else}
              <p class="text-muted-foreground">Said on its install page, before anything is installed.</p>
            {/if}
          </section>

          {#if a.current}
            <section class="space-y-2 rounded-[10px] border bg-card p-4 shadow-panel" data-testid="app-persons">
              <h2 class="font-semibold">On phones</h2>
              <p class="text-xs text-muted-foreground">It always opens on this computer. Also on the paired phones of the people ticked here (Settings → Your phone).</p>
              <div class="flex flex-wrap gap-2">
                {#each [...new Set([...Object.keys(devicesOf), ...(a.persons ?? [])])].sort() as person (person)}
                  {@const names = devicesOf[person] ?? []}
                  <label
                    class="flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 has-checked:border-primary/60 has-checked:bg-primary/5"
                    title={names.length ? names.join(", ") : "no paired phone"}
                  >
                    <input
                      type="checkbox"
                      class="accent-primary"
                      checked={a.persons?.includes(person) ?? false}
                      disabled={!!busy}
                      onchange={(e) => togglePerson(a, person, e.currentTarget.checked)}
                    />
                    {person === "owner" ? "you" : person}
                    <span class="fact">{plural(names.length, "phone")}</span>
                  </label>
                {/each}
              </div>
            </section>
          {/if}
        </aside>
      </div>
    {/if}
  </div>
</div>

<Dialog bind:open={tryOpen} title={trying ? `Try: ${trying.description}` : ""} wide testid="action-try-dialog">
  {#if trying}{#key trying.name}<ActionTry app={name} action={trying} />{/key}{/if}
</Dialog>

<Dialog
  bind:open={editOpen}
  wide={editing?.kind === "folder"}
  title={editing?.kind === "folder" ? (editing.need.description ?? "A folder") : editing?.kind === "agent" ? `Its agent: ${editing.need.description ?? editing.need.name}` : editing ? `The secret ${editing.need.name}` : ""}
  description={editing?.kind === "folder"
    ? `${name} ${editing.need.mode === "rw" ? "reads and writes" : "reads"} this folder.`
    : editing?.kind === "secret"
      ? "Kept by Handler, never in the app's folder. Changing it restarts the app."
      : undefined}
  testid="app-need-dialog"
>
  {#if editing?.kind === "folder"}
    {@const f = editing.need}
    <form class="space-y-3" onsubmit={(e) => (e.preventDefault(), saved(() => api.setAppFile(name, f.name, folderInput.trim())))}>
      <FolderPicker id={`app-folder-${f.name}`} bind:value={folderInput} />
      {#if f.path}<p class="text-xs text-muted-foreground">What is in {f.path} is not moved: {name} works on what the new folder holds.</p>{/if}
      <div class="flex justify-end gap-2">
        <Button variant="outline" onclick={() => (editOpen = false)}>Cancel</Button>
        <Button type="submit" disabled={!folderInput.trim().startsWith("/") || folderInput.trim() === f.path} data-testid="app-need-folder-save">Give this folder</Button>
      </div>
    </form>
  {:else if editing?.kind === "agent"}
    {@const n = editing.need}
    {@const folderMissing = !!n.worksIn && !app?.files?.find((f) => f.name === n.worksIn)?.path}
    <form class="space-y-3" onsubmit={(e) => (e.preventDefault(), saved(() => api.setAppAgent(name, n.name, agentInput)))}>
      {#if n.fits?.length}
        <label class="block space-y-1.5">
          <span class="font-medium">One of your agents that fits</span>
          <select class="h-9 w-full rounded-lg border bg-background px-2 text-sm" bind:value={agentInput} data-testid="app-need-agent-choice">
            <option value="" disabled>Choose…</option>
            {#each n.fits as id (id)}<option value={id}>{agentName(id)}</option>{/each}
          </select>
        </label>
      {:else}
        <p class="text-muted-foreground">None of your agents fits it yet.</p>
      {/if}
      {#if n.definition}
        {#if folderMissing}
          <p class="text-xs text-muted-foreground">Or set up a new one, once its folder is given.</p>
        {:else}
          <p class="text-xs text-muted-foreground">
            Or <a class="text-link hover:underline" href={href({ view: "edit-ad-hoc", app: name, need: n.name })} data-testid="app-need-agent-setup">set up a new one</a> for it.
          </p>
        {/if}
      {/if}
      <div class="flex justify-end gap-2">
        <Button variant="outline" onclick={() => (editOpen = false)}>Cancel</Button>
        {#if n.fits?.length}<Button type="submit" disabled={!agentInput || (agentInput === n.agentId && !n.problem)} data-testid="app-need-agent-save">Give this agent</Button>{/if}
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
  title={confirming === "uninstall" ? `Uninstall ${name}?` : confirming === "rollback" ? `Go back to ${app?.previous?.version}?` : `Deploy ${app?.source.version}?`}
  testid="app-confirm"
>
  {#if app}
    {@const a = app}
    <div class="space-y-3">
      {#if confirming === "uninstall"}
        <p>These are deleted with it:</p>
        <ul class="list-disc space-y-0.5 pl-5 text-muted-foreground">
          <li>its code and installed versions{a.current ? ` (${[a.current.version, a.previous?.version].filter(Boolean).join(", ")})` : ""}</li>
          <li class="text-danger" data-testid="app-uninstall-data">the data {name} keeps for itself: it cannot be brought back</li>
          {#if parts.length}<li>{parts.length === 1 ? "its agent" : "its agents"} {parts.map((x) => x.name).join(", ")}</li>{/if}
          {#if schedules.length}<li>what runs by itself: {schedules.map((x) => x.name).join(", ")}</li>{/if}
        </ul>
        {@const given = (a.files ?? []).filter((f) => f.path)}
        <p class="rounded-lg bg-muted px-3 py-2 text-muted-foreground">
          {#if given.length}Kept: your folders, as they are ({given.map((f) => f.path).join(", ")}).{:else}Nothing of yours is touched.{/if} Export it first to keep its code.
        </p>
      {:else if confirming === "rollback"}
        <p>Its data goes back to how it was before {a.current?.version} was deployed: what changed in it since is lost. Your folders stay as they are.</p>
      {:else if confirming === "deploy"}
        <p>{a.source.version} may reach more than before:</p>
        <ul class="list-disc space-y-0.5 pl-5 text-muted-foreground">
          {#each a.source.addedNeeds ?? [] as added (added)}<li>{added}</li>{/each}
        </ul>
        {#if a.source.addedNeeds?.some((n) => n.startsWith("agent "))}<p class="text-muted-foreground">It may start runs of those agents whenever you use it, and read their results.</p>{/if}
      {/if}
      <div class="flex justify-end gap-2 pt-1">
        <Button variant="outline" onclick={() => (confirmOpen = false)}>Cancel</Button>
        {#if confirming === "uninstall"}
          <Button variant="destructive" onclick={() => confirmed(a)} data-testid="app-confirm-go"><Trash />Uninstall {name}</Button>
        {:else}
          <Button onclick={() => confirmed(a)} data-testid="app-confirm-go">{confirming === "rollback" ? `Go back to ${a.previous?.version}` : `Deploy ${a.source.version}`}</Button>
        {/if}
      </div>
    </div>
  {/if}
</Dialog>
