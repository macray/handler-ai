<script lang="ts">
  // A project's settings, to create one or edit it, in groups: the project (its code folder, name
  // and description); a new project's first agent (its goal, what it runs as, a preset, and the
  // knowledge folder it was started from); what is for all its agents (caches, the skills it gives
  // them: listed, given on a skill's page). More agents, and what each may do or get (its addons),
  // are set on the agents themselves.
  import type { Project, SkillInfo } from "../lib/contracts.gen";
  import { chosen, noAccess, type ModelAccess } from "../lib/access";
  import { api, ApiError } from "../lib/api";
  import { agentBody, emptyAgent, emptyProject, PRESETS, projectBody, projects, projectSpec, type ProjectSpec } from "../lib/projects.svelte";
  import { folderName } from "../lib/agents";
  import { GROUP, SEGMENT, SEGMENT_OFF, SEGMENT_ON } from "../lib/form";
  import { href } from "../lib/router.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import * as NativeSelect from "$lib/components/ui/native-select";
  import { contexts } from "../lib/contexts.svelte";
  import ContextTag from "./ContextTag.svelte";
  import FolderPicker from "./FolderPicker.svelte";
  import ModelAccessPicker from "./ModelAccessPicker.svelte";

  let {
    project,
    initialAccess,
    initialKnowledge,
    onsaved,
    oncancel,
  }: {
    project?: Project; // edit it; none: a new one
    initialAccess?: ModelAccess; // what a new one's first agent runs as, e.g. the last one used
    initialKnowledge?: string; // a new one's first agent's knowledge folder (from the Knowledge page)
    onsaved: (project: Project) => void;
    oncancel: () => void;
  } = $props();

  // the props give the initial values only
  // svelte-ignore state_referenced_locally
  let spec = $state<ProjectSpec>(project ? projectSpec(project) : emptyProject(""));
  // svelte-ignore state_referenced_locally
  let firstAccess = $state<ModelAccess>(initialAccess ? { ...initialAccess } : noAccess()); // its first agent
  let firstPreset = $state("guarded"); // and how it is contained, copied from a preset
  let firstGoal = $state("Dev"); // and its name: what it is for (D.8)
  let risks = $state<string | null>(null); // what that preset widens, to confirm
  let busy = $state(false);
  let error = $state<string | null>(null);

  let skills = $state<SkillInfo[]>([]); // those it gives to all its agents (an existing project's)
  $effect(() => {
    const id = project?.id;
    if (!id) return;
    api.skills().then(
      (list) => (skills = list.filter((s) => s.projects?.includes(id))),
      () => (skills = []),
    );
  });

  // the folders of the other projects: one project per folder
  const used = $derived(Object.fromEntries(projects.list.filter((p) => p.id !== project?.id).map((p) => [p.folder, p.name])));
  // why it cannot be saved yet
  const blocker = $derived(
    !spec.folder
      ? "Choose its code folder."
      : used[spec.folder]
        ? `${used[spec.folder]} already uses this folder.`
        : !project && !firstGoal.trim()
          ? "Give its first agent a goal."
          : !project && !chosen(firstAccess)
            ? "Choose what its first agent runs as."
            : null,
  );

  const CACHES: { value: ProjectSpec["caches"]; label: string; hint: string }[] = [
    { value: "project", label: "This project only", hint: "Its own caches, used by its agents only; removed with it." },
    {
      value: "global",
      label: "Global",
      hint: "The caches used by every project that chooses them and by agents outside projects: less to download, but what one project's agent leaves there, another's may run.",
    },
    { value: "off", label: "Off", hint: "No caches: toolchains and dependencies are fetched again in every session." },
  ];

  // what the caches setting applies to: the toolbox's caches (Settings → Caches)
  let cacheTargets = $state<string[]>([]);
  api.caches().then(
    (i) => (cacheTargets = i.caches.map((c) => c.target)),
    () => {},
  );

  async function save(confirm = false): Promise<void> {
    busy = true;
    error = null;
    try {
      const body = projectBody(spec);
      const knowledge = initialKnowledge ? [initialKnowledge] : [];
      const first = { ...emptyAgent([firstAccess]), ...PRESETS.find((p) => p.id === firstPreset)?.sandbox, knowledge, name: firstGoal };
      const saved = project ? await api.updateProject(project.id, body) : await api.createProject({ ...body, agents: [agentBody(first, confirm)] });
      risks = null;
      onsaved(saved);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.title === "risks not confirmed") risks = e.detail ?? e.title;
      else error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  function submit(event: SubmitEvent): void {
    event.preventDefault();
    void save();
  }
  void contexts.load();
</script>

<form class="space-y-10" onsubmit={submit} data-testid="project-editor">
  <section class="space-y-4" aria-labelledby="group-project">
    <h2 id="group-project" class={GROUP}>The project</h2>
    <div class="space-y-2">
      <Label>Code folder</Label>
      <FolderPicker bind:value={spec.folder} {used} />
      <p class="text-xs text-muted-foreground">
        Mounted read-write at the same path in its agents' sandboxes. One project per folder, inside the work folders (Settings → Folders).
      </p>
      {#if used[spec.folder]}<p class="text-xs text-danger" data-testid="project-folder-used">{used[spec.folder]} already uses this folder.</p>{/if}
      {#if project && spec.folder !== project.folder}
        <p class="text-xs text-warn">Past conversations stay with {folderName(project.folder)}: they cannot be resumed after this change.</p>
      {/if}
    </div>
    <div class="grid gap-4 sm:grid-cols-2">
      <div class="space-y-2">
        <Label for="project-name">Name</Label>
        <Input id="project-name" bind:value={spec.name} placeholder={spec.folder ? folderName(spec.folder) : "the folder's name"} data-testid="project-name" />
      </div>
      <div class="space-y-2">
        <Label for="project-description">Description</Label>
        <Input id="project-description" bind:value={spec.description} placeholder="e.g. the shop's theme: Liquid, Tailwind" data-testid="project-description" />
      </div>
    </div>
    <div class="space-y-2">
      <Label for="project-context">Context</Label>
      <div class="flex items-center gap-2">
        <NativeSelect.Root id="project-context" class="w-56" value={spec.context ?? ""} onchange={(e) => (spec.context = e.currentTarget.value || null)} data-testid="project-context">
          <NativeSelect.Option value="">None: any account</NativeSelect.Option>
          {#each contexts.list as c (c.name)}<NativeSelect.Option value={c.name}>{c.name}</NativeSelect.Option>{/each}
        </NativeSelect.Root>
        {#if spec.context}<ContextTag name={spec.context} />{/if}
      </div>
      <p class="text-xs text-muted-foreground">
        {#if spec.context}Only the accounts and providers made for {spec.context} run its agents.{:else}Work, Personal, a client: then only the accounts and providers made for it run its agents.{/if}
        Contexts are made in <a class="text-link hover:underline" href={href({ view: "settings", section: "contexts" })}>Settings → Contexts</a>.
      </p>
    </div>
  </section>

  {#if !project}
    <section class="space-y-4 border-t pt-8" aria-labelledby="group-first">
      <h2 id="group-first" class={GROUP}>Its first agent</h2>
      <div class="space-y-2">
        <Label for="first-goal">Goal</Label>
        <Input id="first-goal" class="w-64" bind:value={firstGoal} placeholder="e.g. Dev" data-testid="first-agent-goal" />
        <p class="text-xs text-muted-foreground">Its name: what it is for. Add more agents (a reviewer, a contracts check…) on the project page.</p>
      </div>
      <div class="space-y-2">
        <Label>Runs as</Label>
        <ModelAccessPicker bind:value={firstAccess} context={spec.context} />
      </div>
      <div class="space-y-2">
        <Label>Safety preset</Label>
        <div class="inline-flex rounded-lg border bg-muted p-0.5" role="radiogroup" aria-label="preset">
          {#each PRESETS as preset (preset.id)}
            <button
              type="button"
              role="radio"
              aria-checked={firstPreset === preset.id}
              class="{SEGMENT} {firstPreset === preset.id ? SEGMENT_ON : SEGMENT_OFF}"
              onclick={() => (firstPreset = preset.id)}
              data-testid={`project-preset-${preset.id}`}
            >
              {preset.label}
            </button>
          {/each}
        </div>
        <p class="text-xs text-muted-foreground">
          {PRESETS.find((p) => p.id === firstPreset)?.hint}. To start with: change its permissions, network and sandbox on the agent after.
        </p>
      </div>
    </section>
  {/if}

  <section class="space-y-6 border-t pt-8" aria-labelledby="group-all">
    <h2 id="group-all" class={GROUP}>For all its agents</h2>
    <div class="space-y-2" data-testid="project-caches">
      <Label>Toolchain caches</Label>
      <div class="inline-flex rounded-lg border bg-muted p-0.5" role="radiogroup" aria-label="caches">
        {#each CACHES as c (c.value)}
          <button
            type="button"
            role="radio"
            aria-checked={spec.caches === c.value}
            class="{SEGMENT} {spec.caches === c.value ? SEGMENT_ON : SEGMENT_OFF}"
            onclick={() => (spec.caches = c.value)}
            data-testid={`caches-${c.value}`}
          >
            {c.label}
          </button>
        {/each}
      </div>
      <p class="text-xs text-muted-foreground">{CACHES.find((c) => c.value === spec.caches)?.hint}</p>
      {#if spec.caches !== "off" && cacheTargets.length}
        <p class="text-xs text-muted-foreground" data-testid="project-cache-list">
          Kept: <span class="font-mono">{cacheTargets.join(", ")}</span> ·
          <a class="underline underline-offset-2" href={href({ view: "settings", section: "caches" })}>Settings → Caches</a>
        </p>
      {/if}
    </div>

    {#if project}
      <div class="space-y-2" data-testid="project-skills">
        <Label>Skills</Label>
        {#if skills.length}
          <ul class="flex flex-wrap gap-2 text-sm">
            {#each skills as s (s.name)}
              <li><a class="rounded border px-2 py-0.5 font-mono text-xs hover:bg-muted" href={href({ view: "skill", name: s.name })}>{s.name}</a></li>
            {/each}
          </ul>
        {/if}
        <p class="text-xs text-muted-foreground">
          {skills.length ? "Given to all its agents." : "None."} A skill is given to a project's agents on its page, in
          <a class="text-link hover:underline" href={href({ view: "skills" })}>Skills</a>.
        </p>
      </div>
    {/if}
  </section>

  <div class="sticky bottom-0 -mx-1 flex flex-wrap items-center gap-2 border-t bg-background px-1 py-3">
    {#if risks}
      <div class="w-full space-y-2 rounded-md border border-warn/50 bg-warn/5 p-3 text-sm" data-testid="project-risks">
        <p>Its first agent gets more than a new agent gets by default: {risks}.</p>
        <div class="flex gap-2">
          <Button type="button" size="sm" variant="destructive" disabled={busy} onclick={() => save(true)} data-testid="project-confirm-risks">Create anyway</Button>
          <Button type="button" size="sm" variant="ghost" onclick={() => (risks = null)}>Back</Button>
        </div>
      </div>
    {/if}
    <Button type="submit" disabled={busy || !!blocker} data-testid="project-save">
      {project ? "Save" : "Create the project"}
    </Button>
    <Button type="button" variant="ghost" onclick={oncancel}>Cancel</Button>
    {#if blocker}<p class="text-xs text-muted-foreground" data-testid="project-save-blocker">{blocker}</p>{/if}
    {#if error}<p class="w-full text-sm text-danger">{error}</p>{/if}
  </div>
</form>
