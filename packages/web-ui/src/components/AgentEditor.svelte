<script lang="ts">
  // An agent of a project, or an ad-hoc one (no project: in a folder, or a folder per session),
  // to add one or edit it, in five groups: what it is for (its goal or name, instructions); what
  // it runs as (its models, each a harness on an account or a provider with a model; the first by
  // default, each session runs with one) and where; what it is given (addons, skills, knowledge);
  // what it may do (permissions, network, sandbox); how it is started (default agent, from the
  // phone, unattended). Its sandbox settings are its own (nothing is inherited; a new one starts
  // with the defaults of new agents); the hosts its account or provider and its
  // addons need are shown "required by". Its addons, knowledge and skills are its own too; its
  // project's skills come on top. A save that widens what it may do is confirmed (D.8). A new
  // agent of a project set up like another but for its models is pointed to that one: one goal,
  // one agent. Its interface (D.18), as JSON: its runs then take an input
  // and give a result back, unattended; the automations that run it are listed with it (I.1),
  // and "Save and run it on a schedule…" saves it, then opens a new automation's form for it.
  import type { Agent, AutomationView, HarnessInfo, Project } from "../lib/contracts.gen";
  import { resultProblems, runsAgent, whenSentence } from "../lib/automations";
  import { accessLabel, chosen, modelsOf, noAccess, sameModel, sameRun } from "../lib/access";
  import { api, ApiError } from "../lib/api";
  import { adHocBody, agentBody, agentLabel, agentSpec, emptyAgent, presetOf, PRESETS, sameSetup, type AgentSpec, type Sandbox } from "../lib/projects.svelte";
  import { href, type Route } from "../lib/router.svelte";
  import { GROUP, SEGMENT, SEGMENT_OFF, SEGMENT_ON } from "../lib/form";
  import { PERMISSION_LABEL, type NetworkMode } from "../lib/agents";
  import { Button } from "$lib/components/ui/button";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import { Textarea } from "$lib/components/ui/textarea";
  import CalendarClock from "@lucide/svelte/icons/calendar-clock";
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import ShieldAlert from "@lucide/svelte/icons/shield-alert";
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
    pendingSkills = [],
    onsaved,
    oncancel,
  }: {
    project?: Project; // none: an ad-hoc agent
    agent?: Agent; // edit it; none: a new one
    start?: AgentSpec; // a new one's starting values (a duplicated agent's, a built-in agent's)
    origin?: string; // a new one: the built-in agent it sets up (D.18)
    pendingSkills?: string[]; // a built-in agent's skills, not in the library until saved
    onsaved: (agent: Agent, then?: Route) => void; // then: where to go next, instead of back
    oncancel: () => void;
  } = $props();

  // the props give the initial values only
  // svelte-ignore state_referenced_locally
  let spec = $state<AgentSpec>(agent ? agentSpec(agent, project ?? { defaultAgent: null }) : (start ?? emptyAgent()));
  // an ad-hoc agent's folder; null: a folder per session (D.18)
  // svelte-ignore state_referenced_locally
  let folder = $state<string | null>(agent?.scope ?? null);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let risks = $state<string | null>(null); // what the last save would widen, to confirm
  let scheduleNext = $state(false); // saved by "Save and run it on a schedule…": the form next
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

  let editing = $state(0); // the model the picker edits

  // the modes every harness of its models offers (pi has only bypass); all while unknown
  const offered = $derived.by(() => {
    const per = spec.models.map((m) => harnesses.find((h) => h.name === m.harness)?.permissions);
    if (per.some((p) => p === undefined)) return undefined;
    return (per[0] ?? []).filter((mode) => per.every((p) => p?.includes(mode)));
  });
  const live = $derived(agent?.connections.length ?? 0);
  // what its past conversations ran with and it no longer lists: they cannot be resumed
  const dropped = $derived(agent ? modelsOf(agent).filter((old) => !spec.models.some((m) => sameRun(m, old))) : []);
  // the accounts (subscriptions) its models run on: an unattended agent is better on an API key
  const onSubscription = $derived([...new Set(spec.models.flatMap((m) => (m.account ? [m.account] : [])))]);
  const twice = $derived(spec.models.some((m, i) => spec.models.findIndex((o) => sameModel(o, m)) !== i));
  // one goal, one agent: another agent of the project set up the same, but for its models
  // (once it has a goal: a new one starts set up like the default agent)
  const twin = $derived(project && !agent && !start && spec.name.trim() ? sameSetup(spec, project.agents, project) : undefined);
  // why it cannot be saved yet
  const blocker = $derived(
    !spec.models.every(chosen)
      ? "Choose what it runs as."
      : twice
        ? "A model is listed twice."
        : folder === ""
          ? "Choose its folder."
          : project && !spec.name.trim()
            ? "Give it a goal."
            : null,
  );
  const movedFolder = $derived(!!agent && !project && (agent.scope ?? null) !== folder);

  // a new agent starts with what the project's default agent runs as
  $effect(() => {
    if (!project || agent || start || spec.models.some(chosen)) return;
    const preferred = project.agents.find((a) => a.id === project.defaultAgent);
    if (preferred) spec.models = modelsOf(preferred);
  });

  function addModel(): void {
    spec.models.push(noAccess());
    editing = spec.models.length - 1;
  }

  function removeModel(i: number): void {
    spec.models.splice(i, 1);
    editing = Math.min(editing, spec.models.length - 1);
  }

  function makeDefault(i: number): void {
    const [m] = spec.models.splice(i, 1);
    if (m) spec.models.unshift(m);
    editing = 0;
  }

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


  // a starting point for an interface (D.18): a form with one request, a result saying how it
  // went and what it found, as an automation needs it (I.3)
  const EXAMPLE = {
    fields: { type: "object", properties: { request: { type: "string", title: "Request" } }, required: ["request"] },
    result: {
      type: "object",
      properties: {
        status: { enum: ["ok", "attention", "failed"], title: "Status" },
        summary: { type: "string", title: "Summary" },
        details: { type: "string", title: "Details" },
      },
      required: ["status", "summary"],
    },
    timeoutSec: 1800,
  };
  // what its result lacks for an automation to run it (I.3); none while the JSON does not parse
  const lacks = $derived.by(() => {
    if (!spec.interface) return [];
    try {
      return resultProblems(JSON.parse(spec.interface)?.result);
    } catch {
      return [];
    }
  });

  // the automations that run it (I.1): an automation finds it by its name, in its project
  let automations = $state<AutomationView[]>([]);
  $effect(() => {
    if (!agent) return;
    api.automations().then(
      (list) => (automations = list.filter((a) => runsAgent(a.definition, agent.name, project?.name ?? null))),
      () => (automations = []),
    );
  });

  // unattended: no one is there to answer its permission requests, so it never asks (bypass);
  // switching to it is confirmed first, the mode it had is given back when unticked
  let permissionsBefore = $state<PermissionMode | null>(null);
  let confirmBypass = $state(false);
  function toggleInterface(on: boolean): void {
    if (on && spec.permissions !== "bypass") {
      confirmBypass = true;
      return;
    }
    spec.interface = on ? JSON.stringify(EXAMPLE, null, 2) : "";
    if (!on && permissionsBefore !== null) {
      spec.permissions = permissionsBefore;
      permissionsBefore = null;
    }
  }
  function acceptBypass(): void {
    permissionsBefore = spec.permissions;
    spec.permissions = "bypass";
    spec.interface = JSON.stringify(EXAMPLE, null, 2);
    confirmBypass = false;
  }

  async function save(confirm = false): Promise<void> {
    busy = true;
    error = null;
    try {
      let saved: Agent;
      if (!project) {
        const body = adHocBody(spec, folder, agent ? (agent.origin ?? null) : (origin ?? null), confirm);
        saved = agent ? await api.updateAdHocAgent(agent.id, body) : await api.createAdHocAgent(body);
      } else {
        const body = agentBody(spec, confirm);
        saved = agent ? await api.updateAgent(project.id, agent.id, body) : await api.createAgent(project.id, body);
      }
      risks = null;
      onsaved(saved, scheduleNext ? { view: "edit-automation", agent: saved.id } : undefined);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.title === "risks not confirmed") risks = e.detail ?? e.title;
      else {
        error = (e as Error).message;
        scheduleNext = false;
      }
    } finally {
      busy = false;
    }
  }

  function submit(event: SubmitEvent): void {
    event.preventDefault();
    scheduleNext = false;
    void save();
  }
</script>

<form class="space-y-10" onsubmit={submit} data-testid="agent-editor">
  <section class="space-y-4" aria-labelledby="group-for">
    <h2 id="group-for" class={GROUP}>What it is for</h2>
    <div class="grid gap-4 sm:grid-cols-2">
      <div class="space-y-2">
        <Label for="agent-name">{project ? "Goal" : "Name"}</Label>
        <Input id="agent-name" bind:value={spec.name} required={!!project} placeholder="e.g. Dev, Review, Contracts check" data-testid="agent-name-input" />
        {#if project}<p class="text-xs text-muted-foreground">Its name: what it is for, never its model.</p>{/if}
      </div>
      <div class="space-y-2">
        <Label for="agent-description">{project ? "More about it" : "Description"}</Label>
        <Input id="agent-description" bind:value={spec.description} placeholder="e.g. reviews the branch, never edits" data-testid="agent-description" />
      </div>
    </div>
    <div class="space-y-2">
      <Label for="agent-instructions">Instructions</Label>
      <Textarea
        id="agent-instructions"
        bind:value={spec.instructions}
        rows={3}
        placeholder="e.g. Review the diff against main and list the issues. Do not edit files."
        data-testid="agent-instructions"
      />
      <p class="text-xs text-muted-foreground">
        Optional. Sent before the request of every session started with one{spec.interface ? ", and before the input of every run" : ""}.
      </p>
    </div>
  </section>

  <section class="space-y-4 border-t pt-8" aria-labelledby="group-runs">
    <h2 id="group-runs" class={GROUP}>Runs as</h2>
    <div class="space-y-2" data-testid="agent-models">
      {#if spec.models.length > 1}
        <ul class="divide-y overflow-hidden rounded-lg border bg-card text-sm" data-testid="agent-model-list">
          {#each spec.models as m, i (i)}
            {@const problem = agent?.models.find((a) => sameModel(m, a))?.problem}
            <li class="flex flex-wrap items-center gap-2 px-3 py-1.5 {editing === i ? 'bg-accent/50' : ''}" data-testid="agent-model">
              <button type="button" class="min-w-0 flex-1 cursor-pointer truncate text-left" onclick={() => (editing = i)}>
                {chosen(m) ? accessLabel(m) : "Choose below"}
                {#if i === 0}<span class="ml-1 rounded bg-accent-soft px-1.5 py-px text-xs font-medium text-accent-soft-foreground">default</span>{/if}
                {#if problem}<span class="block text-xs text-danger">It cannot start now: {problem}</span>{/if}
              </button>
              {#if i > 0}<Button type="button" variant="ghost" size="sm" onclick={() => makeDefault(i)} data-testid="model-make-default">Make default</Button>{/if}
              <Button type="button" variant="ghost" size="sm" onclick={() => removeModel(i)} data-testid="model-remove">Remove</Button>
            </li>
          {/each}
        </ul>
      {/if}
      {#key editing}
        <ModelAccessPicker bind:value={spec.models[editing]!} context={project?.context ?? null} />
      {/key}
      <div class="flex flex-wrap items-center gap-2">
        <Button type="button" variant="outline" size="sm" onclick={addModel} disabled={!spec.models.every(chosen)} data-testid="model-add">Add a model</Button>
        <p class="text-xs text-muted-foreground">
          The first is its default: a session starts with it unless you choose another; an automation always runs it with the first.
        </p>
      </div>
      {#if twice}<p class="text-xs text-danger">A model is listed twice.</p>{/if}
      {#each dropped as m (accessLabel(m))}
        <p class="text-xs text-warn">Its past conversations with {accessLabel(m)} cannot be resumed after this change.</p>
      {/each}
      {#if spec.models.length === 1 && agent?.models[0]?.problem}
        <p class="text-xs text-danger" data-testid="agent-problem">It cannot start now: {agent.models[0].problem}</p>
      {/if}
      {#if twin}
        <p class="text-xs text-warn" data-testid="agent-twin">
          Set up like <a class="text-link hover:underline" href={href({ view: "edit-agent", project: project!.id, id: twin.id })}>{agentLabel(twin)}</a>
          but for its model: add the model to it instead, and choose it when a session starts.
        </p>
      {/if}
    </div>

    {#if project}
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
    <BindingPicker projectId={project?.id} bind:value={spec.bindings} />
    <SkillPicker projectId={project?.id} bind:value={spec.skills} pending={pendingSkills} />
    <KnowledgePicker bind:value={spec.knowledge} />
  </section>

  <section class="space-y-6 border-t pt-8" aria-labelledby="group-may">
    <h2 id="group-may" class={GROUP}>What it may do</h2>
    <div class="space-y-2" data-testid="agent-preset">
      <Label>Safety preset</Label>
      <div class="flex flex-wrap items-center gap-3">
        <div class="inline-flex rounded-lg border bg-muted p-0.5" role="radiogroup" aria-label="safety preset">
          {#each PRESETS as p (p.id)}
            <button
              type="button"
              role="radio"
              aria-checked={preset?.id === p.id}
              disabled={spec.interface !== "" && p.sandbox.permissions !== "bypass"}
              class="{SEGMENT} disabled:cursor-not-allowed disabled:opacity-50 {preset?.id === p.id ? SEGMENT_ON : SEGMENT_OFF}"
              title={spec.interface !== "" && p.sandbox.permissions !== "bypass" ? "Runs unattended: it never asks" : undefined}
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
                disabled={(offered !== undefined && !offered.includes(m.mode)) || (spec.interface !== "" && m.mode !== "bypass")}
                class="{SEGMENT} disabled:cursor-not-allowed disabled:opacity-50 {spec.permissions === m.mode ? SEGMENT_ON : SEGMENT_OFF}"
                title={spec.interface !== "" && m.mode !== "bypass" ? "Runs unattended" : undefined}
                onclick={() => (spec.permissions = m.mode)}
                data-testid={`permissions-${m.mode}`}
              >
                {m.label}
              </button>
            {/each}
          </div>
          <p class="text-xs {spec.permissions === 'bypass' ? 'text-warn' : 'text-muted-foreground'}">
            {PERMISSIONS.find((m) => m.mode === spec.permissions)?.hint}
            {spec.interface !== "" ? "Fixed: it runs unattended." : "A session can change it."}
          </p>
          {#if offered && !offered.includes(spec.permissions)}
            <p class="text-xs text-danger">Its agent programs do not all have this mode (they all offer: {offered.join(", ") || "none in common"}).</p>
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
    {#if agent?.models.some((m) => m.requiredHosts?.length)}
      <div class="space-y-2" data-testid="agent-required-hosts">
        <p class="text-xs text-muted-foreground">Also allowed, as the model a session runs with and its addons require:</p>
        {#each agent.models as m (accessLabel(m))}
          {#if m.requiredHosts?.length}
            <div class="space-y-0.5 text-xs">
              {#if agent.models.length > 1}<p class="font-medium">With {accessLabel(m)}</p>{/if}
              <ul class="space-y-0.5">
                {#each m.requiredHosts as r (r.host + r.by)}
                  <li><span class="font-mono">{r.host}</span> <span class="text-muted-foreground">required by {r.by}</span></li>
                {/each}
              </ul>
            </div>
          {/if}
        {/each}
      </div>
    {/if}
    {/if}
  </section>

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
    <div class="space-y-2" data-testid="agent-interface">
      <div class="flex items-start gap-2">
        <Checkbox id="agent-has-interface" checked={spec.interface !== "" || confirmBypass} onCheckedChange={(c) => toggleInterface(c === true)} data-testid="agent-has-interface" />
        <div class="space-y-0.5">
          <Label for="agent-has-interface" class="font-normal">Runs unattended: an input in, a result out</Label>
          {#if spec.interface === ""}
            <p class="text-xs text-muted-foreground">Its runs are started with a form and give a result back; no one can prompt them.</p>
          {:else}
            <p class="text-xs text-muted-foreground">
              Its interface, as JSON Schemas: the form a run is started with (<code>fields</code>), what it works on (<code>subject</code>:
              <code>"skill"</code>, mounted read-only), the result its final message must hold (<code>result</code>), and how long a turn may take
              (<code>timeoutSec</code>).
            </p>
          {/if}
        </div>
      </div>
      {#if confirmBypass}
        <div class="flex items-start gap-3 rounded-md border border-warn/40 bg-warn/5 p-3" role="alertdialog" aria-labelledby="bypass-title" data-testid="agent-confirm-bypass" {@attach (el) => el.scrollIntoView({ block: "center", behavior: "smooth" })}>
          <ShieldAlert class="size-5 shrink-0 text-warn" />
          <div class="space-y-2">
            <p id="bypass-title" class="text-sm font-medium">Permissions: {PERMISSION_LABEL[spec.permissions]} → {PERMISSION_LABEL.bypass}</p>
            <p class="text-xs text-muted-foreground">It will never ask before acting.</p>
            <div class="flex gap-2">
              <Button type="button" size="sm" variant="destructive" onclick={acceptBypass} data-testid="agent-accept-bypass">Switch to {PERMISSION_LABEL.bypass}</Button>
              <Button type="button" size="sm" variant="ghost" onclick={() => (confirmBypass = false)}>Cancel</Button>
            </div>
          </div>
        </div>
      {:else if spec.interface !== ""}
        <p class="flex items-center gap-1.5 text-xs font-medium text-warn" data-testid="agent-unattended-permissions">
          <ShieldAlert class="size-4" />
          Permissions: {PERMISSION_LABEL.bypass}{permissionsBefore !== null ? ` (was ${PERMISSION_LABEL[permissionsBefore]})` : ""}
        </p>
      {/if}
      {#if spec.interface !== "" && onSubscription.length}
        <p class="text-xs text-muted-foreground" data-testid="agent-unattended-subscription">
          It runs on a subscription ({onSubscription.join(", ")}): subscription plans are for ordinary, individual use (their vendors' terms). For an
          agent that runs on its own, an API key (a provider) is recommended.
        </p>
      {/if}
      {#if spec.interface !== ""}
        <Textarea bind:value={spec.interface} rows={14} class="font-mono text-xs" spellcheck={false} data-testid="agent-interface-json" />
        {#if lacks.length}
          <p class="text-xs text-warn" data-testid="agent-interface-lacks">An automation can run it only when its <code>result</code> has {lacks.join(" and ")}.</p>
        {/if}
      {/if}
    </div>
    {#if agent || spec.interface !== ""}
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
            disabled={busy || spec.interface === "" || !spec.name.trim() || !!blocker || lacks.length > 0}
            onclick={() => ((scheduleNext = true), void save())}
            data-testid="agent-schedule"
          >
            <CalendarClock />Save and run it on a schedule…
          </Button>
          {#if spec.interface === ""}
            <p class="text-xs text-muted-foreground">Only an agent that runs unattended: tick it above.</p>
          {:else if !spec.name.trim()}
            <p class="text-xs text-muted-foreground">An automation finds it by its name: give it one above.</p>
          {:else if lacks.length}
            <p class="text-xs text-muted-foreground">Its result needs {lacks.join(" and ")} first (above).</p>
          {/if}
        </div>
      </div>
    {/if}
  </section>

  <div class="sticky bottom-0 -mx-1 flex flex-wrap items-center gap-2 border-t bg-background px-1 py-3">
    {#if risks}
      <div class="w-full space-y-2 rounded-md border border-warn/40 bg-warn/5 p-3 text-sm" data-testid="agent-risks">
        <p>This gives the agent more than {agent ? "before" : "a new agent gets by default"}: {risks}.</p>
        <div class="flex gap-2">
          <Button type="button" size="sm" variant="destructive" disabled={busy} onclick={() => save(true)} data-testid="agent-confirm-risks">Save anyway</Button>
          <Button type="button" size="sm" variant="ghost" onclick={() => ((risks = null), (scheduleNext = false))}>Back</Button>
        </div>
      </div>
    {/if}
    <Button type="submit" disabled={busy || !!blocker} data-testid="agent-save">{agent ? "Save" : "Add the agent"}</Button>
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
