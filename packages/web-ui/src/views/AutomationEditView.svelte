<script lang="ts">
  // An automation's form (I.1), a new one or one it can say (`name`: changed): when (a time, or a
  // session that stops) and what runs (one of your agents with an interface, with its input; or a
  // route of one of your apps). handlerd checks it as it is filled in (what it will do, its warnings
  // and problems, its first run) and writes it as the automation.toml of a new folder ("Create and
  // turn on" is the approval, I.7) or over the one it has (on, it stays on: as an edit of its
  // file). A script starts from an example (the Automations page). `agent`: the agent to run.
  import ShieldAlert from "@lucide/svelte/icons/shield-alert";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import * as NativeSelect from "$lib/components/ui/native-select";
  import PageHeader from "../components/PageHeader.svelte";
  import PageTitle from "../components/PageTitle.svelte";
  import RunFields from "../components/RunFields.svelte";
  import When from "../components/When.svelte";
  import { accessLabel } from "../lib/access";
  import { exactTime } from "../lib/agents";
  import { api } from "../lib/api";
  import { DAYS, formOf, howOften, SCHEDULE_PRESETS, scheduleOf, scheduleProblem, suggestName, WEEKDAYS, type Day, type ScheduleForm } from "../lib/automations";
  import type { Agent, App, Automation, AutomationCheck, AutomationView, Project } from "../lib/contracts.gen";
  import { GROUP, SEGMENT, SEGMENT_OFF, SEGMENT_ON } from "../lib/form";
  import { agentLabel } from "../lib/projects.svelte";
  import { fieldsOf, fieldValues, type Schema } from "../lib/runs";
  import { href, navigate } from "../lib/router.svelte";

  let { name: editing, agent: chosenAgent }: { name?: string; agent?: string } = $props();

  let agents = $state<Agent[]>([]);
  let projectList = $state<Project[]>([]);
  let apps = $state<App[]>([]);
  let loaded = $state(false);
  let error = $state<string | null>(null);

  let on = $state<"time" | "stop">("time");
  let every = $state({ n: 1, unit: "h" as "m" | "h" });
  let at = $state({ at: "08:30", days: [...DAYS] as Day[] });
  let timeKind = $state<"every" | "at">("at");
  let stopProject = $state(""); // "": any project's session (and those outside projects)

  let what = $state<"agent" | "app">("agent");
  // svelte-ignore state_referenced_locally
  let agentId = $state(chosenAgent ?? "");
  let values = $state<Record<string, unknown>>({});
  let subject = $state("");
  let app = $state("");
  let call = $state("POST /api/");

  let name = $state("");
  let named = $state(false); // the person typed a name: no more suggestions
  let description = $state("");

  let enabled = $state(false); // the one changed is on
  let check = $state<AutomationCheck | null>(null);
  let checkError = $state<string | null>(null);
  let busy = $state(false);

  $effect(() => {
    Promise.all([api.agents(), api.projects(), api.apps(), editing ? api.automation(editing) : null]).then(
      ([a, p, x, current]) => {
        agents = a.filter((ag) => ag.interface);
        projectList = p;
        apps = x;
        if (current) fill(current);
        if (!agents.some((ag) => ag.id === agentId)) agentId = agents.find((ag) => ag.name)?.id ?? "";
        app ||= apps[0]?.name ?? "";
        if (!current && !agents.length && apps.length) what = "app";
        loaded = true;
      },
      (e: Error) => (error = e.message),
    );
  });

  const agent = $derived(agents.find((a) => a.id === agentId));
  const projectOf = (a: Agent): string | null => projectList.find((p) => p.id === a.projectId)?.name ?? null;
  const fields = $derived(fieldsOf(agent?.interface?.fields as Schema | undefined));
  const schedule = $derived<ScheduleForm | null>(
    on === "stop" ? null : timeKind === "every" ? { kind: "every", ...every } : { kind: "at", ...at },
  );
  const scheduleWrong = $derived(schedule ? scheduleProblem(schedule) : null);

  // the automation changed, in the form
  function fill(current: AutomationView): void {
    const f = formOf(current.definition);
    if (!f) {
      error = "The form cannot say this automation: change it in its file.";
      return;
    }
    enabled = current.enabled ?? false;
    name = current.name;
    named = true;
    on = f.on;
    timeKind = f.schedule.kind;
    if (f.schedule.kind === "every") every = { n: f.schedule.n, unit: f.schedule.unit };
    else at = { at: f.schedule.at, days: [...f.schedule.days] };
    stopProject = f.stopProject;
    what = f.what;
    app = f.app;
    call = f.call;
    description = f.description;
    const runs = f.agent && agents.find((a) => a.name === f.agent?.name && projectOf(a) === f.agent?.project);
    if (f.agent && runs) {
      agentId = formAgent = runs.id;
      const kinds = fieldsOf(runs.interface?.fields as Schema | undefined);
      values = Object.fromEntries(
        Object.entries(f.agent.fields).map(([k, v]) => [k, kinds.find((x) => x.key === k)?.kind === "json" ? JSON.stringify(v) : v]),
      );
      subject = f.agent.skill;
    } else if (f.agent) error = `Its agent ${f.agent.name} no longer runs unattended or was renamed: choose one.`;
  }

  // a new agent chosen: its own form
  let formAgent = "";
  $effect(() => {
    if (agentId === formAgent) return;
    formAgent = agentId;
    values = {};
    subject = "";
  });

  $effect(() => {
    if (named) return;
    const subjectName = what === "agent" ? (agent?.name ?? "") : app;
    name = suggestName(subjectName, schedule);
  });

  // the definition the form says, or why it cannot be one yet
  const built = $derived.by((): { definition: Automation } | { wrong: string } => {
    if (scheduleWrong) return { wrong: scheduleWrong };
    const when = schedule ? scheduleOf(schedule) : ("session.stopped" as const);
    const only = !schedule && stopProject ? { only: { project: [stopProject] } } : {};
    const base = { apiVersion: "handler.automation/v1" as const, ...(description.trim() ? { description: description.trim() } : {}), when, ...only };
    if (what === "app") {
      if (!app) return { wrong: "Choose an app." };
      if (!/^POST \/api\/[A-Za-z0-9/_.-]*$/.test(call)) return { wrong: "The route is POST /api/… (letters, digits, / _ . -)." };
      return { definition: { ...base, run: { app, call } } };
    }
    if (!agent) return { wrong: "Choose an agent." };
    if (!agent.name) return { wrong: "This agent has no name: an automation finds it by its name. Give it one in its settings." };
    let input: Record<string, unknown>;
    try {
      input = { fields: fieldValues(fields, values) };
    } catch (e) {
      return { wrong: (e as Error).message };
    }
    if (agent.interface?.subject === "skill") input.subject = { skill: subject };
    const project = projectOf(agent);
    return { definition: { ...base, run: { agent: agent.name, ...(project ? { project } : {}), input } } };
  });

  // handlerd says what it would do, as it is filled in
  $effect(() => {
    if (!("definition" in built)) {
      check = null;
      return;
    }
    const definition = $state.snapshot(built.definition) as Automation;
    const timer = setTimeout(() => {
      api.checkAutomation(definition).then(
        (c) => ((check = c), (checkError = null)),
        (e: Error) => ((check = null), (checkError = e.message)),
      );
    }, 300);
    return () => clearTimeout(timer);
  });

  const nameOk = $derived(/^[a-z0-9][a-z0-9-]{0,63}$/.test(name));
  const ready = $derived("definition" in built && nameOk && !!check && !checkError);

  async function save(): Promise<void> {
    if (!("definition" in built) || !editing) return;
    busy = true;
    error = null;
    try {
      await api.updateAutomation(editing, $state.snapshot(built.definition) as Automation);
      navigate({ view: "automation", name: editing });
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  async function create(enable: boolean): Promise<void> {
    if (!("definition" in built)) return;
    busy = true;
    error = null;
    try {
      const made = await api.createAutomation(name, { definition: $state.snapshot(built.definition) as Automation, enable });
      navigate({ view: "automation", name: made.name });
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  function preset(form: ScheduleForm): void {
    timeKind = form.kind;
    if (form.kind === "every") every = { n: form.n, unit: form.unit };
    else at = { at: form.at, days: [...form.days] };
  }

  function isPreset(form: ScheduleForm): boolean {
    return !!schedule && JSON.stringify(scheduleOf(form)) === JSON.stringify(scheduleOf(schedule));
  }

  function toggleDay(d: Day): void {
    at.days = at.days.includes(d) ? at.days.filter((x) => x !== d) : DAYS.filter((x) => x === d || at.days.includes(x));
  }

  const DAY_LABEL: Record<Day, string> = { mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun" };
  const CHIP = "cursor-pointer rounded-md border px-2.5 py-1 text-sm transition-colors";
  const CHIP_ON = "border-primary bg-primary text-primary-foreground";
  const CHIP_OFF = "bg-card text-muted-foreground hover:text-foreground";
</script>

<PageHeader
  titled
  title={editing ? `Change ${editing}` : "New automation"}
  parent={editing ? { label: editing, href: href({ view: "automation", name: editing }) } : { label: "Automations", href: href({ view: "automations" }) }}
/>
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-3xl space-y-10 px-8 py-10">
    <PageTitle
      title={editing ? `Change ${editing}` : "New automation"}
      description={editing
        ? enabled
          ? "It is on: your change applies at its next run."
          : "It is off: nothing runs before you turn it on."
        : "When this happens, run that. Nothing runs before you turn it on."}
    />
    {#if error}<p class="text-sm text-danger" data-testid="new-automation-error">{error}</p>{/if}

    <section class="space-y-4" aria-labelledby="group-when">
      <h2 id="group-when" class={GROUP}>When</h2>
      <div class="inline-flex rounded-lg border bg-muted p-0.5" role="radiogroup" aria-label="when">
        {#each [{ v: "time", label: "At a time" }, { v: "stop", label: "When a session stops" }] as o (o.v)}
          <button type="button" role="radio" aria-checked={on === o.v} class="{SEGMENT} {on === o.v ? SEGMENT_ON : SEGMENT_OFF}" onclick={() => (on = o.v as "time" | "stop")} data-testid={`when-${o.v}`}>
            {o.label}
          </button>
        {/each}
      </div>

      {#if on === "time"}
        <div class="flex flex-wrap gap-1.5" data-testid="schedule-presets">
          {#each SCHEDULE_PRESETS as p (p.label)}
            <Button type="button" size="sm" variant={isPreset(p.form) ? "secondary" : "outline"} onclick={() => preset(p.form)}>{p.label}</Button>
          {/each}
        </div>
        <div class="space-y-3 rounded-lg border bg-card p-4">
          <div class="inline-flex rounded-lg border bg-muted p-0.5" role="radiogroup" aria-label="schedule">
            {#each [{ v: "at", label: "At a time of day" }, { v: "every", label: "Every…" }] as o (o.v)}
              <button type="button" role="radio" aria-checked={timeKind === o.v} class="{SEGMENT} {timeKind === o.v ? SEGMENT_ON : SEGMENT_OFF}" onclick={() => (timeKind = o.v as "at" | "every")} data-testid={`schedule-${o.v}`}>
                {o.label}
              </button>
            {/each}
          </div>
          {#if timeKind === "every"}
            <div class="flex items-center gap-2">
              <Label for="every-n" class="font-normal">Every</Label>
              <Input id="every-n" type="number" min="1" class="h-9 w-24" bind:value={every.n} data-testid="schedule-every-n" />
              <NativeSelect.Root bind:value={every.unit} class="w-32" aria-label="unit" data-testid="schedule-every-unit">
                <NativeSelect.Option value="m">minutes</NativeSelect.Option>
                <NativeSelect.Option value="h">hours</NativeSelect.Option>
              </NativeSelect.Root>
            </div>
            <p class="text-xs text-muted-foreground">Counted from when you turn it on: at least every 5 minutes.</p>
          {:else}
            <div class="flex flex-wrap items-center gap-2">
              <Label for="at-time" class="font-normal">At</Label>
              <Input id="at-time" type="time" class="h-9 w-32" bind:value={at.at} data-testid="schedule-at" />
              <span class="text-sm text-muted-foreground">your local time, on</span>
            </div>
            <div class="flex flex-wrap items-center gap-1.5" role="group" aria-label="days" data-testid="schedule-days">
              {#each DAYS as d (d)}
                <button type="button" aria-pressed={at.days.includes(d)} class="{CHIP} {at.days.includes(d) ? CHIP_ON : CHIP_OFF}" onclick={() => toggleDay(d)}>{DAY_LABEL[d]}</button>
              {/each}
              <Button type="button" variant="ghost" size="sm" onclick={() => (at.days = [...WEEKDAYS])}>Weekdays</Button>
              <Button type="button" variant="ghost" size="sm" onclick={() => (at.days = [...DAYS])}>Every day</Button>
            </div>
          {/if}
          {#if scheduleWrong}
            <p class="text-xs text-danger">{scheduleWrong}</p>
          {:else if schedule}
            {#if check?.nextAt && !enabled}
              <p class="text-sm" data-testid="new-automation-first">First run <When at={check.nextAt} /> ({exactTime(check.nextAt)}), once you turn it on.</p>
            {/if}
            <p class="text-sm" data-testid="new-automation-how-often">
              {howOften(schedule).replace(/^./, (c) => c.toUpperCase())}{what === "agent" ? ": each is a run of the agent on its model, which costs tokens on an API key." : "."}
            </p>
          {/if}
          <p class="text-xs text-muted-foreground">It runs while Handler runs: after your computer was off or asleep, only the latest missed time runs.</p>
        </div>
      {:else}
        <div class="space-y-1.5">
          <Label for="stop-project">Of</Label>
          <NativeSelect.Root id="stop-project" bind:value={stopProject} class="w-72" data-testid="stop-project">
            <NativeSelect.Option value="">any session</NativeSelect.Option>
            {#each projectList as p (p.id)}<NativeSelect.Option value={p.name}>a session of {p.name}</NativeSelect.Option>{/each}
          </NativeSelect.Root>
          <p class="text-xs text-muted-foreground">Only sessions that stop after you turn it on.</p>
        </div>
      {/if}
    </section>

    <section class="space-y-4 border-t pt-8" aria-labelledby="group-what">
      <h2 id="group-what" class={GROUP}>Run</h2>
      <div class="inline-flex rounded-lg border bg-muted p-0.5" role="radiogroup" aria-label="what runs">
        {#each [{ v: "agent", label: "One of your agents" }, { v: "app", label: "A route of one of your apps" }] as o (o.v)}
          <button type="button" role="radio" aria-checked={what === o.v} class="{SEGMENT} {what === o.v ? SEGMENT_ON : SEGMENT_OFF}" onclick={() => (what = o.v as "agent" | "app")} data-testid={`run-${o.v}`}>
            {o.label}
          </button>
        {/each}
      </div>

      {#if what === "agent"}
        {#if loaded && !agents.length}
          <p class="rounded-lg border bg-card px-4 py-6 text-center text-sm text-muted-foreground" data-testid="no-unattended-agent">
            None of your agents runs unattended yet. In an agent's settings, under <em>How it is started</em>, tick
            <em>Runs unattended</em>: it then has a form and a result, and an automation can run it.
          </p>
        {:else}
          <div class="space-y-1.5">
            <Label for="run-agent">Agent</Label>
            <NativeSelect.Root id="run-agent" bind:value={agentId} class="w-full" data-testid="new-automation-agent">
              {#each agents as a (a.id)}
                <NativeSelect.Option value={a.id} disabled={!a.name}>
                  {agentLabel(a)} · {projectOf(a) ?? "outside projects"}{a.name ? "" : " (no name: give it one first)"}
                </NativeSelect.Option>
              {/each}
            </NativeSelect.Root>
            <p class="text-xs text-muted-foreground">Only agents that run unattended (a form in, a result out) are listed. Its result comes to your inbox.</p>
          </div>
          {#if agent}
            <div class="space-y-4 rounded-lg border bg-card p-4" data-testid="new-automation-input">
              {#if fields.length || agent.interface?.subject === "skill"}
                <RunFields {agent} {fields} bind:values bind:subject />
              {:else}
                <p class="text-sm text-muted-foreground">Its form has no field: it runs with nothing to fill in.</p>
              {/if}
            </div>
            <p class="text-sm" data-testid="new-automation-model">
              Runs on <strong>{agent.models[0] ? accessLabel(agent.models[0]) : "no model"}</strong>, its default model (the first in
              its settings, the one new sessions start with too).
              <a class="text-link hover:underline" href={agent.projectId ? href({ view: "edit-agent", project: agent.projectId, id: agent.id }) : href({ view: "edit-ad-hoc", id: agent.id })}>Change it</a>
            </p>
          {/if}
        {/if}
      {:else if loaded && !apps.length}
        <p class="rounded-lg border bg-card px-4 py-6 text-center text-sm text-muted-foreground">No app yet: add one on the <a class="text-link hover:underline" href={href({ view: "apps" })}>Apps</a> page.</p>
      {:else}
        <div class="grid gap-4 sm:grid-cols-2">
          <div class="space-y-1.5">
            <Label for="run-app">App</Label>
            <NativeSelect.Root id="run-app" bind:value={app} class="w-full" data-testid="new-automation-app">
              {#each apps as a (a.name)}<NativeSelect.Option value={a.name}>{a.name}</NativeSelect.Option>{/each}
            </NativeSelect.Root>
          </div>
          <div class="space-y-1.5">
            <Label for="run-call">Route</Label>
            <Input id="run-call" class="font-mono" bind:value={call} data-testid="new-automation-call" />
          </div>
        </div>
        <p class="text-xs text-muted-foreground">Handler starts the app if needed and calls the route as you. What the app notifies comes to your inbox.</p>
      {/if}
      <p class="text-xs text-muted-foreground">
        A script of your own (in a sandbox without network, adding to a note): start from an example on the
        <a class="text-link hover:underline" href={href({ view: "automations" })}>Automations</a> page.
      </p>
    </section>

    <section class="space-y-4 border-t pt-8" aria-labelledby="group-name">
      <h2 id="group-name" class={GROUP}>Name</h2>
      <div class="grid gap-4 sm:grid-cols-2">
        <div class="space-y-1.5">
          <Label for="automation-name">Name</Label>
          <Input id="automation-name" bind:value={name} oninput={() => (named = true)} readonly={!!editing} class="font-mono" data-testid="new-automation-name" />
          {#if !nameOk}<p class="text-xs text-danger">Lowercase letters, digits and -, at most 64.</p>{/if}
        </div>
        <div class="space-y-1.5">
          <Label for="automation-description">Description (optional)</Label>
          <Input id="automation-description" bind:value={description} placeholder="e.g. Review the code every morning" />
        </div>
      </div>
      <p class="text-xs text-muted-foreground">
        {#if editing}
          Saved over <code>~/.config/handler-ai/automations/{name}/automation.toml</code>: what you wrote in it by hand (comments too) is replaced.
        {:else}
          Saved as <code>~/.config/handler-ai/automations/{name || "…"}/automation.toml</code>, a file you can read and edit.
        {/if}
      </p>
    </section>

    <section class="space-y-3 border-t pt-8" aria-labelledby="group-does" data-testid="new-automation-check">
      <h2 id="group-does" class={GROUP}>What it will do</h2>
      {#if "wrong" in built}
        <p class="text-sm text-muted-foreground">{built.wrong}</p>
      {:else if checkError}
        <p class="text-sm text-danger">{checkError}</p>
      {:else if check}
        <ul class="space-y-0.5 text-sm" data-testid="new-automation-permissions">
          {#each check.permissions ?? [] as line (line)}
            <li>{#each line.split("`") as part, i (i)}{#if i % 2}<code class="rounded bg-muted px-1 text-xs">{part}</code>{:else}{part}{/if}{/each}</li>
          {/each}
        </ul>
        {#if check.warnings?.length}
          <div class="flex gap-2 rounded-md border border-warn/40 bg-warn/5 p-3 text-sm" data-testid="new-automation-warnings">
            <ShieldAlert class="size-4 shrink-0 text-warn" />
            <div>{#each check.warnings as w (w)}<p>{w}</p>{/each}</div>
          </div>
        {/if}
        {#if check.problems?.length}
          <div class="rounded-md border border-danger/30 bg-danger/5 p-3 text-sm" data-testid="new-automation-problems">
            <p class="font-medium text-danger">It cannot run until these are fixed:</p>
            <ul class="mt-1 list-disc pl-5 text-danger">{#each check.problems as p (p)}<li>{p}</li>{/each}</ul>
          </div>
        {/if}
      {:else}
        <p class="text-sm text-muted-foreground">Checking…</p>
      {/if}
    </section>

    <div class="sticky bottom-0 -mx-1 flex flex-wrap items-center gap-2 border-t bg-background px-1 py-3">
      {#if editing}
        <Button disabled={busy || !ready} onclick={save} data-testid="automation-save">Save</Button>
        <Button variant="ghost" href={href({ view: "automation", name: editing })}>Cancel</Button>
        <p class="text-xs text-muted-foreground">
          {check?.problems?.length ? "With problems it does not run until they are fixed." : enabled ? "It stays on: it will do what is said above." : ""}
        </p>
      {:else}
        <Button disabled={busy || !ready || !!check?.problems?.length} onclick={() => create(true)} data-testid="new-automation-create-on">Create and turn on</Button>
        <Button variant="outline" disabled={busy || !ready} onclick={() => create(false)} data-testid="new-automation-create-off">Create, off</Button>
        <Button variant="ghost" href={href({ view: "automations" })}>Cancel</Button>
        <p class="text-xs text-muted-foreground">
          {check?.problems?.length ? "With problems it can only be created off." : "Turning it on is your approval of what it will do, above."}
        </p>
      {/if}
    </div>
  </div>
</div>
