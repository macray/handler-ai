<script lang="ts">
  // A project's settings, to create one or edit it, as rows (`SettingRow`) in groups: the project
  // (its code folder, name, description and area); a new project's first agent (its goal, what it
  // runs as, a preset, and the knowledge folder it was started from); what is for all its agents
  // (caches, the skills it gives them: added from the library in a dialog, each one added saying
  // what handler's scan found in its files, as the skill's page does). An existing project's
  // changes are marked, counted on a bar that saves or undoes them; Delete comes last. More agents,
  // and what each may do or get (its addons), are set on the agents themselves.
  import Plus from "@lucide/svelte/icons/plus";
  import Trash from "@lucide/svelte/icons/trash-2";
  import X from "@lucide/svelte/icons/x";
  import { untrack } from "svelte";
  import type { Project, SkillInfo } from "../lib/contracts.gen";
  import { chosen, noAccess, type ModelAccess } from "../lib/access";
  import { api, ApiError } from "../lib/api";
  import { agentBody, emptyAgent, emptyProject, PRESETS, projectBody, projects, projectSpec, type ProjectSpec } from "../lib/projects.svelte";
  import { folderName } from "../lib/agents";
  import { SEGMENT, SEGMENT_OFF, SEGMENT_ON } from "../lib/form";
  import { href } from "../lib/router.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import * as NativeSelect from "$lib/components/ui/native-select";
  import { areas } from "../lib/areas.svelte";
  import AreaTag from "./AreaTag.svelte";
  import FolderPicker from "./FolderPicker.svelte";
  import ModelAccessPicker from "./ModelAccessPicker.svelte";
  import Dialog from "./Dialog.svelte";
  import PickRow from "./PickRow.svelte";
  import SettingRow from "./SettingRow.svelte";
  import { scanFindings } from "../lib/skills";

  let {
    project,
    initialAccess,
    initialKnowledge,
    initialFolder,
    onsaved,
    oncancel,
    ondelete,
  }: {
    project?: Project; // edit it; none: a new one
    initialAccess?: ModelAccess; // what a new one's first agent runs as, e.g. the last one used
    initialKnowledge?: string; // a new one's first agent's knowledge folder (from the Knowledge page)
    initialFolder?: string; // a new one's folder (an app's data, to make it a project: H.2)
    onsaved: (project: Project) => void;
    oncancel: () => void; // a new one's Cancel
    ondelete?: () => void; // an existing one's Delete
  } = $props();

  // the props give the initial values only
  // svelte-ignore state_referenced_locally
  // svelte-ignore state_referenced_locally
  const initial: ProjectSpec = project ? projectSpec(project) : emptyProject(initialFolder ?? "");
  let spec = $state<ProjectSpec>({ ...initial });
  // an existing project's settings changed since it was loaded, marked on their control
  const changed = $derived((Object.keys(initial) as (keyof ProjectSpec)[]).filter((k) => JSON.stringify(spec[k]) !== JSON.stringify(initial[k])));
  const CHANGED = "ring-[1.5px] ring-primary";
  const GROUP = "text-base font-semibold";
  const CARD = "divide-y rounded-[10px] border bg-card shadow-panel";
  const mark = (key: keyof ProjectSpec): string => (project && changed.includes(key) ? CHANGED : "");
  // svelte-ignore state_referenced_locally
  let firstAccess = $state<ModelAccess>(initialAccess ? { ...initialAccess } : noAccess()); // its first agent
  let firstPreset = $state("guarded"); // and how it is contained, copied from a preset
  let firstGoal = $state("Dev"); // and its name: what it is for (D.8)
  let risks = $state<string | null>(null); // what that preset widens, to confirm
  let busy = $state(false);
  let error = $state<string | null>(null);

  let library = $state<SkillInfo[]>([]); // the skills it may give to all its agents
  api.skills().then(
    (list) => (library = list),
    () => {},
  );
  let addingSkills = $state(false);
  // what handler's scan found in the skills it is to give and did not (their own page says it in full)
  let findings = $state<Record<string, string[]>>({});
  $effect(() => {
    for (const name of spec.skills) {
      if (initial.skills.includes(name) || name in untrack(() => findings)) continue;
      findings[name] = [];
      api.skill(name).then(
        (s) => (findings[name] = s.scan ? scanFindings(s.scan) : []),
        () => {},
      );
    }
  });
  const added = $derived(spec.skills.filter((n) => !initial.skills.includes(n) && findings[n]?.length));
  // the agents of this project that picked it themselves: it moves to the project
  const pickedHere = (s: SkillInfo): string[] =>
    project ? (s.usedBy ?? []).filter((u) => u.startsWith(`agents/${project.name}/`)).map((u) => u.split("/").at(-1) ?? "") : [];

  function giveSkill(name: string, give: boolean): void {
    spec.skills = give ? [...spec.skills, name].sort() : spec.skills.filter((n) => n !== name);
  }

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
      const first = { ...emptyAgent(firstAccess), ...PRESETS.find((p) => p.id === firstPreset)?.sandbox, knowledge, name: firstGoal };
      const saved = project ? await api.updateProject(project.id, body) : await api.createProject({ ...body, agents: [agentBody(first, {}, confirm)] });
      risks = null;
      onsaved(saved);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.title === "risks not confirmed") risks = e.detail ?? e.title;
      else error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  function undo(): void {
    spec = { ...initial };
    error = null;
  }

  function submit(event: SubmitEvent): void {
    event.preventDefault();
    void save();
  }
  void areas.load();
</script>

<form class="space-y-10" onsubmit={submit} data-testid="project-editor">
  <section class="space-y-3" aria-labelledby="group-project">
    <h2 id="group-project" class={GROUP}>The project</h2>
    <div class={CARD}>
      <SettingRow label="Code folder" hint="Its agents see it, read-write, at the same path." for="project-folder">
        <div class="rounded-lg {mark('folder')}"><FolderPicker id="project-folder" bind:value={spec.folder} {used} /></div>
        <p class="text-xs text-muted-foreground">One project per folder, inside the work folders (Settings → Folders).</p>
        {#if used[spec.folder]}<p class="text-xs text-danger" data-testid="project-folder-used">{used[spec.folder]} already uses this folder.</p>{/if}
        {#if project && spec.folder !== project.folder}
          <p class="text-xs text-warn">Past conversations stay with {folderName(project.folder)}: they cannot be resumed after this change.</p>
        {/if}
      </SettingRow>
      <SettingRow label="Name" for="project-name">
        <Input id="project-name" class={mark("name")} bind:value={spec.name} placeholder={spec.folder ? folderName(spec.folder) : "the folder's name"} data-testid="project-name" />
      </SettingRow>
      <SettingRow label="Description" hint="Shown under its name." for="project-description">
        <Input id="project-description" class={mark("description")} bind:value={spec.description} placeholder="e.g. the shop's theme: Liquid, Tailwind" data-testid="project-description" />
      </SettingRow>
      <SettingRow
        label="Area"
        hint={spec.area ? `Only the accounts and providers made for ${spec.area} run its agents.` : "Work, Personal, a client: then only the accounts and providers made for it run its agents."}
        for="project-area"
      >
        <div class="flex items-center gap-2">
          <NativeSelect.Root id="project-area" class="w-56 {mark('area')}" value={spec.area ?? ""} onchange={(e) => (spec.area = e.currentTarget.value || null)} data-testid="project-area">
            <NativeSelect.Option value="">None: any account</NativeSelect.Option>
            {#each areas.list as c (c.name)}<NativeSelect.Option value={c.name}>{c.name}</NativeSelect.Option>{/each}
          </NativeSelect.Root>
          {#if spec.area}<AreaTag name={spec.area} />{/if}
        </div>
        <p class="text-xs text-muted-foreground">
          Areas are made in <a class="text-link hover:underline" href={href({ view: "settings", section: "areas" })}>Settings → Areas</a>.
        </p>
      </SettingRow>
    </div>
  </section>

  {#if !project}
    <section class="space-y-3" aria-labelledby="group-first">
      <h2 id="group-first" class={GROUP}>Its first agent</h2>
      <div class={CARD}>
        <SettingRow label="Goal" hint="Its name: what it is for. Add more agents (a reviewer, a contracts check…) on the project page." for="first-goal">
          <Input id="first-goal" class="w-64" bind:value={firstGoal} placeholder="e.g. Dev" data-testid="first-agent-goal" />
        </SettingRow>
        <SettingRow label="Runs as">
          <ModelAccessPicker bind:value={firstAccess} area={spec.area} />
        </SettingRow>
        <SettingRow label="Safety preset" hint="To start with: change its permissions, network and sandbox on the agent after.">
          <div class="inline-flex self-start rounded-lg border bg-muted p-0.5" role="radiogroup" aria-label="preset">
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
          <p class="text-xs text-muted-foreground">{PRESETS.find((p) => p.id === firstPreset)?.hint}.</p>
        </SettingRow>
      </div>
    </section>
  {/if}

  <section class="space-y-3" aria-labelledby="group-all">
    <h2 id="group-all" class={GROUP}>For all its agents</h2>
    <div class={CARD}>
      <SettingRow label="Toolchain caches" hint="npm, pip, cargo… kept between sessions." data-testid="project-caches">
        <div class="inline-flex self-start rounded-lg border bg-muted p-0.5 {mark('caches')}" role="radiogroup" aria-label="caches">
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
            <a class="text-link hover:underline" href={href({ view: "settings", section: "caches" })}>Settings → Caches</a>
          </p>
        {/if}
      </SettingRow>

      <SettingRow label="Skills" hint="From your library: all its agents get them." data-testid="project-skills">
        <div class="flex flex-wrap items-center gap-1.5 rounded-lg text-sm {mark('skills')}">
          {#each spec.skills as name (name)}
            <span class="inline-flex h-7 items-center rounded-md border bg-background font-mono text-xs" data-testid="project-skill">
              <a class="py-0.5 pr-1 pl-2 text-foreground no-underline hover:underline" href={href({ view: "skill", name })} title="Its page: what it says, who gets it">{name}</a>
              <button type="button" class="grid h-full cursor-pointer place-items-center rounded-r-md px-1.5 text-muted-foreground hover:bg-muted hover:text-foreground" onclick={() => giveSkill(name, false)} aria-label="Take {name} back" title="Its agents no longer get it" data-testid="project-skill-remove"><X class="size-3" /></button>
            </span>
          {/each}
          <Button type="button" variant="ghost" size="sm" onclick={() => (addingSkills = true)} data-testid="project-skill-add"><Plus />Add skill</Button>
        </div>
        {#each added as name (name)}
          <p class="text-xs text-warn" data-testid="project-skill-findings">
            {name}: Handler found {findings[name]?.join(", ")}. These are instructions your agents will follow:
            <a class="text-link hover:underline" href={href({ view: "skill", name })}>read it</a> before saving.
          </p>
        {/each}
      </SettingRow>
    </div>
  </section>

  <Dialog bind:open={addingSkills} title="Skills for {spec.name.trim() || (spec.folder ? folderName(spec.folder) : 'the project')}" description="All its agents get the skills checked. The library's skills are made and imported in Skills." testid="project-skill-dialog">
    {#if library.length}
      <div class="-mx-1 max-h-[60vh] divide-y overflow-y-auto rounded-lg border">
        {#each library as s (s.name)}
          {@const picked = pickedHere(s)}
          <PickRow
            name={s.name}
            description={s.error ?? s.description ?? ""}
            note={picked.length ? `${picked.join(", ")} picked it` : ""}
            checked={spec.skills.includes(s.name)}
            disabled={!!s.error && !spec.skills.includes(s.name)}
            onchange={(c) => giveSkill(s.name, c)}
            testid={`project-skill-pick-${s.name}`}
          />
        {/each}
      </div>
    {:else}
      <p class="rounded-[10px] border border-dashed px-4 py-6 text-center text-muted-foreground">
        Your library has no skill yet: write or import one in <a class="text-link hover:underline" href={href({ view: "skills" })}>Skills</a>.
      </p>
    {/if}
    <div class="mt-4 flex justify-end">
      <Button type="button" onclick={() => (addingSkills = false)} data-testid="project-skill-done">Done</Button>
    </div>
  </Dialog>

  {#if project && ondelete}
    <div class="flex items-center gap-4 rounded-[10px] border px-4 py-3.5">
      <div class="flex-1">
        <p class="text-sm font-medium">Delete the project</p>
        <p class="text-xs text-muted-foreground">
          {project.agents.length === 1 ? "Its agent and its sessions go" : `Its ${project.agents.length} agents and their sessions go`}; the folder is not touched.
        </p>
      </div>
      <Button type="button" variant="outline" size="sm" class="text-destructive hover:text-destructive" onclick={ondelete} data-testid="project-delete"><Trash />Delete…</Button>
    </div>
  {/if}

  {#if project}
    {#if changed.length || error}
      <div class="sticky bottom-5 z-10 mx-auto flex w-fit max-w-full flex-wrap items-center gap-2 rounded-xl border bg-popover py-2 pr-2 pl-4 text-sm shadow-lift" data-testid="project-savebar">
        {#if error}<span class="text-danger">{error}</span>
        {:else if blocker}<span class="text-muted-foreground" data-testid="project-save-blocker">{blocker}</span>
        {:else}<span class="text-muted-foreground">{changed.length === 1 ? "1 change" : `${changed.length} changes`}</span>{/if}
        <Button type="button" variant="ghost" size="sm" onclick={undo} data-testid="project-undo">Undo</Button>
        <Button type="submit" size="sm" disabled={busy || !!blocker || !changed.length} data-testid="project-save">Save</Button>
      </div>
    {/if}
  {:else}
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
      <Button type="submit" disabled={busy || !!blocker} data-testid="project-save">Create the project</Button>
      <Button type="button" variant="ghost" onclick={oncancel}>Cancel</Button>
      {#if blocker}<p class="text-xs text-muted-foreground" data-testid="project-save-blocker">{blocker}</p>{/if}
      {#if error}<p class="w-full text-sm text-danger">{error}</p>{/if}
    </div>
  {/if}
</form>
