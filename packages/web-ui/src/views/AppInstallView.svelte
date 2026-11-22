<script lang="ts">
  // Installing an app, on one page (H.2, the agents set-up page's layout; E6: it is set up here
  // only): where it keeps its data (its folder, picked from suggestions: a new one in a work
  // folder or in your notes, made at Install, or one you have named after it; or another; a
  // project's folder lists the app from its side, H.14),
  // its other folders (suggested the same way), who works on its jobs (H.2: one Who works for the app, required when it
  // has jobs; the model alone greyed when a job reaches folders, schemas or hosts), its secrets,
  // what you can ask it, what runs by itself (its suggestions, each switched on unless the app
  // marks it optional: Install makes and turns on those left on; off and disabled, saying why,
  // while who works for it is an account whose terms refuse runs nobody follows, I.7), who opens
  // it on a phone; beside them what it will be allowed to do.
  // Install does what is not done yet, in order, each through its own request (its folders, who
  // works on its jobs, its secrets, what runs by itself), then deploys and ends on the app's page. Stopped midway,
  // the page opened again shows what is done and goes on.
  import { ask } from "../lib/ask.svelte";
  import Check from "@lucide/svelte/icons/check";
  import Folder from "@lucide/svelte/icons/folder";
  import FolderOpen from "@lucide/svelte/icons/folder-open";
  import ShieldCheck from "@lucide/svelte/icons/shield-check";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import FolderPicker from "../components/FolderPicker.svelte";
  import AppWhoWorks from "../components/AppWhoWorks.svelte";
  import Switch from "../components/Switch.svelte";
  import { sameModel } from "../lib/access";
  import PageHeader from "../components/PageHeader.svelte";
  import { fromSourceWords } from "../lib/sources";
  import { api } from "../lib/api";
  import { appTitle, dataNeed, folderSuggestions, jobLimits, reaches, stillToChoose, suggested, whoWorksWords, type FolderSuggestion } from "../lib/apps";
  import { whenSentence } from "../lib/automations";
  import { homePath } from "../lib/text";
  import type { AccountInfo, App, AppManifestSuggestedAutomation, AutomationView, DirectoryEntry, WhoWorks } from "../lib/contracts.gen";
  import { projects } from "../lib/projects.svelte";
  import { remote } from "../lib/remote.svelte";
  import { href, navigate } from "../lib/router.svelte";
  import { installBlocked, unattendedBlocked, type Blocked } from "../lib/blocked";
  import { harnesses } from "../lib/harnesses.svelte";
  import AppFailure from "../components/AppFailure.svelte";
  import DisabledReason from "../components/DisabledReason.svelte";

  let { name }: { name: string } = $props();

  let app = $state<App | null>(null);
  const title = $derived(app ? appTitle(app) : name); // what it is called (H.1)
  let automations = $state<AutomationView[]>([]);
  let accounts = $state<AccountInfo[]>([]); // their harnesses: whose terms refuse runs nobody follows
  let error = $state<string | null>(null);
  let errorLogged = $state(false); // its deploy failed: its log shown under it
  let doing = $state<string | null>(null); // the step under way

  // where its data goes: a folder of yours, one suggested (a new one made at Install) or another
  // (picked, or made, in the picker)
  let chosenFolder = $state("");
  let suggestions = $state<FolderSuggestion[] | null>(null); // null: not read yet
  let another = $state(false); // Another folder…: the picker
  let otherFolders = $state<Record<string, string>>({}); // its other folders needs → the folder chosen
  let otherSuggestions = $state<Record<string, FolderSuggestion[]>>({}); // their suggestions
  let otherAnother = $state<Record<string, boolean>>({}); // their Another folder…
  let secrets = $state<Record<string, string>>({});
  let who = $state<WhoWorks | null>(null); // who works on its jobs (H.2), as chosen here
  let switched = $state<Record<number, boolean>>({}); // suggestions switched on or off here
  let persons = $state<string[] | null>(null);

  async function load(): Promise<void> {
    try {
      const [a, au, ac] = await Promise.all([
        api.app(name),
        api.automations().catch(() => []),
        api.accounts().catch(() => []),
        harnesses.load(),
      ]);
      [automations, accounts] = [au, ac];
      persons ??= [...(a.persons ?? [])];
      who ??= a.whoWorks ?? null;
      app = a;
      error = null;
      if (suggestions === null && (a.files ?? []).some((f) => !f.path)) void suggest(a);
    } catch (e) {
      error = (e as Error).message;
    }
  }

  /** The folders offered for the app's folders: from the work folders and your notes (offered
   *  for an app's folder, H.9), and what they hold. Each folder's first is chosen; none, its
   *  picker. */
  async function suggest(a: App): Promise<void> {
    let listed: { path: string; entries: DirectoryEntry[] }[] = [];
    let notes: { path: string; entries: DirectoryEntry[] } | null = null;
    try {
      const [work, offered] = await Promise.all([api.folders(), api.directories(undefined, true)]);
      const roots = work.folders.filter((f) => f.exists).map((f) => f.path);
      const list = (path: string) => api.directories(path, true).then((l) => ({ path, entries: l.entries }), () => null);
      listed = (await Promise.all(roots.map(list))).filter((l) => l !== null);
      const notesRoot = offered.entries.map((e) => e.path).find((path) => !roots.includes(path));
      notes = notesRoot ? await list(notesRoot) : null;
    } catch {
      // nothing to suggest: the pickers
    }
    const notesFirst = (a.jobs ?? []).some((j) => j.canDo.schemas?.length); // its data is notes
    suggestions = folderSuggestions(a, listed, { notes, notesFirst });
    if (!chosenFolder && !another) {
      if (suggestions.length) chosenFolder = suggestions[0]!.path;
      else another = true;
    }
    const data = dataNeed(a)?.name;
    for (const f of a.files ?? []) {
      if (f.name === data || f.path) continue;
      const offered = folderSuggestions(a, listed, { need: f.name, notes, notesFirst });
      otherSuggestions[f.name] = offered;
      if (!otherFolders[f.name] && !otherAnother[f.name]) {
        if (offered.length) otherFolders[f.name] = offered[0]!.path;
        else otherAnother[f.name] = true;
      }
    }
  }

  function pickFolder(s: FolderSuggestion | null): void {
    another = !s;
    chosenFolder = s?.path ?? ""; // another: the picker starts from the work folders
  }

  function pickOther(need: string, s: FolderSuggestion | null): void {
    otherAnother[need] = !s;
    otherFolders[need] = s?.path ?? "";
  }

  $effect(() => {
    remote.start();
    void load();
  });

  const data = $derived(app ? dataNeed(app) : undefined);
  const others = $derived((app?.files ?? []).filter((f) => f.name !== data?.name));
  const target = $derived(data?.path ?? chosenFolder);
  // a new folder suggested: made when it is given, at Install
  const creates = $derived(!another && !!suggestions?.some((s) => s.isNew && s.path === chosenFolder));
  // the project whose folder it is: it lists the app (H.14), the app stays in Apps
  const project = $derived(target ? projects.list.find((p) => p.folder === target) : undefined);
  const devicesOf = $derived.by(() => {
    const out: Record<string, string[]> = { owner: [] };
    for (const d of remote.status?.devices ?? []) (out[d.person ?? "owner"] ??= []).push(d.name);
    return out;
  });

  /** A suggestion wanted: as switched, else on unless the app marks it optional. */
  function wanted(i: number): boolean {
    return switched[i] ?? !app?.suggests?.[i]?.optional;
  }

  /** Who works on a job (H.2): its own (only once installed), else the app's as chosen here. */
  function jobWho(job: string): WhoWorks | null {
    const j = app?.jobs?.find((x) => x.name === job);
    return j?.own && j.whoWorks ? j.whoWorks : who;
  }

  /** Why a suggestion cannot be turned on with who works now (its account's terms refuse runs
   *  nobody follows, I.7): its switch then stays off, and Install skips it. */
  function refused(i: number): Blocked | null {
    const s = app?.suggests?.[i];
    if (!s?.run.job) return null; // a call is its code: nobody works on it
    const w = jobWho(s.run.job);
    return unattendedBlocked(w && { account: w.account, harness: w.program }, accounts, harnesses.list, '[data-step="who-works"] [data-testid="model-choice-access"]');
  }

  /** A suggestion made and turned on at Install: wanted, and runnable by who works. */
  function isOn(i: number): boolean {
    return wanted(i) && !refused(i);
  }

  /** Who works for a suggestion: its job's Who works. */
  function worker(s: AppManifestSuggestedAutomation): string {
    if (!s.run.job) return "its code";
    const w = jobWho(s.run.job);
    return (w && (w.account ?? w.provider)) || "who you choose";
  }

  const todo = $derived(
    app
      ? stillToChoose({ title, data, target, others, otherFolders, secrets: app.secrets, given: secrets, jobs: !!app.jobs?.length, who })
      : [],
  );
  /** A step with nothing left to choose in it: its number becomes a check. */
  const PREFIX: Record<string, string> = { where: "folder", workers: "who-works", secrets: "secret:" };
  const done = (step: string): boolean => !!PREFIX[step] && !todo.some((t) => t.at.startsWith(`[data-step="${PREFIX[step]}`));
  const blocked = $derived(installBlocked(todo));

  /** What it will be allowed to do: what its version may reach, with the folders chosen; who
   *  works on its jobs; what runs by itself. */
  const allowed = $derived.by(() => {
    if (!app?.source.needs) return [];
    const files = (app.files ?? []).map((f) => ({ ...f, path: f.path ?? ((f.name === data?.name ? target : otherFolders[f.name]) || null) }));
    const lines = reaches(app.source.needs, { ...app, files });
    if (app.jobs?.length && who) lines.push(`Its jobs run as ${whoWorksWords(who, (h) => harnesses.product(h))}.`);
    (app.suggests ?? []).forEach((s, i) => {
      const what = s.run.job ? `its job “${app!.jobs?.find((j) => j.name === s.run.job)?.description ?? s.run.job}”` : `its code (${s.run.call})`;
      if (isOn(i)) lines.push(`Runs ${what} ${whenSentence(suggested(app!, s).definition).toLowerCase()}, by itself.`);
    });
    return lines;
  });

  async function step<T>(label: string, action: () => Promise<T>): Promise<T> {
    doing = label;
    return action();
  }

  async function install(): Promise<void> {
    if (!app) return;
    const a = app;
    error = null;
    try {
      // its folders first: its jobs work in them
      if (data && !data.path) await step(`giving it ${target}`, () => api.setAppFile(a.name, data.name, target, creates));
      for (const f of others) {
        const path = otherFolders[f.name]!;
        const made = !otherAnother[f.name] && !!otherSuggestions[f.name]?.some((s) => s.isNew && s.path === path);
        if (!f.path) await step(`giving it ${path}`, () => api.setAppFile(a.name, f.name, path, made));
      }
      // who works on its jobs: before what runs them by itself is made and turned on
      const w = who;
      if (a.jobs?.length && w && !(a.whoWorks && sameModel(asAccess(w), asAccess(a.whoWorks)))) await step("choosing who works", () => api.setAppWhoWorks(a.name, w));
      for (const s of a.secrets ?? []) if (!s.set) await step(`keeping ${s.name}`, () => api.setAppSecret(a.name, s.name, secrets[s.name]!.trim()));
      for (const [i, s] of (a.suggests ?? []).entries()) {
        const { name: auto, definition } = suggested(a, s);
        if (isOn(i) && !automations.some((x) => x.name === auto)) await step(`making ${auto}`, () => api.createAutomation(auto, { definition, agentId: null, enable: true }));
      }
      if (!a.current) await step("deploying: its tests, then its health check", () => api.deployApp(a.name));
      if (persons && persons.join() !== (a.persons ?? []).join()) await step("sharing it", () => api.setAppPersons(a.name, persons!));
      await projects.refresh();
      navigate({ view: "apps", app: a.name, tab: "settings" }, true);
    } catch (e) {
      const failed = `While ${doing}: ${(e as Error).message}. What was done is kept: Install goes on from there.`;
      const deploying = doing?.startsWith("deploying") ?? false;
      await load(); // what was done, shown; it clears the error: set after
      error = failed;
      errorLogged = deploying;
    } finally {
      doing = null;
    }
  }

  async function cancel(): Promise<void> {
    const detail = "It was never installed: its code and what you chose for it here go; your folders stay.";
    if (app && !app.current && (await ask({ title: `Forget ${title}?`, detail, yes: "Forget", danger: true }))) {
      await api.uninstallApp(app.name).catch(() => {});
    }
    navigate({ view: "apps" }, true);
  }

  const asAccess = (w: WhoWorks) => ({ harness: w.program, account: w.account, provider: w.provider, model: w.model });

  function togglePerson(person: string, on: boolean): void {
    const all = new Set(persons ?? []);
    if (on) all.add(person);
    else all.delete(person);
    persons = [...all].sort();
  }

  /** What the app's folder is for, in its words, and who reads it. */
  function folderHint(f: { description?: string | null; name: string; mode: string }): string {
    const writes = f.mode === "rw";
    const helpers = app?.jobs?.some((j) => j.canDo.files?.[f.name]) ? " and its jobs" : "";
    const by = helpers ? `${title}${helpers} ${writes ? "read and write" : "read"} it` : `${title} ${writes ? "reads and writes" : "reads"} it`;
    return `${(f.description ?? f.name).replace(/\.$/, "")}. ${by}.`;
  }

  const showsWho = $derived(Object.keys(devicesOf).length > 1 || (remote.status?.devices ?? []).length > 0);
  // the steps shown, numbered in order
  const steps = $derived(
    [data && "where", app?.jobs?.length && "workers", app?.secrets?.length && "secrets", app?.actions?.length && "actions", app?.suggests?.length && "suggests", showsWho && "who"].filter(Boolean),
  );
</script>

<!-- A folder's choices: its suggestions, then Another folder… (its picker); `chosen`: null when
     another is picked. `need`: "" for the app's data folder (its test ids stay as they were). -->
{#snippet choices(label: string, offered: FolderSuggestion[], chosen: string | null, pick: (s: FolderSuggestion | null) => void, need: string)}
  <div class="divide-y overflow-hidden rounded-[10px] border bg-card" role="radiogroup" aria-label={label} data-testid={need ? `install-folders-${need}` : "install-folders"}>
    {#each offered as s (s.path)}
      {@const on = chosen === s.path}
      <button
        type="button"
        role="radio"
        aria-checked={on}
        class="flex w-full cursor-pointer items-center gap-3 px-3.5 py-2.5 text-left text-sm hover:bg-muted/60 {on ? 'bg-accent-soft/40' : ''}"
        onclick={() => pick(s)}
        data-testid="install-folder-suggestion"
      >
        <span class="radio" class:on></span><Folder class="size-4 shrink-0 text-muted-foreground" />
        <span class="min-w-0 truncate font-mono text-xs" title={s.path}>{homePath(s.path)}</span>
        <span class="text-xs text-muted-foreground">{s.isNew ? "new folder" : "a folder you have"}{s.inNotes ? ", in your notes" : ""}</span>
      </button>
    {/each}
    <button
      type="button"
      role="radio"
      aria-checked={chosen === null}
      class="flex w-full cursor-pointer items-center gap-3 px-3.5 py-2.5 text-left text-sm hover:bg-muted/60 {chosen === null ? 'bg-accent-soft/40' : 'text-muted-foreground'}"
      onclick={() => pick(null)}
      data-testid="install-folder-other"
    >
      <span class="radio" class:on={chosen === null}></span><FolderOpen class="size-4 shrink-0" />Another folder…
    </button>
  </div>
{/snippet}

{#snippet head(step: string, heading: string, hint: string, optional = false)}
  <div class="flex items-start gap-3">
    {#if done(step)}
      <span class="flex size-6 shrink-0 items-center justify-center rounded-full bg-ok/10 text-ok" data-testid="install-step-done"><Check class="size-3.5" /></span>
    {:else}
      <span class="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">{steps.indexOf(step) + 1}</span>
    {/if}
    <div>
      <h2 class="text-sm font-semibold">{heading}{#if optional}<span class="ml-1.5 text-xs font-normal text-muted-foreground">optional</span>{/if}</h2>
      {#if hint}<p class="text-sm text-muted-foreground">{hint}</p>{/if}
    </div>
  </div>
{/snippet}

<PageHeader width="max-w-5xl" title="Install {title}" parent={{ label: `Library › Apps › ${title}`, href: href({ view: "apps", app: name }) }} />
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-5xl space-y-6 px-8 py-10">
    <div class="space-y-1">
      {#if app}<p class="text-sm text-muted-foreground">{app.source.description ?? ""} <span class="fact">· {app.source.version ?? ""} · {fromSourceWords(app.fromSource, []) ?? "from a file"}</span></p>{/if}
    </div>
    {#if app?.source.error}
      <p class="text-sm text-danger">Its folder cannot be read: {app.source.error}</p>
    {:else if app}
      <div class="grid items-start gap-6 lg:grid-cols-[1fr_19rem]">
        <div class="space-y-4">
          {#if data}
            <section class="space-y-3 rounded-xl border bg-card p-4 shadow-panel" data-testid="install-where">
              {@render head("where", `${title}'s folder`, folderHint(data))}
              <div class="space-y-2 pl-9 text-sm">
                {#if data.path}
                  <p data-testid="install-where-done"><Check class="mr-1 inline size-4 text-ok" /><span class="fact">{data.path}</span></p>
                {:else}
                  <div class="space-y-2" data-step="folder">
                    {#if suggestions?.length}{@render choices(`${title}'s folder`, suggestions, another ? null : chosenFolder, pickFolder, "")}{/if}
                    {#if another}<FolderPicker bind:value={chosenFolder} used={Object.fromEntries(projects.list.map((p) => [p.folder, p.name]))} forApp />{/if}
                  </div>
                {/if}
                {#if project}
                  <p class="text-xs text-muted-foreground" data-testid="install-where-project">The folder of the project {project.name}: its page will list {title} as using it. The app stays in Apps.</p>
                {/if}
                {#each others as f (f.name)}
                  <div class="space-y-1 pt-2" data-step="folder:{f.name}">
                    <p>{f.description ?? f.name} <span class="text-muted-foreground">· {f.mode === "rw" ? "read and written" : "read only"}</span></p>
                    {#if f.path}
                      <p class="fact">{f.path}</p>
                    {:else}
                      {@const offered = otherSuggestions[f.name] ?? []}
                      {#if offered.length}{@render choices(f.description ?? f.name, offered, otherAnother[f.name] ? null : (otherFolders[f.name] ?? ""), (s) => pickOther(f.name, s), f.name)}{/if}
                      {#if otherAnother[f.name]}<FolderPicker bind:value={() => otherFolders[f.name] ?? "", (v) => (otherFolders[f.name] = v)} forApp />{/if}
                    {/if}
                  </div>
                {/each}
              </div>
            </section>
          {/if}

          {#if app.jobs?.length}
            {@const unattended = (app.suggests ?? []).some((s, i) => wanted(i) && !!s.run.job)}
            <section class="space-y-3 rounded-xl border bg-card p-4 shadow-panel" data-testid="install-who-works">
              {@render head("workers", "Who works", `${title} brings its jobs, the work it asks a model to do; you choose who does it: account or API key, program and model. One job may get its own later, on ${title}'s page.`)}
              <div class="space-y-3 pl-9 text-sm">
                <div class="flex flex-wrap items-center gap-3" data-step="who-works">
                  {#key app.name}<AppWhoWorks name={title} value={who} limits={jobLimits(app.jobs, false)} {unattended} onchange={(w) => (who = w)} />{/key}
                </div>
                <p class="text-muted-foreground" data-testid="install-jobs">Its jobs: <span class="text-foreground">{app.jobs.map((j) => j.description).join(" · ")}</span></p>
              </div>
            </section>
          {/if}

          {#if app.secrets?.length}
            <section class="space-y-3 rounded-xl border bg-card p-4 shadow-panel">
              {@render head("secrets", "Its secrets", "Kept by Handler, never in the app's folder.")}
              <div class="space-y-2 pl-9 text-sm">
                {#each app.secrets as s (s.name)}
                  <div class="flex items-center gap-3" data-step="secret:{s.name}">
                    <span class="fact w-44">{s.name}</span>
                    {#if s.set}<span><Check class="mr-1 inline size-4 text-ok" />kept</span>{:else}<Input type="password" class="w-72" bind:value={secrets[s.name]} data-testid="install-secret" />{/if}
                  </div>
                {/each}
              </div>
            </section>
          {/if}

          {#if app.actions?.length}
            <section class="space-y-3 rounded-xl border bg-card p-4 shadow-panel" data-testid="install-actions">
              {@render head("actions", "What you will be able to ask it", "Tried from its page once installed.")}
              <ul class="space-y-1.5 pl-9 text-sm">
                {#each app.actions as action (action.name)}
                  <li class="flex flex-wrap gap-x-3">
                    <span class="font-medium">{action.description}</span>
                    {#if action.examples?.length}<span class="text-muted-foreground">“{action.examples[0]}”</span>{/if}
                    <span class="fact">{action.by === "code" ? "instant" : "takes a while"}</span>
                  </li>
                {/each}
              </ul>
            </section>
          {/if}

          {#if app.suggests?.length}
            <section class="space-y-3 rounded-xl border bg-card p-4 shadow-panel" data-testid="install-suggests">
              {@render head("suggests", "Runs by itself", `${title} suggests ${app.suggests.length === 1 ? "one run" : "runs"} of its own. Each one switched on is made and turned on at Install; switch off what you do not want, and change it later on its page.`, true)}
              <div class="space-y-2 pl-9 text-sm">
                {#each app.suggests as s, i (i)}
                  {@const made = automations.find((x) => x.name === suggested({ name }, s).name)}
                  <div class="flex items-center gap-3 rounded-lg border px-3 py-2.5">
                    <div class="min-w-0 flex-1">
                      <p>{s.description} <span class="text-muted-foreground">· {whenSentence(suggested({ name }, s).definition)} · {s.run.job ? `${worker(s)} works` : "its code, no model"}</span>{#if s.optional}<span class="ml-1.5 text-xs text-muted-foreground">optional</span>{/if}</p>
                      {#if s.run.job}<p class="text-xs text-muted-foreground" data-testid="install-suggest-advice">Runs with nobody following: an API key is recommended rather than your subscription.</p>{/if}
                      {#if !made && refused(i)}<DisabledReason blocked={refused(i)!} testid="install-suggest-refused" />{/if}
                    </div>
                    {#if made}<span class="text-muted-foreground">made ({made.enabled ? "on" : "off"})</span>
                    {:else}<Switch checked={isOn(i)} disabled={!!refused(i)} label="{s.description}: runs by itself" onchange={(on) => (switched[i] = on)} testid="install-suggest" />{/if}
                  </div>
                {/each}
              </div>
            </section>
          {/if}

          {#if showsWho}
            <section class="space-y-3 rounded-xl border bg-card p-4 shadow-panel">
              {@render head("who", "Who opens it", "On this computer, and on the paired phones of the people you tick.")}
              <div class="flex flex-wrap gap-2 pl-9 text-sm">
                {#each Object.keys(devicesOf).sort() as person (person)}
                  <label class="flex items-center gap-2 rounded-lg border px-3 py-2 has-checked:border-primary/60 has-checked:bg-primary/5">
                    <input type="checkbox" class="accent-primary" checked={persons?.includes(person) ?? false} onchange={(e) => togglePerson(person, e.currentTarget.checked)} />
                    {person === "owner" ? "you, on your phone" : person}
                  </label>
                {/each}
              </div>
            </section>
          {/if}

          {#if error && errorLogged && app}<AppFailure name={app.name} message={error} testid="install-error" />
          {:else if error}<p class="text-sm text-danger" data-testid="install-error">{error}</p>{/if}
          <div class="flex items-center justify-end gap-3">
            {#if doing}<p class="mr-auto text-sm text-muted-foreground" data-testid="install-doing">{doing}…</p>
            {:else if blocked}<span class="mr-auto"><DisabledReason {blocked} testid="install-todo" /></span>
            {:else}<p class="mr-auto text-sm text-muted-foreground">Its tests run first: if they fail, it is not installed (what you chose is kept).</p>{/if}
            <Button variant="ghost" onclick={cancel} data-testid="install-cancel">Cancel</Button>
            <Button disabled={!!doing || !!blocked} onclick={install} data-testid="install-go"><Check />Install {title}</Button>
          </div>
        </div>

        <aside class="space-y-2 rounded-[10px] bg-muted/60 px-4 py-3.5 text-sm lg:sticky lg:top-4" data-testid="install-may">
          <h3 class="flex items-center gap-2 font-semibold"><ShieldCheck class="size-4" />What {title} may do</h3>
          {#each allowed as line (line)}<p class="text-muted-foreground">{line}</p>{/each}
          <p class="pt-1 text-xs text-muted-foreground">Installing says yes to this. Nothing of yours is written in {title}'s own files.</p>
        </aside>
      </div>
    {:else if error}
      <p class="text-sm text-danger">{error}</p>
    {:else}
      <p class="text-sm text-muted-foreground">Loading…</p>
    {/if}
  </div>
</div>

<style>
  .radio {
    flex: none;
    width: 15px;
    height: 15px;
    border: 1.5px solid var(--muted-foreground);
    border-radius: 50%;
  }
  .radio.on {
    border: 4.5px solid var(--primary);
  }
</style>
