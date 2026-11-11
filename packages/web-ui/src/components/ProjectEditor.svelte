<script lang="ts">
  // A project's settings, to create one or edit it (its page's Settings tab), as rows
  // (`SettingRow`). New project is one page and makes the project alone (its agents are added on
  // its page): its folder (those of the work folders changed last, with their git branch, one
  // already a project greyed; Another folder… opens the folder picker), then its name (the
  // folder's by default), description, area and caches; Create the project. An existing one's
  // also has what all its agents get (the skills it gives them: added from the library in a
  // dialog, each one added saying what handler's scan found in its files, as the skill's page
  // does; the tools it gives them, picked in a dialog); its changes are marked, counted on a bar
  // that saves or undoes them; Delete comes last. What each agent may do or get is set on it.
  import Plus from "@lucide/svelte/icons/plus";
  import Trash from "@lucide/svelte/icons/trash-2";
  import X from "@lucide/svelte/icons/x";
  import { untrack } from "svelte";
  import type { Project, SkillInfo } from "../lib/contracts.gen";
  import { api, toolboxChanges, type ToolboxChanges } from "../lib/api";
  import ToolboxConfirm from "./ToolboxConfirm.svelte";
  import { emptyProject, projectBody, projects, projectSpec, type ProjectSpec } from "../lib/projects.svelte";
  import { ago, folderName } from "../lib/agents";
  import { SEGMENT, SEGMENT_OFF, SEGMENT_ON } from "../lib/form";
  import { href } from "../lib/router.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { areas } from "../lib/areas.svelte";
  import AddonPicker from "./AddonPicker.svelte";
  import AreaTag from "./AreaTag.svelte";
  import FolderPicker from "./FolderPicker.svelte";
  import GitBranch from "@lucide/svelte/icons/git-branch";
  import Search from "@lucide/svelte/icons/search";
  import type { DirectoryEntry } from "../lib/contracts.gen";
  import Dialog from "./Dialog.svelte";
  import PickRow from "./PickRow.svelte";
  import SettingRow from "./SettingRow.svelte";
  import { scanFindings } from "../lib/skills";

  let {
    project,
    initialFolder,
    onsaved,
    oncancel,
    ondelete,
  }: {
    project?: Project; // edit it; none: a new one
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
  let toolbox = $state<(ToolboxChanges & { risks: boolean }) | null>(null); // what it adds to the toolbox
  let busy = $state(false);
  let error = $state<string | null>(null);

  let library = $state<SkillInfo[]>([]); // the skills it may give to all its agents
  api.skills().then(
    (list) => (library = list),
    () => {},
  );
  let addingSkills = $state(false);
  let addingAddons = $state(false);
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
        : null,
  );

  // a new one's folder: those changed last first (the first free one chosen), or another one
  let recent = $state<DirectoryEntry[]>([]);
  // svelte-ignore state_referenced_locally
  let another = $state(!!initialFolder);
  // svelte-ignore state_referenced_locally
  if (!project) {
    api.recentDirectories().then(
      (l) => {
        recent = l.entries;
        if (!spec.folder && !another) spec.folder = recent.find((e) => !used[e.path])?.path ?? "";
        if (!recent.length) another = true;
      },
      () => (another = true),
    );
  }
  const changedWhen = (at: string | null | undefined): string => {
    if (!at) return "";
    const days = Math.floor((Date.now() - Date.parse(at)) / 86_400_000);
    return days < 1 ? "changed today" : days < 2 ? "changed yesterday" : `changed ${ago(at)}`;
  };

  const CACHES: { value: ProjectSpec["caches"]; label: string; hint: string }[] = [
    { value: "project", label: "Its own", hint: "Its own caches, used by its agents only; removed with it." },
    {
      value: "global",
      label: "Shared with your other projects",
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

  async function save(confirm = false, adds: string[] = []): Promise<void> {
    busy = true;
    error = null;
    try {
      const body = { ...projectBody(spec), toolboxAdds: adds };
      const saved = project ? await api.updateProject(project.id, body) : await api.createProject(body);
      toolbox = null;
      onsaved(saved);
    } catch (e) {
      const changes = toolboxChanges(e);
      if (changes) toolbox = { ...changes, risks: confirm };
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
    {#if project}<h2 id="group-project" class={GROUP}>The project</h2>{/if}
    <div class={CARD}>
      <SettingRow label="Folder" hint="Its agents work in it, read-write, at the same path." for="project-folder">
        {#if !project}
          <div class="divide-y overflow-hidden rounded-[10px] border bg-card" role="radiogroup" aria-label="folder" data-testid="project-folders">
            {#each recent as e (e.path)}
              {@const taken = !!used[e.path]}
              <button
                type="button"
                role="radio"
                aria-checked={!another && spec.folder === e.path}
                disabled={taken}
                class="flex w-full cursor-pointer items-center gap-3 px-3.5 py-2.5 text-left text-sm hover:bg-muted/60 disabled:cursor-default disabled:opacity-50 disabled:hover:bg-transparent {!another && spec.folder === e.path ? 'bg-accent-soft/40' : ''}"
                onclick={() => ((spec.folder = e.path), (another = false))}
                data-testid="project-folder-recent"
              >
                <span class="radio" class:on={!another && spec.folder === e.path}></span>
                <span class="path min-w-0 flex-1 truncate font-mono text-xs" title={e.path}><bdi>{e.path}</bdi></span>
                {#if e.branch}<span class="inline-flex items-center gap-1 rounded-md border px-1.5 py-px text-xs text-muted-foreground"><GitBranch class="size-3" />{e.branch}</span>{/if}
                <span class="w-28 shrink-0 text-right text-xs text-muted-foreground">{taken ? "already a project" : changedWhen(e.changedAt)}</span>
              </button>
            {/each}
            <button type="button" class="flex w-full cursor-pointer items-center gap-3 px-3.5 py-2.5 text-left text-sm text-muted-foreground hover:bg-muted/60" onclick={() => (another = true)} data-testid="project-folder-other">
              <Search class="size-4" />Another folder…
            </button>
          </div>
        {/if}
        {#if project || another}
          <div class="rounded-lg {mark('folder')}"><FolderPicker id="project-folder" bind:value={spec.folder} {used} /></div>
        {/if}
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
        hint={spec.area ? `Its agents use ${spec.area}'s accounts and keys only.` : "Work, Personal, a client: its agents then use only the accounts and keys made for it."}
      >
        <div class="inline-flex flex-wrap self-start rounded-lg border bg-muted p-0.5 {mark('area')}" role="radiogroup" aria-label="area" data-testid="project-area">
          {#each [null, ...areas.list.map((c) => c.name)] as a (a ?? "")}
            <button
              type="button"
              role="radio"
              aria-checked={spec.area === a}
              class="{SEGMENT} inline-flex items-center gap-1.5 {spec.area === a ? SEGMENT_ON : SEGMENT_OFF}"
              onclick={() => (spec.area = a)}
              data-testid="project-area-{a ?? 'none'}"
            >
              {#if a}<AreaTag name={a} />{:else}None{/if}
            </button>
          {/each}
        </div>
        <p class="text-xs text-muted-foreground">
          Areas are made in <a class="text-link hover:underline" href={href({ view: "settings", section: "areas" })}>Settings → Areas</a>.
        </p>
      </SettingRow>
      <SettingRow label="Toolchain caches" hint="npm, pip, cargo… kept between sessions." data-testid="project-caches">
        <div class="inline-flex self-start rounded-lg border bg-muted p-0.5 {mark('caches')}" role="radiogroup" aria-label="caches">
          {#each CACHES as c (c.value)}
            <button
              type="button"
              role="radio"
              aria-checked={spec.caches === c.value}
              class="{SEGMENT} {spec.caches === c.value ? SEGMENT_ON : SEGMENT_OFF} {c.value === 'global' ? 'text-warn hover:text-warn' : ''}"
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
    </div>
  </section>

  {#if project}
  <section class="space-y-3" aria-labelledby="group-all">
    <h2 id="group-all" class={GROUP}>What all its agents get</h2>
    <div class={CARD}>
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

      <SettingRow label="Tools" hint="Programs and their skills: all its agents get them." data-testid="project-addons">
        <div class="flex flex-wrap items-center gap-1.5 rounded-lg text-sm {mark('addons')}">
          {#each spec.addons as u (u.addon)}
            {@const name = u.binding ? `${u.addon}: ${u.binding}` : u.addon}
            <span class="inline-flex h-7 items-center rounded-md border bg-background font-mono text-xs" data-testid="project-addon">
              <span class="py-0.5 pr-1 pl-2">{name}</span>
              <button type="button" class="grid h-full cursor-pointer place-items-center rounded-r-md px-1.5 text-muted-foreground hover:bg-muted hover:text-foreground" onclick={() => (spec.addons = spec.addons.filter((x) => x.addon !== u.addon))} aria-label="Take {name} back" title="Its agents no longer get it" data-testid="project-addon-remove"><X class="size-3" /></button>
            </span>
          {/each}
          <Button type="button" variant="ghost" size="sm" onclick={() => (addingAddons = true)} data-testid="project-addon-add"><Plus />Add a tool</Button>
        </div>
      </SettingRow>
    </div>
  </section>
  {/if}

  <Dialog bind:open={addingAddons} title="Tools for {spec.name.trim() || (spec.folder ? folderName(spec.folder) : 'the project')}" description="All its agents get the tools checked; an agent that picked one itself gets it from the project instead. Tools are installed and connected in Library → Tools." testid="project-addon-dialog">
    <AddonPicker projectId={project?.id} bind:value={spec.addons} hint="" />
    <div class="mt-4 flex justify-end">
      <Button type="button" onclick={() => (addingAddons = false)} data-testid="project-addon-done">Done</Button>
    </div>
  </Dialog>

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
          {project.agents.length === 0 ? "Its sessions go." : project.agents.length === 1 ? "Its agent and its sessions go." : `Its ${project.agents.length} agents and their sessions go.`} The folder stays as it is.
        </p>
      </div>
      <Button type="button" variant="outline" size="sm" class="text-destructive hover:text-destructive" onclick={ondelete} data-testid="project-delete"><Trash />Delete…</Button>
    </div>
  {/if}

  {#if project}
    {#if toolbox}
      {@const t = toolbox}
      <div class="sticky bottom-20 z-10 mx-auto w-fit max-w-full rounded-xl bg-popover shadow-lift">
        <ToolboxConfirm changes={t} {busy} onconfirm={() => save(t.risks, t.adds)} onback={() => (toolbox = null)} />
      </div>
    {/if}
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
      {#if toolbox}
        {@const t = toolbox}
        <ToolboxConfirm changes={t} {busy} action="Add and create" onconfirm={() => save(t.risks, t.adds)} onback={() => (toolbox = null)} />
      {/if}
      <Button type="submit" disabled={busy || !!blocker} data-testid="project-save">Create the project</Button>
      <Button type="button" variant="ghost" onclick={oncancel}>Cancel</Button>
      {#if blocker}<p class="text-xs text-muted-foreground" data-testid="project-save-blocker">{blocker}</p>{/if}
      {#if error}<p class="w-full text-sm text-danger">{error}</p>{/if}
    </div>
  {/if}
</form>

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
  /* a long path cut at its start: its folder's name stays */
  .path {
    direction: rtl;
    text-align: left;
  }
</style>
