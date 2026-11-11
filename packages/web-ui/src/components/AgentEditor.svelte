<script lang="ts">
  // An agent of a project, or one outside projects (in a folder, or a folder per session), to add
  // one or edit it: the one agent form, every setting visible, nothing folded. Rows first: its
  // name (what it is for; "Assistant" for a project's first) and description, how it is used
  // (Talk; Brief: a form starts each session, then a talk; Job: a form in, a result out,
  // unattended, D.18; a change of use that drops a saved brief or result says so), who works (two
  // chips: its program, or the model alone, then what it runs on and its model), its tools,
  // skills and notes; outside projects, its folder. Then a brief's or a job's form (JobEditor), its
  // instructions, which may name the form's fields `{{key}}` (a field not saved yet keeps its
  // placeholders when its label, so its key, changes); then Can do (CanDo: the network and the
  // switches, no named preset; the model alone has no sandbox, said in one card); then how it is
  // started (default agent, from the phone, the automations that run it, I.1). Its settings are
  // its own, nothing inherited; a new one starts with only the sites it needs. A save that widens
  // what it may do is confirmed (D.8). A new agent of a project set up like another but for its
  // model is pointed to that one: one goal, one agent. A job never asks (bypass, confirmed when
  // chosen); "Save and try" saves it, then opens its page and its run form; "Save and run it on a
  // schedule…" saves it, then opens a new automation's form.
  import type { Agent, AgentOrigin, AutomationView, HarnessInfo, Project, UseRef } from "../lib/contracts.gen";
  import { resultProblems, runsAgent, whenSentence } from "../lib/automations";
  import { dependents } from "../lib/apps";
  import { accessLabel, accessOf, chosen, sameModel, sameRun } from "../lib/access";
  import { api, ApiError, toolboxChanges, type ToolboxChanges } from "../lib/api";
  import ToolboxConfirm from "./ToolboxConfirm.svelte";
  import { runtime } from "../lib/runtime.svelte";
  import { agentBody, agentLabel, agentSpec, emptyAgent, homeOf, sameSetup, withModelAlone, type AgentSpec, type Home } from "../lib/projects.svelte";
  import { href, type Route } from "../lib/router.svelte";
  import { SEGMENT, SEGMENT_OFF, SEGMENT_ON } from "../lib/form";
  import { PERMISSION_LABEL } from "../lib/agents";
  import { productName } from "../lib/harnesses.svelte";
  import { neededSites } from "../lib/safety";
  import type { AccountInfo, AddonInfo, ProviderInfo } from "../lib/contracts.gen";
  import { Button } from "$lib/components/ui/button";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import FlaskConical from "@lucide/svelte/icons/flask-conical";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import { interfaceOf, newBrief, newJob, placeholders, renamed, switchedTo, useOf, type Use } from "../lib/interface";
  import { fieldsOf, type Schema } from "../lib/runs";
  import { tick, untrack } from "svelte";
  import JobEditor from "./JobEditor.svelte";
  import CalendarClock from "@lucide/svelte/icons/calendar-clock";
  import ClipboardList from "@lucide/svelte/icons/clipboard-list";
  import NotebookPen from "@lucide/svelte/icons/notebook-pen";
  import MessageSquare from "@lucide/svelte/icons/message-square";
  import ShieldAlert from "@lucide/svelte/icons/shield-alert";
  import ShieldCheck from "@lucide/svelte/icons/shield-check";
  import PromptBox from "./PromptBox.svelte";
  import AddonPicker from "./AddonPicker.svelte";
  import FolderPicker from "./FolderPicker.svelte";
  import KnowledgePicker from "./KnowledgePicker.svelte";
  import SkillPicker from "./SkillPicker.svelte";
  import StatusBadge from "./StatusBadge.svelte";
  import When from "./When.svelte";
  import ModelChoice from "./ModelChoice.svelte";
  import CanDo from "./CanDo.svelte";
  import SettingRow from "./SettingRow.svelte";

  let {
    project,
    agent,
    start,
    origin,
    startFolder,
    pendingSkills = [],
    onsaved,
    oncancel,
  }: {
    project?: Project; // none: an ad-hoc agent
    agent?: Agent; // edit it; none: a new one
    start?: AgentSpec; // a new one's starting values (a duplicated agent's, a definition's)
    origin?: AgentOrigin; // a new one: what it is set up from (D.23: an agents file's agent, D.18: a need of Handler's, H.2: an app's need, whose part it is)
    startFolder?: string | null; // a new ad-hoc one's folder (an app's need: the folder given for it)
    pendingSkills?: string[]; // its definition's skills, not in the library until saved
    onsaved: (agent: Agent, then?: Route) => void; // then: where to go next, instead of back
    oncancel: () => void;
  } = $props();

  // the props give the initial values only
  // svelte-ignore state_referenced_locally
  let spec = $state<AgentSpec>(
    agent ? agentSpec(agent, project ?? { defaultAgent: null }) : (start ?? { ...emptyAgent(), name: project && !project.agents.length ? "Assistant" : "" }),
  );
  // an ad-hoc agent's folder; null: a folder per session (D.18)
  // svelte-ignore state_referenced_locally
  let folder = $state<string | null>(agent ? (agent.scope ?? null) : (startFolder ?? null));
  let busy = $state(false);
  let error = $state<string | null>(null);
  let risks = $state<string | null>(null); // what the last save would widen, to confirm
  let toolbox = $state<(ToolboxChanges & { risks: boolean }) | null>(null); // what it adds to the toolbox
  // saved by "Save and try" (its page, to run it) or "Save and run it on a schedule…" (the form)
  let next = $state<"try" | "schedule" | null>(null);
  let displayAvailable = $state(false); // the daemon found a Wayland display (A.6)
  // what this computer's sandbox runtime gives (A.8), as last checked; unknown: nothing greyed
  const gives = $derived(runtime.last?.supports ?? null);
  api.health().then(
    (h) => (displayAvailable = h.display ?? false),
    () => (displayAvailable = false),
  );

  let harnesses = $state<HarnessInfo[]>([]);
  api.harnesses().then(
    (list) => (harnesses = list),
    () => (harnesses = []),
  );

  // who works (D.18): an agent program, or the model alone (what only a sandbox has goes)
  function chooseProgram(alone: boolean): void {
    if (alone === spec.modelAlone) return;
    spec = withModelAlone(spec, alone);
    if (alone) folder = null;
  }

  // the modes its harness offers (pi has only bypass); all while unknown
  const offered = $derived(harnesses.find((h) => h.name === spec.model.harness)?.permissions);
  const live = $derived(agent?.connections.length ?? 0);
  // what its past conversations ran with, changed: they cannot be resumed
  const dropped = $derived(agent && !sameRun(spec.model, agent.model) ? agent.model : null);
  // the account (a subscription) it runs on: an unattended agent is better on an API key
  const onSubscription = $derived(spec.model.account);
  // one goal, one agent: another agent of the project set up the same, but for its model
  // (once it has a goal: a new one starts set up like the default agent)
  const twin = $derived(project && !agent && !start && spec.name.trim() ? sameSetup(spec, project.agents, project) : undefined);
  // why it cannot be saved yet
  const movedFolder = $derived(!!agent && !project && (agent.scope ?? null) !== folder);

  // a new agent starts with what the project's default agent runs as
  // (once: what is chosen after is the person's)
  let seeded = false;
  $effect(() => {
    if (seeded || !project || agent || start || chosen(spec.model, spec.modelAlone)) return;
    seeded = true;
    const preferred = project.agents.find((a) => a.id === project.defaultAgent);
    if (preferred) spec = { ...withModelAlone(spec, preferred.modelAlone ?? false), model: accessOf(preferred.model) };
  });



  type PermissionMode = Agent["permissions"];

  // the sites what it uses needs: handlerd's own list for a saved agent unchanged, else what its
  // model and its tools (its own and its project's) say they reach
  let infos = $state<{ accounts: AccountInfo[]; providers: ProviderInfo[]; addons: AddonInfo[] }>({ accounts: [], providers: [], addons: [] });
  Promise.all([api.accounts(), api.providers(), api.addons()]).then(
    ([accounts, providers, addons]) => (infos = { accounts, providers, addons }),
    () => {},
  );
  const uses = $derived([...spec.addons, ...(project?.addons ?? [])]);
  const unchanged = $derived(!!agent && sameModel(spec.model, agent.model) && JSON.stringify(spec.addons) === JSON.stringify(agent.addons ?? []));
  const needed = $derived(neededSites(spec.model, uses, infos, unchanged ? (agent?.model.requiredHosts ?? []) : undefined));

  // how it is used, the first choice, as cards saying each the same three things: how it starts,
  // who is there, how it ends
  const USES: { use: Use; label: string; hint: string; icon: typeof MessageSquare }[] = [
    { use: "chat", label: "Talk", hint: "Say what to do, or nothing; you talk with it until you are done.", icon: MessageSquare },
    { use: "brief", label: "Brief", hint: "Fill in a form to start, then work on it together.", icon: NotebookPen },
    { use: "job", label: "Job", hint: "Fill in a form; it works alone and returns a result.", icon: ClipboardList },
  ];
  const use = $derived(useOf(spec.interface));
  const job = $derived(use === "job"); // unattended: it never asks

  // a new job (D.18): no form yet, a result saying how it went, as an automation needs it (I.3);
  // a new brief: one long text, what a chat's request box asks
  const NEW_JOB = JSON.stringify(interfaceOf(newJob()), null, 2);
  const NEW_BRIEF = JSON.stringify(interfaceOf(newBrief(), true), null, 2);
  // what a save drops of what it has now
  const was = $derived<Use>(agent?.interface ? (agent.interface.result ? "job" : "brief") : "chat");
  const DROPS: Partial<Record<`${Use}→${Use}`, string>> = {
    "job→brief": "Its result goes when you save.",
    "job→chat": "Its form and its result go when you save.",
    "brief→chat": "Its brief goes when you save.",
  };
  const drops = $derived(DROPS[`${was}→${use}`] ?? null);
  // the form's fields, for its instructions to name; a placeholder naming none blocks the save
  const formFields = $derived.by(() => {
    if (use === "chat") return [];
    try {
      return fieldsOf(JSON.parse(spec.interface)?.fields as Schema | undefined);
    } catch {
      return [];
    }
  });
  const unknownField = $derived(placeholders(spec.instructions).find((k) => !formFields.some((f) => f.key === k)) ?? null);
  const blocker = $derived(
    unknownField !== null
      ? `Instructions: {{${unknownField}}} is not a field of its form.`
      : !chosen(spec.model, spec.modelAlone)
      ? "Choose what it runs as."
      : folder === ""
        ? "Choose its folder."
        : project && !spec.name.trim()
          ? "Give it a name."
          : null,
  );
  // a field's key that changed in place (it follows its label until saved): its placeholders too
  let keysBefore: string[] = [];
  $effect(() => {
    const keys = formFields.map((f) => f.key);
    if (keys.length === keysBefore.length) {
      const before = untrack(() => spec.instructions);
      let text = before;
      keys.forEach((k, i) => {
        const old = keysBefore[i]!;
        if (old !== k && !keys.includes(old)) text = renamed(text, old, k);
      });
      if (text !== before) spec.instructions = text;
    }
    keysBefore = keys;
  });
  let instructionsBox = $state<HTMLTextAreaElement | null>(null);
  async function insertField(key: string): Promise<void> {
    const box = instructionsBox;
    const [from, to] = box ? [box.selectionStart, box.selectionEnd] : [spec.instructions.length, spec.instructions.length];
    const piece = `{{${key}}}`;
    spec.instructions = spec.instructions.slice(0, from) + piece + spec.instructions.slice(to);
    await tick();
    box?.focus();
    box?.setSelectionRange(from + piece.length, from + piece.length);
  }

  // what its result lacks for an automation to run it (I.3); none while the JSON does not parse
  const lacks = $derived.by(() => {
    if (!job) return [];
    try {
      return resultProblems(JSON.parse(spec.interface)?.result);
    } catch {
      return [];
    }
  });

  // the automations that run it (I.1): an automation finds it by its name, in its project; the
  // apps it was given to (H.2), by its id
  let automations = $state<AutomationView[]>([]);
  // Handler's roles it was given for (D.18) and the apps it was given to (H.2): D.22's used-by
  let usedBy = $state<UseRef[]>([]);
  $effect(() => {
    if (!agent) return;
    api.automations().then(
      (list) => (automations = list.filter((a) => runsAgent(a, agent.id))),
      () => (automations = []),
    );
    dependents(agent.id).then(
      (refs) => (usedBy = refs.filter((r) => r.kind !== "automation")),
      () => (usedBy = []),
    );
  });

  // a job: no one is there to answer its permission requests, so it never asks (bypass);
  // switching to it is confirmed first, the mode it had is given back when it is no longer one.
  // A brief keeps its form, a job the form it had as a brief.
  let permissionsBefore = $state<PermissionMode | null>(null);
  let confirmBypass = $state(false);
  function chooseUse(next: Use): void {
    confirmBypass = false;
    if (next === use) return;
    if (next === "job" && spec.permissions !== "bypass") {
      confirmBypass = true;
      return;
    }
    spec.interface = next === "chat" ? "" : use === "chat" ? (next === "job" ? NEW_JOB : NEW_BRIEF) : switchedTo(next, spec.interface);
    if (next !== "job" && permissionsBefore !== null) {
      spec.permissions = permissionsBefore;
      permissionsBefore = null;
    }
  }
  function acceptBypass(): void {
    permissionsBefore = spec.permissions;
    spec.permissions = "bypass";
    spec.interface = use === "chat" ? NEW_JOB : switchedTo("job", spec.interface);
    confirmBypass = false;
  }

  async function save(confirm = false, adds: string[] = []): Promise<void> {
    busy = true;
    error = null;
    try {
      // its home: kept when it exists; a new one's, its project's, or the app it is set up for
      const home: Home = agent
        ? { ...homeOf(agent), ...(agent.projectId ? {} : { scope: folder }) }
        : project
          ? { projectId: project.id }
          : { app: origin?.kind === "app" ? origin.name : null, scope: folder };
      const body = agentBody({ ...spec, origin: agent ? (agent.origin ?? null) : (origin ?? null) }, home, confirm, adds);
      const saved = agent ? await api.updateAgent(agent.id, body) : await api.createAgent(body);
      risks = toolbox = null;
      onsaved(saved, next === "schedule" ? { view: "edit-automation", agent: saved.id } : next === "try" ? { view: "agent", id: saved.id } : undefined);
    } catch (e) {
      const changes = toolboxChanges(e);
      if (e instanceof ApiError && e.status === 409 && e.title === "risks not confirmed") risks = e.detail ?? e.title;
      else if (changes) ((risks = null), (toolbox = { ...changes, risks: confirm }));
      else {
        error = (e as Error).message;
        next = null;
      }
    } finally {
      busy = false;
    }
  }

  function submit(event: SubmitEvent): void {
    event.preventDefault();
    next = null;
    void save();
  }
</script>

<form class="space-y-8" onsubmit={submit} data-testid="agent-editor">
  <div class="divide-y overflow-hidden rounded-[10px] border bg-card shadow-panel">
    <SettingRow label="Name" for="agent-name">
      <div class="flex flex-wrap items-center gap-3">
        <Input id="agent-name" class="max-w-60" bind:value={spec.name} required={!!project} data-testid="agent-name-input" />
        <span class="text-xs text-muted-foreground">what it's for: Reviewer, Release notes…</span>
      </div>
    </SettingRow>
    <SettingRow label="Description" for="agent-description">
      <Input id="agent-description" class="max-w-md" bind:value={spec.description} placeholder="optional: shown when you point at it" data-testid="agent-description" />
    </SettingRow>
    <SettingRow label="Use" data-testid="agent-use">
      <div class="flex flex-wrap items-center gap-3">
        <div class="inline-flex rounded-lg border bg-muted p-0.5" role="radiogroup" aria-label="use">
          {#each USES as u (u.use)}
            {@const on = confirmBypass ? u.use === "job" : u.use === use}
            <button
              type="button"
              role="radio"
              aria-checked={on}
              class="{SEGMENT} inline-flex items-center gap-1.5 {on ? SEGMENT_ON : SEGMENT_OFF}"
              onclick={() => chooseUse(u.use)}
              data-testid="agent-use-{u.use}"
            >
              <u.icon class="size-4" />{u.label}
            </button>
          {/each}
        </div>
        <span class="text-xs text-muted-foreground">{USES.find((u) => u.use === use)?.hint}</span>
      </div>
      {#if confirmBypass}
        <div class="flex items-start gap-3 rounded-md border border-warn/40 bg-warn/5 p-3" role="alertdialog" aria-labelledby="bypass-title" data-testid="agent-confirm-bypass">
          <ShieldAlert class="size-5 shrink-0 text-warn" />
          <div class="space-y-2">
            <p id="bypass-title" class="text-sm font-medium">A job never asks before acting</p>
            <p class="text-xs text-muted-foreground">It runs alone: only what it can do (below) limits it. Asks before acting goes off.</p>
            <div class="flex gap-2">
              <Button type="button" size="sm" variant="destructive" onclick={acceptBypass} data-testid="agent-accept-bypass">Make it a job</Button>
              <Button type="button" size="sm" variant="ghost" onclick={() => (confirmBypass = false)}>Cancel</Button>
            </div>
          </div>
        </div>
      {/if}
      {#if drops}<p class="text-xs text-warn" data-testid="agent-use-drops">{drops}</p>{/if}
      {#if job && onSubscription}
        <p class="text-xs text-muted-foreground" data-testid="agent-unattended-subscription">
          It runs on a subscription ({onSubscription}): subscription plans are for ordinary, individual use (their vendors' terms). For an agent that
          runs on its own, an API key is recommended.
        </p>
      {/if}
    </SettingRow>
    <SettingRow label="Who works" data-testid="agent-model">
      <ModelChoice
        agent={{ id: agent?.id ?? "", name: spec.name, model: spec.model, area: project?.area ?? null, modelAlone: spec.modelAlone }}
        own
        onchange={(m) => (spec.model = accessOf(m))}
        onalone={chooseProgram}
      />
      {#if dropped}
        <p class="text-xs text-warn">Its past conversations with {accessLabel(dropped)} cannot be resumed after this change.</p>
      {/if}
      {#if agent?.model.problem}
        <p class="text-xs text-danger" data-testid="agent-problem">It cannot start now: {agent.model.problem}</p>
      {/if}
      {#if twin}
        <p class="text-xs text-warn" data-testid="agent-twin">
          Set up like <a class="text-link hover:underline" href={href({ view: "edit-agent", project: project!.id, id: twin.id })}>{agentLabel(twin)}</a>
          but for its model: start a session of it and choose that model instead.
        </p>
      {/if}
    </SettingRow>
    {#if !project}
      <SettingRow label="Works in" data-testid="agent-folder">
        {#if spec.modelAlone}
          <p class="text-xs text-muted-foreground" data-testid="agent-no-folder">No folder: the model alone reads what its form, the conversation and its notes give it.</p>
        {:else}
          <div class="inline-flex self-start rounded-lg border bg-muted p-0.5" role="radiogroup" aria-label="folder">
            {#each [{ own: false, label: "A folder per session" }, { own: true, label: "A folder" }] as f (f.label)}
              <button
                type="button"
                role="radio"
                aria-checked={(folder !== null) === f.own}
                class="{SEGMENT} {(folder !== null) === f.own ? SEGMENT_ON : SEGMENT_OFF}"
                onclick={() => (folder = f.own ? (agent?.scope ?? "") : null)}
                data-testid={f.own ? "folder-own" : "folder-per-session"}
              >
                {f.label}
              </button>
            {/each}
          </div>
          {#if folder === null}
            <p class="text-xs text-muted-foreground">Each session starts in an empty folder of its own, kept with the session.</p>
          {:else}
            <FolderPicker bind:value={folder} />
          {/if}
          {#if movedFolder}<p class="text-xs text-warn">Its past conversations stay where they were: they cannot be resumed after this change.</p>{/if}
        {/if}
      </SettingRow>
    {/if}
    <SettingRow label="Tools">
      {#if spec.modelAlone}
        <p class="text-xs text-muted-foreground" data-testid="agent-alone-not-given">None: a tool needs an agent program.</p>
      {:else}
        <AddonPicker chips projectId={project?.id} given={project?.addons ?? []} bind:value={spec.addons} />
      {/if}
    </SettingRow>
    <SettingRow label="Skills">
      {#if spec.modelAlone}
        <p class="text-xs text-muted-foreground">None: a skill can run scripts, it needs an agent program.</p>
      {:else}
        <SkillPicker projectId={project?.id} bind:value={spec.skills} pending={pendingSkills} />
      {/if}
    </SettingRow>
    <SettingRow label="Notes">
      <KnowledgePicker bind:value={spec.knowledge} />
    </SettingRow>
  </div>

  {#if spec.interface !== ""}
    <section class="space-y-4" aria-label="its form" data-testid="agent-form-fields">
      <JobEditor bind:value={spec.interface} fresh={!agent?.interface && !start?.interface} brief={use === "brief"} />
      {#if lacks.length}
        <p class="text-xs text-warn" data-testid="agent-interface-lacks">An automation can run it only when its <code>result</code> has {lacks.join(" and ")}.</p>
      {/if}
    </section>
  {/if}

  <section class="space-y-2" aria-labelledby="group-instructions">
    <h2 id="group-instructions" class="text-sm font-semibold">Instructions</h2>
    <Label for="agent-instructions" class="sr-only">Instructions</Label>
    <PromptBox
      id="agent-instructions"
      bind:value={spec.instructions}
      bind:ref={instructionsBox}
      fields={formFields}
      placeholder="e.g. Review the diff against main and list the issues. Do not edit files."
      testid="agent-instructions"
    />
    {#if spec.interface !== "" && !formFields.length}
      <p class="text-xs text-muted-foreground" data-testid="instructions-no-fields">Add fields to the form above to use their values here.</p>
    {:else if formFields.length}
      <div class="flex flex-wrap items-center gap-1.5" data-testid="instructions-fields">
        <span class="text-xs text-muted-foreground">Insert from the form:</span>
        {#each formFields as f (f.key)}
          <button
            type="button"
            class="cursor-pointer rounded-md border bg-muted px-1.5 py-px text-xs hover:bg-accent"
            title="Puts {`{{${f.key}}}`} here: its value when a session starts"
            onclick={() => insertField(f.key)}
            data-testid="instructions-field">{f.title}</button
          >
        {/each}
      </div>
    {/if}
    <p class="text-xs text-muted-foreground">
      {job
        ? "Sent at the start of each run, with the form's values; how to give the result back is added for you."
        : use === "brief"
          ? "Optional. Sent at the start of each session, with the form's values."
          : "Optional. Sent at the start of each session."}
    </p>
  </section>

  {#if spec.modelAlone}
    <section class="space-y-2" aria-labelledby="group-can" data-testid="agent-can-do">
      <h2 id="group-can" class="text-sm font-semibold">Can do</h2>
      <div class="space-y-1 rounded-[10px] border bg-card p-4 shadow-panel" data-testid="agent-alone-safe">
        <p class="flex items-center gap-1.5 text-sm font-medium"><ShieldCheck class="size-4 text-safe" />Nothing outside this call</p>
        <p class="text-xs text-muted-foreground">
          No files, no network, no tools: it reads what it is sent and answers, whatever it is told. Sent to its provider at each call: the conversation
          (its form's values first) and its notes.
        </p>
      </div>
    </section>
  {:else}
    <CanDo bind:spec {job} {offered} program={productName(spec.model.harness ?? "")} {needed} {gives} {displayAvailable} />
  {/if}

  {#if project || agent || job}
    <section class="space-y-2" aria-labelledby="group-started">
      <h2 id="group-started" class="text-sm font-semibold">How it is started</h2>
      <div class="divide-y overflow-hidden rounded-[10px] border bg-card shadow-panel">
        {#if project}
          <div class="flex items-center gap-2 px-4 py-3">
            <Checkbox id="agent-default" bind:checked={spec.default} disabled={agent?.id === project.defaultAgent} />
            <Label for="agent-default" class="font-normal">The project's default agent</Label>
          </div>
          <div class="flex items-start gap-2 px-4 py-3">
            <Checkbox id="agent-remote" bind:checked={spec.remoteStart} data-testid="agent-remote-start" />
            <div class="space-y-0.5">
              <Label for="agent-remote" class="font-normal">Can be started from your phone</Label>
              <p class="text-xs text-muted-foreground">By your paired devices (Settings → Your phone), which then share the session.</p>
            </div>
          </div>
        {/if}
        {#if agent || job}
          <div class="space-y-2 px-4 py-3" data-testid="agent-automations">
            <Label>Started automatically</Label>
            {#if !agent}
              <p class="text-xs text-muted-foreground">An automation runs it at a time, or when a session stops.</p>
            {:else if automations.length}
              <ul class="divide-y overflow-hidden rounded-lg border bg-card text-sm">
                {#each automations as a (a.name)}
                  <li class="flex flex-wrap items-center gap-2 px-3 py-2">
                    <a class="font-medium text-link hover:underline" href={href({ view: "automation", name: a.name })}>{a.name}</a>
                    <StatusBadge status={a.enabled ? "on" : "off"} />
                    <span class="text-muted-foreground">{whenSentence(a.definition)}{#if a.nextAt}, next <When at={a.nextAt} />{/if}</span>
                    {#if a.problems?.length}<span class="text-xs text-danger">{a.problems.length} problem{a.problems.length === 1 ? "" : "s"}</span>{/if}
                  </li>
                {/each}
              </ul>
            {:else}
              <p class="text-xs text-muted-foreground">No automation runs it.</p>
            {/if}
            <div class="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={busy || !job || !spec.name.trim() || !!blocker || lacks.length > 0}
                onclick={() => ((next = "schedule"), void save())}
                data-testid="agent-schedule"
              >
                <CalendarClock />Save and run it on a schedule…
              </Button>
              {#if !job}
                <p class="text-xs text-muted-foreground">Only for jobs (choose its use above).</p>
              {:else if !spec.name.trim()}
                <p class="text-xs text-muted-foreground">An automation finds it by its name: give it one above.</p>
              {:else if lacks.length}
                <p class="text-xs text-muted-foreground">Its result needs {lacks.join(" and ")} first (above).</p>
              {/if}
            </div>
          </div>
        {/if}
        {#if usedBy.length}
          <div class="space-y-2 px-4 py-3" data-testid="agent-used-by">
            <Label>Used by</Label>
            <p class="text-xs text-muted-foreground">They run it when you use them. Its form and result must still fit what they send and read.</p>
            <ul class="divide-y overflow-hidden rounded-lg border bg-card text-sm">
              {#each usedBy as u (`${u.kind}/${u.id}`)}
                <li class="flex flex-wrap items-center gap-2 px-3 py-2">
                  <a
                    class="font-medium text-link hover:underline"
                    href={u.kind === "handler" ? href({ view: "settings", section: "helpers" }) : href({ view: "apps", app: u.id })}>{u.label}</a
                  >
                  <span class="text-muted-foreground">{u.how}</span>
                </li>
              {/each}
            </ul>
          </div>
        {/if}
      </div>
    </section>
  {/if}

  <div class="sticky bottom-0 -mx-1 flex flex-wrap items-center gap-2 border-t bg-background px-1 py-3">
    {#if risks}
      <div class="w-full space-y-2 rounded-md border border-warn/40 bg-warn/5 p-3 text-sm" data-testid="agent-risks">
        <p>This gives the agent more than {agent ? "before" : "a new agent starts with"}: {risks}.</p>
        <div class="flex gap-2">
          <Button type="button" size="sm" variant="destructive" disabled={busy} onclick={() => save(true)} data-testid="agent-confirm-risks">Save anyway</Button>
          <Button type="button" size="sm" variant="ghost" onclick={() => ((risks = null), (next = null))}>Back</Button>
        </div>
      </div>
    {/if}
    {#if toolbox}
      {@const t = toolbox}
      <ToolboxConfirm changes={t} {busy} onconfirm={() => save(t.risks, t.adds)} onback={() => ((toolbox = null), (next = null))} />
    {/if}
    {#if spec.interface !== ""}
      <Button type="button" disabled={busy || !!blocker} onclick={() => ((next = "try"), void save())} data-testid="agent-save-try"><FlaskConical />Save and try</Button>
      <Button type="submit" variant="outline" disabled={busy || !!blocker} data-testid="agent-save">{agent ? "Save" : "Add the agent"}</Button>
    {:else}
      <Button type="submit" disabled={busy || !!blocker} data-testid="agent-save">{agent ? "Save" : "Add the agent"}</Button>
    {/if}
    <Button type="button" variant="ghost" onclick={oncancel}>Cancel</Button>
    {#if blocker}<p class="text-xs text-muted-foreground" data-testid="agent-save-blocker">{blocker}</p>{/if}
    {#if agent && live}
      <p class="text-xs text-muted-foreground">
        {live} running: its sites and learning them apply to {live === 1 ? "it" : "them"} at once, the rest to new sessions.
      </p>
    {/if}
    {#if error}<p class="w-full text-sm text-danger">{error}</p>{/if}
  </div>
</form>
