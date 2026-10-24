<script lang="ts">
  // An agent of a project, or an ad-hoc one (no project: in a folder, or a folder per session),
  // to add one or edit it. First how it is used: chatted with, briefed (its interface without a
  // result, D.18: a form starts each session, then a chat) or given a job (its interface: a form
  // in, a result out, unattended); a change of use that drops a saved brief or result says so.
  // Then in groups, each needing only what is above it: what it is for (its goal or name); a
  // brief's or a job's form, and a job's result, edited as fields (JobEditor); its instructions,
  // which may name the form's fields, `{{key}}` (D.18), inserted by their labels (a field not
  // saved yet keeps its placeholders when its label, so its key, changes);
  // who works (an agent program, or the model alone: D.18, no sandbox, no tools, only providers;
  // then its model, a harness on an account or a provider with a model; a session may run with
  // another, picked when it starts) and where; what it is given (addons, skills, knowledge);
  // what it may do (permissions, network, sandbox); how it is started (default agent, from the
  // phone, unattended). Its sandbox settings are its own (nothing is inherited; a new one starts
  // with the defaults of new agents); the hosts its account or provider and its
  // addons need are shown "required by". Its addons, knowledge and skills are its own too; its
  // project's skills come on top. A save that widens what it may do is confirmed (D.8). A new
  // agent of a project set up like another but for its model is pointed to that one: one goal,
  // one agent. An agent with a job never asks (bypass, confirmed when chosen); the automations
  // that run it are listed with it (I.1); "Save and try" saves it, then opens its page and its
  // run form; "Save and run it on a schedule…" saves it, then opens a new automation's form. On
  // the model alone, what only a sandbox has (addons, skills, its permissions, network and
  // sandbox, a folder) is not offered: each says why in one line.
  import type { Agent, AgentOrigin, AutomationView, HarnessInfo, Project, UseRef } from "../lib/contracts.gen";
  import { resultProblems, runsAgent, whenSentence } from "../lib/automations";
  import { dependents } from "../lib/apps";
  import { accessLabel, accessOf, chosen, sameRun } from "../lib/access";
  import { api, ApiError } from "../lib/api";
  import { agentBody, agentLabel, agentSpec, emptyAgent, homeOf, presetOf, PRESETS, sameSetup, withModelAlone, type AgentSpec, type Home, type Sandbox } from "../lib/projects.svelte";
  import { href, type Route } from "../lib/router.svelte";
  import { GROUP, SEGMENT, SEGMENT_OFF, SEGMENT_ON } from "../lib/form";
  import { PERMISSION_LABEL, type NetworkMode } from "../lib/agents";
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
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import ClipboardList from "@lucide/svelte/icons/clipboard-list";
  import NotebookPen from "@lucide/svelte/icons/notebook-pen";
  import MessageSquare from "@lucide/svelte/icons/message-square";
  import ShieldAlert from "@lucide/svelte/icons/shield-alert";
  import ShieldCheck from "@lucide/svelte/icons/shield-check";
  import Bot from "@lucide/svelte/icons/bot";
  import Zap from "@lucide/svelte/icons/zap";
  import PromptBox from "./PromptBox.svelte";
  import BindingPicker from "./BindingPicker.svelte";
  import FolderPicker from "./FolderPicker.svelte";
  import HostList from "./HostList.svelte";
  import KnowledgePicker from "./KnowledgePicker.svelte";
  import SkillPicker from "./SkillPicker.svelte";
  import StatusBadge from "./StatusBadge.svelte";
  import When from "./When.svelte";
  import ModelAccessPicker from "./ModelAccessPicker.svelte";

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
  let spec = $state<AgentSpec>(agent ? agentSpec(agent, project ?? { defaultAgent: null }) : (start ?? emptyAgent()));
  // an ad-hoc agent's folder; null: a folder per session (D.18)
  // svelte-ignore state_referenced_locally
  let folder = $state<string | null>(agent ? (agent.scope ?? null) : (startFolder ?? null));
  let busy = $state(false);
  let error = $state<string | null>(null);
  let risks = $state<string | null>(null); // what the last save would widen, to confirm
  // saved by "Save and try" (its page, to run it) or "Save and run it on a schedule…" (the form)
  let next = $state<"try" | "schedule" | null>(null);
  let displayAvailable = $state(false); // the daemon found a Wayland display (A.6)
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
  const PROGRAMS = [
    { alone: false, label: "An agent program", hint: "Claude Code, Codex…: it works on files and runs tools, in its sandbox.", icon: Bot },
    { alone: true, label: "The model alone", hint: "One model call a turn, in seconds: no files, no tools, no sandbox. On a provider.", icon: Zap },
  ];
  function chooseProgram(alone: boolean): void {
    if (alone === spec.modelAlone) return;
    spec = withModelAlone(spec, alone);
    if (alone) folder = null;
    customizing = false;
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
  type Confinement = Agent["confinement"];

  const MODES: { mode: NetworkMode; label: string; hint: string }[] = [
    { mode: "none", label: "No network", hint: "Nothing: no model API either, unless the agent runs a local model." },
    { mode: "filtered", label: "Filtered", hint: "Only the hosts below, plus those its account or provider and its addons require." },
    { mode: "open", label: "Open", hint: "Anything on the internet (and your LAN)." },
  ];

  const PERMISSIONS: { mode: PermissionMode; label: string; hint: string }[] = [
    { mode: "ask", label: PERMISSION_LABEL.ask, hint: "You answer each of its requests (edit a file, run a command)." },
    { mode: "accept-edits", label: PERMISSION_LABEL["accept-edits"], hint: "It edits files without asking; anything else is asked." },
    {
      mode: "bypass",
      label: PERMISSION_LABEL.bypass,
      hint: "It never asks: only its sandbox and its network limit what it runs.",
    },
  ];

  const CONFINEMENTS: { value: Confinement; label: string; hint: string }[] = [
    { value: "strict", label: "Strict", hint: "A locked-down container: the default." },
    {
      value: "nested",
      label: "Runs containers",
      hint: "Podman inside the sandbox (e.g. for tests in containers): a weaker confinement.",
    },
    { value: "privileged", label: "Privileged", hint: "Last resort: a privileged container is about as safe as no sandbox." },
  ];

  // a safety preset sets its permissions, network and sandbox at once; "Customize" shows them
  // (open from the start when they match no preset)
  const preset = $derived(presetOf(spec));
  // svelte-ignore state_referenced_locally
  let customizing = $state(presetOf(spec) === undefined);
  function applyPreset(sandbox: Sandbox): void {
    Object.assign(spec, sandbox);
  }
  const hostsNote = $derived(
    spec.network === "filtered" && spec.allow.length ? ` ${spec.allow.length} host${spec.allow.length === 1 ? "" : "s"} allowed.` : "",
  );
  const summary = $derived(
    preset
      ? `${preset.hint}; a strict sandbox.${hostsNote}`
      : `Its own: ${PERMISSION_LABEL[spec.permissions].toLowerCase()}, ${MODES.find((m) => m.mode === spec.network)?.label.toLowerCase()} network${spec.network === "filtered" && spec.egress === "log-only" ? " (log only)" : ""}, ${CONFINEMENTS.find((c) => c.value === spec.confinement)?.label.toLowerCase()} sandbox.${hostsNote}`,
  );
  const summaryTone = $derived(
    spec.confinement === "privileged" ? "text-danger" : spec.network === "open" || spec.confinement === "nested" ? "text-warn" : "text-muted-foreground",
  );


  // how it is used, the first choice, as cards saying each the same three things: how it starts,
  // who is there, how it ends
  const USES: { use: Use; label: string; hint: string; icon: typeof MessageSquare }[] = [
    { use: "chat", label: "Chat", hint: "Say what to do, or nothing; you talk with it until you are done.", icon: MessageSquare },
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
          ? "Give it a goal."
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

  async function save(confirm = false): Promise<void> {
    busy = true;
    error = null;
    try {
      // its home: kept when it exists; a new one's, its project's, or the app it is set up for
      const home: Home = agent
        ? { ...homeOf(agent), ...(agent.projectId ? {} : { scope: folder }) }
        : project
          ? { projectId: project.id }
          : { app: origin?.kind === "app" ? origin.name : null, scope: folder };
      const body = agentBody({ ...spec, origin: agent ? (agent.origin ?? null) : (origin ?? null) }, home, confirm);
      const saved = agent ? await api.updateAgent(agent.id, body) : await api.createAgent(body);
      risks = null;
      onsaved(saved, next === "schedule" ? { view: "edit-automation", agent: saved.id } : next === "try" ? { view: "agent", id: saved.id } : undefined);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.title === "risks not confirmed") risks = e.detail ?? e.title;
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

<form class="space-y-10" onsubmit={submit} data-testid="agent-editor">
  <section class="space-y-2" aria-labelledby="group-use" data-testid="agent-use">
    <h2 id="group-use" class="text-base font-semibold">How will you use it?</h2>
    <div class="grid gap-3 sm:grid-cols-3" role="radiogroup" aria-labelledby="group-use">
      {#each USES as u (u.label)}
        {@const on = confirmBypass ? u.use === "job" : u.use === use}
        <button
          type="button"
          role="radio"
          aria-checked={on}
          class="flex cursor-pointer items-start gap-3 rounded-lg border bg-card p-4 text-left transition-colors hover:border-foreground/30 {on ? 'border-primary ring-1 ring-primary' : ''}"
          onclick={() => chooseUse(u.use)}
          data-testid="agent-use-{u.use}"
        >
          <u.icon class="mt-0.5 size-5 shrink-0 {on ? 'text-primary' : 'text-muted-foreground'}" />
          <span class="space-y-0.5">
            <span class="block text-sm font-medium">{u.label}</span>
            <span class="block text-xs text-muted-foreground">{u.hint}</span>
          </span>
        </button>
      {/each}
    </div>
    {#if confirmBypass}
      <div class="flex items-start gap-3 rounded-md border border-warn/40 bg-warn/5 p-3" role="alertdialog" aria-labelledby="bypass-title" data-testid="agent-confirm-bypass">
        <ShieldAlert class="size-5 shrink-0 text-warn" />
        <div class="space-y-2">
          <p id="bypass-title" class="text-sm font-medium">Permissions: {PERMISSION_LABEL[spec.permissions]} → {PERMISSION_LABEL.bypass}</p>
          <p class="text-xs text-muted-foreground">A job runs alone, so it never asks before acting. Only what it may reach (below) limits it.</p>
          <div class="flex gap-2">
            <Button type="button" size="sm" variant="destructive" onclick={acceptBypass} data-testid="agent-accept-bypass">Switch to {PERMISSION_LABEL.bypass}</Button>
            <Button type="button" size="sm" variant="ghost" onclick={() => (confirmBypass = false)}>Cancel</Button>
          </div>
        </div>
      </div>
    {/if}
    {#if drops}<p class="text-xs text-warn" data-testid="agent-use-drops">{drops}</p>{/if}
  </section>

  <section class="space-y-4 border-t pt-8" aria-labelledby="group-for">
    <h2 id="group-for" class={GROUP}>What it is for</h2>
    <div class="grid gap-4 sm:grid-cols-2">
      <div class="space-y-2">
        <Label for="agent-name">{project ? "Goal" : "Name"}</Label>
        <Input id="agent-name" bind:value={spec.name} required={!!project} placeholder="e.g. Dev, Review, Contracts check" data-testid="agent-name-input" />
        {#if project}<p class="text-xs text-muted-foreground">Name it by its purpose, not its model.</p>{/if}
      </div>
      <div class="space-y-2">
        <Label for="agent-description">Description</Label>
        <Input id="agent-description" bind:value={spec.description} placeholder="e.g. reviews the branch, never edits" data-testid="agent-description" />
      </div>
    </div>
  </section>

  {#if spec.interface !== ""}
    <section class="space-y-4 border-t pt-8" aria-labelledby="group-job">
      <JobEditor bind:value={spec.interface} fresh={!agent?.interface && !start?.interface} brief={use === "brief"} />
      {#if lacks.length}
        <p class="text-xs text-warn" data-testid="agent-interface-lacks">An automation can run it only when its <code>result</code> has {lacks.join(" and ")}.</p>
      {/if}
    </section>
  {/if}

  <section class="space-y-4 border-t pt-8" aria-labelledby="group-instructions">
    <h2 id="group-instructions" class={GROUP}>Its instructions</h2>
    <div class="space-y-2">
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
    </div>
  </section>

  <section class="space-y-4 border-t pt-8" aria-labelledby="group-runs">
    <h2 id="group-runs" class={GROUP}>Who works</h2>
    <div class="grid gap-3 sm:grid-cols-2" role="radiogroup" aria-label="who works" data-testid="agent-program">
      {#each PROGRAMS as p (p.label)}
        {@const on = spec.modelAlone === p.alone}
        <button
          type="button"
          role="radio"
          aria-checked={on}
          class="flex cursor-pointer items-start gap-3 rounded-lg border bg-card p-3 text-left transition-colors hover:border-foreground/30 {on ? 'border-primary ring-1 ring-primary' : ''}"
          onclick={() => chooseProgram(p.alone)}
          data-testid={p.alone ? "agent-program-model" : "agent-program-harness"}
        >
          <p.icon class="mt-0.5 size-5 shrink-0 {on ? 'text-primary' : 'text-muted-foreground'}" />
          <span class="space-y-0.5">
            <span class="block text-sm font-medium">{p.label}</span>
            <span class="block text-xs text-muted-foreground">{p.hint}</span>
          </span>
        </button>
      {/each}
    </div>
    <div class="space-y-2" data-testid="agent-model">
      {#key spec.modelAlone}
        <ModelAccessPicker bind:value={spec.model} area={project?.area ?? null} alone={spec.modelAlone} />
      {/key}
      <p class="text-xs text-muted-foreground">A session starts with it; you can pick another for one session when you start it. An automation always runs it with this one.</p>
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
    </div>

    {#if spec.modelAlone}
      <p class="text-xs text-muted-foreground" data-testid="agent-no-folder">No folder: the model alone reads what its form, the conversation and its knowledge give it.</p>
    {:else if project}
      <p class="text-xs text-muted-foreground">It works in the project's folder, <code>{project.folder}</code>.</p>
    {:else}
      <div class="space-y-2" data-testid="agent-folder">
        <Label>Works in</Label>
        <div class="inline-flex rounded-lg border bg-muted p-0.5" role="radiogroup" aria-label="folder">
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
      </div>
    {/if}
  </section>

  <section class="space-y-6 border-t pt-8" aria-labelledby="group-given">
    <h2 id="group-given" class={GROUP}>What it is given</h2>
    {#if spec.modelAlone}
      <KnowledgePicker bind:value={spec.knowledge} />
      <p class="text-xs text-muted-foreground">Its notes are put into each call (at most 192 KiB in all).</p>
      <ul class="space-y-1 text-xs text-muted-foreground" data-testid="agent-alone-not-given">
        <li>No addons: an addon is a tool, it needs an agent program.</li>
        <li>No skills: a skill can run scripts, it needs an agent program.</li>
      </ul>
    {:else}
      <BindingPicker projectId={project?.id} bind:value={spec.bindings} />
      <SkillPicker projectId={project?.id} bind:value={spec.skills} pending={pendingSkills} />
      <KnowledgePicker bind:value={spec.knowledge} />
    {/if}
  </section>

  <section class="space-y-6 border-t pt-8" aria-labelledby="group-may">
    <h2 id="group-may" class={GROUP}>What it may do</h2>
    {#if spec.modelAlone}
      <div class="space-y-1 rounded-lg border border-ok/30 bg-ok/5 p-3" data-testid="agent-alone-safe">
        <p class="flex items-center gap-1.5 text-sm font-medium text-ok"><ShieldCheck class="size-4" />Nothing outside this call</p>
        <p class="text-xs text-muted-foreground">
          No files, no network, no tools: it reads what it is sent and answers, whatever it is told. Sent to its provider at each call: the conversation
          (its form's values first) and its knowledge's notes.
        </p>
      </div>
    {:else}
    {#if job}
      <div class="space-y-1">
        <p class="flex items-center gap-1.5 text-xs font-medium text-warn" data-testid="agent-unattended-permissions">
          <ShieldAlert class="size-4" />
          It never asks before acting ({PERMISSION_LABEL.bypass}{permissionsBefore !== null ? `, was ${PERMISSION_LABEL[permissionsBefore]}` : ""}): its network and its sandbox are all that limit it.
        </p>
        {#if onSubscription}
          <p class="text-xs text-muted-foreground" data-testid="agent-unattended-subscription">
            It runs on a subscription ({onSubscription}): subscription plans are for ordinary, individual use (their vendors' terms). For an
            agent that runs on its own, an API key (a provider) is recommended.
          </p>
        {/if}
      </div>
    {/if}
    <div class="space-y-2" data-testid="agent-preset">
      <Label>Safety preset</Label>
      <div class="flex flex-wrap items-center gap-3">
        <div class="inline-flex rounded-lg border bg-muted p-0.5" role="radiogroup" aria-label="safety preset">
          {#each PRESETS as p (p.id)}
            <button
              type="button"
              role="radio"
              aria-checked={preset?.id === p.id}
              disabled={job && p.sandbox.permissions !== "bypass"}
              class="{SEGMENT} disabled:cursor-not-allowed disabled:opacity-50 {preset?.id === p.id ? SEGMENT_ON : SEGMENT_OFF}"
              title={job && p.sandbox.permissions !== "bypass" ? "Runs unattended: it never asks" : undefined}
              onclick={() => applyPreset(p.sandbox)}
              data-testid={`agent-preset-${p.id}`}
            >
              {p.label}
            </button>
          {/each}
        </div>
        <Button type="button" variant="ghost" size="sm" onclick={() => (customizing = !customizing)} aria-expanded={customizing} data-testid="agent-customize">
          <ChevronDown class="transition-transform {customizing ? 'rotate-180' : ''}" />{preset ? "Customize" : "Its own settings"}
        </Button>
      </div>
      <p class="text-xs {summaryTone}" data-testid="agent-preset-summary">{summary}</p>
    </div>

    {#if customizing}
      <div class="space-y-6 rounded-lg border p-4" data-testid="agent-custom">
        <div class="space-y-2" data-testid="agent-permissions">
          <Label>Permissions</Label>
          <div class="inline-flex rounded-lg border bg-muted p-0.5" role="radiogroup" aria-label="permissions">
            {#each PERMISSIONS as m (m.mode)}
              <button
                type="button"
                role="radio"
                aria-checked={spec.permissions === m.mode}
                disabled={(offered !== undefined && !offered.includes(m.mode)) || (job && m.mode !== "bypass")}
                class="{SEGMENT} disabled:cursor-not-allowed disabled:opacity-50 {spec.permissions === m.mode ? SEGMENT_ON : SEGMENT_OFF}"
                title={job && m.mode !== "bypass" ? "Runs unattended" : undefined}
                onclick={() => (spec.permissions = m.mode)}
                data-testid={`permissions-${m.mode}`}
              >
                {m.label}
              </button>
            {/each}
          </div>
          <p class="text-xs {spec.permissions === 'bypass' ? 'text-warn' : 'text-muted-foreground'}">
            {PERMISSIONS.find((m) => m.mode === spec.permissions)?.hint}
            {job ? "Fixed: it runs unattended." : "A session can change it."}
          </p>
          {#if offered && !offered.includes(spec.permissions)}
            <p class="text-xs text-danger">Its agent program does not have this mode (it offers: {offered.join(", ")}).</p>
          {/if}
        </div>

        <div class="space-y-2" data-testid="agent-network">
          <Label>Network</Label>
          <div class="inline-flex rounded-lg border bg-muted p-0.5" role="radiogroup" aria-label="network">
            {#each MODES as m (m.mode)}
              <button
                type="button"
                role="radio"
                aria-checked={spec.network === m.mode}
                class="{SEGMENT} {spec.network === m.mode ? SEGMENT_ON : SEGMENT_OFF}"
                onclick={() => (spec.network = m.mode)}
                data-testid={`network-${m.mode}`}
              >
                {m.label}
              </button>
            {/each}
          </div>
          <p class="text-xs {spec.network === 'open' ? 'text-warn' : 'text-muted-foreground'}">{MODES.find((m) => m.mode === spec.network)?.hint}</p>
          {#if spec.network === "filtered"}
            <div class="space-y-4 pt-1">
              <div class="flex items-start gap-2">
                <Checkbox id="agent-log-only" checked={spec.egress === "log-only"} onCheckedChange={(c) => (spec.egress = c === true ? "log-only" : "enforce")} data-testid="agent-log-only" />
                <div class="space-y-0.5">
                  <Label for="agent-log-only">Log only</Label>
                  <p class="text-xs text-muted-foreground">Lets everything through and records it: allow the hosts the project needs, then turn it off.</p>
                </div>
              </div>
            </div>
          {/if}
        </div>

        <div class="space-y-2">
          <Label>Sandbox</Label>
          <div class="inline-flex rounded-lg border bg-muted p-0.5" role="radiogroup" aria-label="confinement">
            {#each CONFINEMENTS as c (c.value)}
              <button
                type="button"
                role="radio"
                aria-checked={spec.confinement === c.value}
                class="{SEGMENT} {spec.confinement === c.value ? SEGMENT_ON : SEGMENT_OFF}"
                onclick={() => (spec.confinement = c.value)}
                data-testid={`confinement-${c.value}`}
              >
                {c.label}
              </button>
            {/each}
          </div>
          <p class="text-xs {spec.confinement === 'strict' ? 'text-muted-foreground' : spec.confinement === 'privileged' ? 'text-danger' : 'text-warn'}">
            {CONFINEMENTS.find((c) => c.value === spec.confinement)?.hint}
          </p>
          <div class="flex items-start gap-2 pt-2">
            <Checkbox id="agent-display" bind:checked={spec.display} disabled={!displayAvailable && !spec.display} />
            <div class="space-y-0.5">
              <Label for="agent-display">Show windows on my screen and paste images</Label>
              <p class="text-xs text-muted-foreground">
                {#if displayAvailable}
                  It can open windows on your desktop (e.g. the playwright browser) and use your clipboard, so images can be pasted in its
                  terminal; it then also reads what you copy. Without it, its browser is headless.
                {:else}
                  No Wayland display found by the daemon.
                {/if}
              </p>
            </div>
          </div>
        </div>
      </div>
    {/if}

    {#if spec.network === "filtered"}
    <div class="space-y-1.5" data-testid="agent-hosts">
      <Label>Allowed hosts</Label>
      <HostList value={spec.allow} onchange={(next) => { spec.allow = next; }} empty="None." />
    </div>
    {#if agent?.model.requiredHosts?.length}
      <div class="space-y-2" data-testid="agent-required-hosts">
        <p class="text-xs text-muted-foreground">Also allowed, as its model and its addons require:</p>
        <ul class="space-y-0.5 text-xs">
          {#each agent.model.requiredHosts as r (r.host + r.by)}
            <li><span class="font-mono">{r.host}</span> <span class="text-muted-foreground">required by {r.by}</span></li>
          {/each}
        </ul>
      </div>
    {/if}
    {/if}
    {/if}
  </section>

  {#if project || agent || job}
  <section class="space-y-3 border-t pt-8" aria-labelledby="group-started">
    <h2 id="group-started" class={GROUP}>How it is started</h2>
    {#if project}
      <div class="flex items-center gap-2">
        <Checkbox id="agent-default" bind:checked={spec.default} disabled={agent?.id === project.defaultAgent} />
        <Label for="agent-default" class="font-normal">The project's default agent</Label>
      </div>
      <div class="flex items-start gap-2">
        <Checkbox id="agent-remote" bind:checked={spec.remoteStart} data-testid="agent-remote-start" />
        <div class="space-y-0.5">
          <Label for="agent-remote" class="font-normal">Can be started from your phone</Label>
          <p class="text-xs text-muted-foreground">By your paired devices (Settings → Remote), which then share the session.</p>
        </div>
      </div>
    {/if}
    {#if agent || job}
      <div class="space-y-2" data-testid="agent-automations">
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
            <p class="text-xs text-muted-foreground">Only for jobs (choose at the top).</p>
          {:else if !spec.name.trim()}
            <p class="text-xs text-muted-foreground">An automation finds it by its name: give it one above.</p>
          {:else if lacks.length}
            <p class="text-xs text-muted-foreground">Its result needs {lacks.join(" and ")} first (above).</p>
          {/if}
        </div>
      </div>
    {/if}
    {#if usedBy.length}
      <div class="space-y-2" data-testid="agent-used-by">
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
  </section>
  {/if}

  <div class="sticky bottom-0 -mx-1 flex flex-wrap items-center gap-2 border-t bg-background px-1 py-3">
    {#if risks}
      <div class="w-full space-y-2 rounded-md border border-warn/40 bg-warn/5 p-3 text-sm" data-testid="agent-risks">
        <p>This gives the agent more than {agent ? "before" : "a new agent gets by default"}: {risks}.</p>
        <div class="flex gap-2">
          <Button type="button" size="sm" variant="destructive" disabled={busy} onclick={() => save(true)} data-testid="agent-confirm-risks">Save anyway</Button>
          <Button type="button" size="sm" variant="ghost" onclick={() => ((risks = null), (next = null))}>Back</Button>
        </div>
      </div>
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
        {live} running: hosts and log-only apply to {live === 1 ? "it" : "them"} at once, the rest to new sessions.
      </p>
    {/if}
    {#if error}<p class="w-full text-sm text-danger">{error}</p>{/if}
  </div>
</form>
