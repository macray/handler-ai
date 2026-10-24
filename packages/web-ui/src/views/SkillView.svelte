<script lang="ts">
  // One skill of the library (D.17), its own page: who gets it (the projects that give it to all
  // their agents, changed on its own: not a field of its SKILL.md; the agents that picked it), its
  // SKILL.md as a form (name, when to use
  // it, its instructions, its other frontmatter fields as written; lib/skillmd.ts), and
  // its other files (scripts, references, assets): opened one at a time, written as text or
  // uploaded, executable or not, deleted. A new skill is created from its SKILL.md first. The
  // files on disk are the truth: whatever is opened is read again from handlerd. Unsaved changes are
  // marked, and leaving with some asks first (router `leaving`); saving says who it changes the
  // skill for, and "Save as a new skill" keeps the change to a copy (with its other files). Below: what handler found in its
  // files, its reviews and "Edit with an agent" (SkillReview, D.18). Just imported (already in the
  // library): a panel says so first, with the next steps, checking it and choosing who gets it.
  import UsesPanel from "../components/UsesPanel.svelte";
  import CircleCheck from "@lucide/svelte/icons/circle-check";
  import Download from "@lucide/svelte/icons/download";
  import Trash from "@lucide/svelte/icons/trash-2";
  import Plus from "@lucide/svelte/icons/plus";
  import Upload from "@lucide/svelte/icons/upload";
  import X from "@lucide/svelte/icons/x";
  import { untrack } from "svelte";
  import { Button } from "$lib/components/ui/button";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import { Textarea } from "$lib/components/ui/textarea";
  import * as NativeSelect from "$lib/components/ui/native-select";
  import PageHeader from "../components/PageHeader.svelte";
  import PageTitle from "../components/PageTitle.svelte";
  import PickRow from "../components/PickRow.svelte";
  import SkillReview from "../components/SkillReview.svelte";
  import { api } from "../lib/api";
  import type { SkillInfo } from "../lib/contracts.gen";
  import { projects } from "../lib/projects.svelte";
  import { scanFindings, who } from "../lib/skills";
  import { href, leaving, navigate, type Imported } from "../lib/router.svelte";
  import { NEW_SKILL, readSkill, writeSkill, type SkillDoc } from "../lib/skillmd";

  let { name, imported }: { name: string | null; imported?: Imported } = $props(); // name null: a new skill

  const SKILL_FILE = "SKILL.md";
  const FOLDERS = ["scripts", "references", "assets"];
  const list = href({ view: "skills" });

  // SKILL.md, as a form and as last read (to tell what changed)
  let skill = $state<SkillInfo | null>(null);
  let doc = $state<SkillDoc>({ ...NEW_SKILL });
  let read = $state(writeSkill(NEW_SKILL));
  // the projects that give it to all their agents: a new skill's choice, or the one being made
  // for a skill (`placing`)
  let givers = $state<string[]>([]);
  let placing = $state(false);
  // another file open (text: null when binary: replaced by an upload)
  type Open = { path: string; text: string | null; was: string | null; size: number; executable: boolean; isNew: boolean };
  let file = $state<Open | null>(null);
  let adding = $state(false); // the field for a new file's path shown
  let newPath = $state("");
  let uploadInto = $state("scripts");
  let uploads = $state<HTMLInputElement | null>(null);
  let busy = $state(false);
  let error = $state<string | null>(null);

  const skillChanged = $derived(writeSkill(doc) !== read);
  const fileChanged = $derived(file !== null && (file.isNew || file.text !== file.was));
  const users = $derived(skill ? who(skill, projects.list) : ""); // whom a change of it reaches
  const folders = $derived([...new Set([...FOLDERS, ...(skill?.files ?? []).map((f) => f.path.split("/").slice(0, -1).join("/")).filter(Boolean)])]);

  $effect(() => {
    leaving.unsaved = skillChanged || fileChanged;
  });
  $effect(() => {
    const warn = (e: BeforeUnloadEvent) => {
      if (leaving.unsaved) e.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => {
      window.removeEventListener("beforeunload", warn);
      leaving.unsaved = false;
    };
  });

  async function act(action: () => Promise<unknown>): Promise<boolean> {
    busy = true;
    error = null;
    try {
      await action();
      return true;
    } catch (e) {
      error = (e as Error).message;
      return false;
    } finally {
      busy = false;
    }
  }

  async function load(): Promise<void> {
    if (!projects.loaded) await projects.refresh();
    if (name === null) return;
    const before = writeSkill(doc);
    skill = await api.skill(name);
    if (writeSkill(doc) !== before) return; // typed in while it was read: the edits stay
    doc = readSkill(skill.content ?? "");
    read = writeSkill(doc);
  }

  /** Open a file (null: SKILL.md), read again from handlerd; asks before dropping unsaved edits. */
  async function select(path: string | null): Promise<void> {
    if (fileChanged && !confirm(`Drop your changes to ${file?.path}?`)) return;
    adding = false;
    if (path === null || !name) {
      file = null;
      if (!skillChanged) await act(load); // its unsaved edits stay
      return;
    }
    await act(async () => {
      const f = await api.skillFile(name ?? "", path);
      file = { path, text: f.text ?? null, was: f.text ?? null, size: f.size, executable: f.executable ?? false, isNew: false };
    });
  }

  /** The projects that give it to all their agents, now `givers`; its SKILL.md as it is on disk. */
  async function place(): Promise<void> {
    if (!skill || !name) return;
    const target = [...givers];
    if ([...target].sort().join() === [...(skill.projects ?? [])].sort().join()) return void (placing = false);
    const content = skill.content ?? "";
    if (await act(async () => (skill = await api.updateSkill(name ?? "", { content, projects: target })))) placing = false;
  }

  function give(id: string, checked: boolean): void {
    givers = checked ? [...givers, id] : givers.filter((g) => g !== id);
  }

  /** What handler's scan found in its files, in a line (the details: SkillReview). */
  function found(s: SkillInfo): string {
    if (!s.scan) return "nothing yet.";
    const parts = scanFindings(s.scan);
    return parts.length ? `${parts.join(", ")}.` : "no script, binary file, URL, hidden character or encoded blob.";
  }

  async function saveSkill(): Promise<void> {
    if (name === null) {
      let made = "";
      if (await act(async () => (made = (await api.createSkill({ content: writeSkill(doc), projects: givers })).name))) {
        leaving.unsaved = false;
        navigate({ view: "skill", name: made }, true);
      }
      return;
    }
    const body = { content: writeSkill(doc), projects: skill?.projects ?? [] };
    let saved = "";
    if (await act(async () => (saved = (await api.updateSkill(name ?? "", body)).name))) {
      if (saved !== name) {
        leaving.unsaved = false;
        navigate({ view: "skill", name: saved }, true); // renamed: its page follows
      } else await act(load);
    }
  }

  /** Its SKILL.md as edited, with its other files, as a new skill used by no agent yet: the change
   *  stays out of the agents that get this one. Its new name: the one typed in the form, or asked. */
  async function saveAsNew(): Promise<void> {
    if (!name) return;
    let newName = doc.name.trim();
    if (newName === name) {
      newName = prompt("The new skill's name (lowercase letters, digits and hyphens):", `${name}-2`)?.trim() ?? "";
      if (!newName) return;
    }
    const body = { content: writeSkill({ ...doc, name: newName }), copyOf: name };
    let made = "";
    if (await act(async () => (made = (await api.createSkill(body)).name))) {
      leaving.unsaved = false;
      navigate({ view: "skill", name: made }, true);
    }
  }

  function discard(): void {
    doc = readSkill(skill?.content ?? "");
  }

  async function saveFile(): Promise<void> {
    if (!file || !name || file.text === null) return;
    const { path, text, executable } = file;
    if (await act(async () => (skill = await api.writeSkillFile(name ?? "", path, { text, executable })))) {
      file = { ...file, was: text, isNew: false };
    }
  }

  async function removeFile(): Promise<void> {
    if (!file || !name || !confirm(`Delete ${file.path}?`)) return;
    const path = file.path;
    if (await act(async () => (skill = await api.deleteSkillFile(name ?? "", path)))) file = null;
  }

  async function removeSkill(): Promise<void> {
    if (!skill) return;
    const users = skill.usedBy?.length ? ` It is taken from ${skill.usedBy.join(", ")}.` : "";
    if (!confirm(`Delete the skill ${skill.name} and its folder?${users}`)) return;
    if (await act(() => api.deleteSkill(skill?.name ?? ""))) {
      leaving.unsaved = false;
      navigate({ view: "skills" }, true);
    }
  }

  async function download(): Promise<void> {
    await act(async () => {
      const url = URL.createObjectURL(await api.exportSkill(name ?? ""));
      Object.assign(document.createElement("a"), { href: url, download: `${name}.zip` }).click();
      URL.revokeObjectURL(url);
    });
  }

  function addFile(): void {
    const path = newPath.trim().replace(/^\/+/, "");
    if (!path) return;
    if (fileChanged && !confirm(`Drop your changes to ${file?.path}?`)) return;
    file = { path, text: "", was: null, size: 0, executable: path.startsWith("scripts/"), isNew: true };
    newPath = "";
    adding = false;
  }

  async function base64(f: File): Promise<string> {
    const bytes = new Uint8Array(await f.arrayBuffer());
    let binary = "";
    for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    return btoa(binary);
  }

  async function upload(chosen: FileList | null): Promise<void> {
    if (!name || !chosen?.length) return;
    let last = "";
    await act(async () => {
      for (const f of Array.from(chosen)) {
        last = uploadInto ? `${uploadInto}/${f.name}` : f.name;
        skill = await api.writeSkillFile(name ?? "", last, { base64: await base64(f), executable: last.startsWith("scripts/") });
      }
    });
    if (uploads) uploads.value = "";
    if (last) await select(last);
  }

  function size(bytes: number): string {
    return bytes < 1024 ? `${bytes} B` : bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} kB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  }

  $effect(() => {
    untrack(() => void act(load)); // once: what it reads (the form) must not load it again
  });
</script>

{#snippet projectChecks()}
  {#if projects.list.length}
    <div class="max-h-60 divide-y overflow-y-auto rounded-lg border bg-card" data-testid="skill-projects">
      {#each projects.list as p (p.id)}
        <PickRow name={`All agents of ${p.name}`} checked={givers.includes(p.id)} onchange={(checked) => give(p.id, checked)} testid="skill-project" />
      {/each}
    </div>
  {/if}
  <p class="text-xs text-muted-foreground">Any other agent may also pick it in its settings.</p>
{/snippet}

{#snippet placement(s: SkillInfo)}
  {#if placing}
    <div class="max-w-md space-y-2">
      {@render projectChecks()}
      <div class="flex gap-2">
        <Button size="sm" disabled={busy || !s.content} onclick={place} data-testid="skill-place">Apply</Button>
        <Button variant="ghost" size="sm" onclick={() => (placing = false)}>Cancel</Button>
      </div>
      {#if error}<p class="text-sm text-danger">{error}</p>{/if}
    </div>
  {:else}
    <div class="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm">
      <span data-testid="skill-who">{users ? `Used by ${users}.` : "No agent uses it yet: give it to a project's agents, or pick it in an agent's settings."}</span>
      <Button variant="outline" size="xs" onclick={() => ((givers = [...(s.projects ?? [])]), (placing = true))} data-testid="skill-change-who">Change</Button>
    </div>
  {/if}
{/snippet}

<PageHeader titled title={name ?? "New skill"} parent={{ label: "Skills", href: list }}>
  {#snippet actions()}
    {#if name !== null}
      <Button variant="ghost" size="sm" disabled={busy} onclick={download} data-testid="skill-download"><Download />Download</Button>
      <Button variant="ghost" size="sm" class="text-destructive hover:text-destructive" disabled={busy || !skill} onclick={removeSkill} data-testid="skill-delete"><Trash />Delete</Button>
    {/if}
  {/snippet}
</PageHeader>
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto grid w-full max-w-6xl gap-6 px-8 py-10 md:grid-cols-[14rem_1fr]" data-testid="skill-editor">
    <div class="space-y-3 md:col-span-2">
      <PageTitle title={name ?? "New skill"} />
      {#if skill && !imported}
        <div class="space-y-1" data-testid="skill-placement">
          <div class="text-xs font-medium text-muted-foreground">Who gets it</div>
          {@render placement(skill)}
        </div>
        <UsesPanel kind="skill" id={skill.name} />
      {/if}
    </div>
    {#if skill && imported}
      {@const unused = !users}
      <section class="space-y-4 rounded-lg border bg-card p-5 md:col-span-2" data-testid="skill-imported">
        <div class="flex items-start justify-between gap-3">
          <div class="space-y-1">
            <h2 class="flex items-center gap-2 text-base font-semibold">
              <CircleCheck class="size-4 shrink-0 text-primary" />{skill.name} is in your library
            </h2>
            {#if imported === "replaced"}
              <p class="text-sm {unused ? 'text-muted-foreground' : 'text-warn'}">
                Its files were replaced by the imported ones{unused ? ". No agent uses it yet." : ": the agents that get it (below) use this version now."}
              </p>
            {:else}
              <p class="text-sm text-muted-foreground">It is saved{unused ? ": no agent uses it until you choose who gets it." : "."}</p>
            {/if}
          </div>
          <Button variant="ghost" size="icon-sm" aria-label="Close" onclick={() => navigate({ view: "skill", name }, true)} data-testid="skill-imported-close"><X /></Button>
        </div>
        <div class="grid gap-3 md:grid-cols-2">
          <div class="space-y-2 rounded-lg border p-3.5 text-sm">
            <div class="font-medium">1. Check it</div>
            <p class="text-xs text-muted-foreground">These are someone else's instructions to your agents. Handler found in its files: {found(skill)}</p>
            <Button
              variant="outline"
              size="sm"
              onclick={() => document.getElementById("skill-reviews")?.scrollIntoView({ behavior: "smooth" })}
              data-testid="skill-imported-review">Have it reviewed</Button
            >
          </div>
          <div class="space-y-2 rounded-lg border p-3.5 text-sm" data-testid="skill-placement">
            <div class="font-medium">2. Choose who gets it</div>
            {@render placement(skill)}
          </div>
        </div>
        {#if unused}<p class="text-xs text-muted-foreground">Not now? It stays in your library, used by no agent: close this and come back to it any time.</p>{/if}
      </section>
    {/if}
    <nav class="space-y-1 text-sm" aria-label="files">
      <div class="px-2 pb-1 text-xs font-medium text-muted-foreground">Files</div>
      <button
        type="button"
        class="flex w-full cursor-pointer items-center justify-between rounded px-2 py-1 text-left font-mono text-xs {file === null ? 'bg-muted font-medium' : 'hover:bg-muted/60'}"
        onclick={() => select(null)}
      >
        {SKILL_FILE}{#if skillChanged}<span class="size-1.5 rounded-full bg-warn" title="unsaved"></span>{/if}
      </button>
      {#each skill?.files ?? [] as f (f.path)}
        <button
          type="button"
          class="flex w-full cursor-pointer items-center justify-between gap-2 rounded px-2 py-1 text-left font-mono text-xs {file?.path === f.path ? 'bg-muted font-medium' : 'hover:bg-muted/60'}"
          title={`${f.path} · ${size(f.size)}`}
          onclick={() => select(f.path)}
          data-testid="skill-file"
        >
          <span class="truncate">{f.path}</span>
          <span class="flex shrink-0 items-center gap-1.5">
            {#if f.executable}<span class="rounded bg-muted px-1 font-sans text-[0.65rem] text-muted-foreground">runs</span>{/if}
            {#if file?.path === f.path && fileChanged}<span class="size-1.5 rounded-full bg-warn" title="unsaved"></span>{/if}
          </span>
        </button>
      {/each}
      {#if file?.isNew}
        <div class="flex items-center justify-between rounded bg-muted px-2 py-1 font-mono text-xs font-medium">
          <span class="truncate">{file.path}</span><span class="size-1.5 shrink-0 rounded-full bg-warn" title="unsaved"></span>
        </div>
      {/if}
      {#if name !== null}
        <div class="space-y-2 border-t pt-3">
          {#if adding}
            <form class="space-y-1.5" onsubmit={(e) => (e.preventDefault(), addFile())}>
              <Input bind:value={newPath} placeholder="e.g. scripts/check.sh" class="h-8 font-mono text-xs" data-testid="skill-new-path" />
              <div class="flex gap-1">
                <Button type="submit" size="sm" disabled={!newPath.trim()} data-testid="skill-add-file">Add</Button>
                <Button type="button" variant="ghost" size="sm" onclick={() => (adding = false)}>Cancel</Button>
              </div>
            </form>
          {:else}
            <Button variant="outline" size="sm" class="w-full justify-start" onclick={() => (adding = true)} data-testid="skill-new-file"><Plus />Add a file</Button>
          {/if}
          <div class="flex gap-1">
            <NativeSelect.Root class="h-8 min-w-0 flex-1 text-xs" bind:value={uploadInto} title="the folder uploaded files go into">
              <NativeSelect.Option value="">top level</NativeSelect.Option>
              {#each folders as f (f)}<NativeSelect.Option value={f}>{f}/</NativeSelect.Option>{/each}
            </NativeSelect.Root>
            <Button variant="outline" size="sm" disabled={busy} onclick={() => uploads?.click()}><Upload />Upload</Button>
            <input bind:this={uploads} type="file" multiple class="hidden" onchange={(e) => upload(e.currentTarget.files)} data-testid="skill-upload" />
          </div>
          <p class="text-xs text-muted-foreground">Files in <code>scripts/</code> are made executable: they <em>run</em> in the agent's sandbox.</p>
        </div>
      {:else}
        <p class="border-t px-2 pt-3 text-xs text-muted-foreground">Create the skill, then add its scripts and references.</p>
      {/if}
    </nav>

    <div class="min-w-0 space-y-4">
      {#if file === null}
        <div class="grid gap-4 sm:grid-cols-[1fr_1fr]">
          <div class="space-y-1.5">
            <Label for="skill-name">Name</Label>
            <Input id="skill-name" bind:value={doc.name} placeholder="e.g. code-review" class="font-mono" data-testid="skill-name" />
            <p class="text-xs text-muted-foreground">Lowercase letters, digits, hyphens. Renaming keeps its agents.</p>
          </div>
          {#if name === null}
            <div class="space-y-1.5">
              <Label>Who gets it</Label>
              {@render projectChecks()}
            </div>
          {/if}
        </div>
        <div class="space-y-1.5">
          <Label for="skill-description">When to use it</Label>
          <Textarea
            id="skill-description"
            bind:value={doc.description}
            rows={2}
            placeholder="What it does, and when the agent should use it, e.g. Review a diff for bugs and style; use before committing."
            data-testid="skill-description"
          />
          <p class="text-xs text-muted-foreground">The agent reads this to decide when to load the skill.</p>
        </div>
        <div class="space-y-1.5">
          <Label for="skill-body">Instructions</Label>
          <Textarea id="skill-body" bind:value={doc.body} rows={18} class="min-h-80 font-mono text-xs" spellcheck={false} data-testid="skill-content" />
        </div>
        <details class="space-y-1.5 text-sm" open={doc.other !== ""}>
          <summary class="cursor-pointer text-muted-foreground">Other fields{doc.other ? "" : " (none)"}</summary>
          <Textarea bind:value={doc.other} rows={4} class="font-mono text-xs" spellcheck={false} placeholder="license: MIT" data-testid="skill-other" />
          <p class="text-xs text-muted-foreground">More of the SKILL.md frontmatter, as YAML (<code>license</code>, <code>compatibility</code>, <code>metadata</code>…).</p>
        </details>
        <div class="flex min-h-7.5 items-center gap-2">
          {#if name === null}
            <Button size="sm" disabled={busy || !doc.name.trim()} onclick={saveSkill} data-testid="skill-save">Create</Button>
            <Button variant="ghost" size="sm" href={list}>Cancel</Button>
          {:else if skillChanged}
            <span class="text-sm text-warn">Unsaved changes</span>
            <Button size="sm" disabled={busy || !doc.name.trim()} onclick={saveSkill} data-testid="skill-save">Save</Button>
            {#if users}
              <Button variant="outline" size="sm" disabled={busy || !doc.name.trim()} onclick={saveAsNew} data-testid="skill-save-new">Save as a new skill</Button>
            {/if}
            <Button variant="ghost" size="sm" disabled={busy} onclick={discard} data-testid="skill-discard">Discard</Button>
          {:else}
            <p class="text-xs text-muted-foreground" data-testid="skill-saved">Saved in your library.</p>
          {/if}
        </div>
        {#if name !== null && skillChanged && users}
          <p class="-mt-2 text-xs text-muted-foreground" data-testid="skill-affects">
            Save changes it for {users}. To change it for some of them only: save it as a new skill, then give that one to them.
          </p>
        {/if}
      {:else}
        <div class="font-mono text-sm">{file.path}</div>
        {#if file.text !== null}
          <Textarea bind:value={file.text} rows={22} class="min-h-96 font-mono text-xs" spellcheck={false} data-testid="skill-file-content" />
        {:else}
          <p class="text-sm text-muted-foreground">A binary file ({size(file.size)}). Upload it again to replace it.</p>
        {/if}
        <div class="flex flex-wrap items-center gap-2">
          {#if file.text !== null}
            <Button size="sm" disabled={busy || !fileChanged} onclick={saveFile} data-testid="skill-file-save">Save</Button>
            <label class="flex items-center gap-1.5 text-sm">
              <Checkbox checked={file.executable} onCheckedChange={(c) => file && (file.executable = c === true)} />
              Runs (executable, saved with it)
            </label>
          {/if}
          {#if fileChanged && users}<span class="text-xs text-muted-foreground">Changes it for {users}.</span>{/if}
          {#if !file.isNew}
            <Button variant="ghost" size="sm" class="text-destructive hover:text-destructive" disabled={busy} onclick={removeFile} data-testid="skill-file-delete">Delete this file</Button>
          {:else}
            <Button variant="ghost" size="sm" onclick={() => (file = null)}>Cancel</Button>
          {/if}
        </div>
      {/if}
      {#if error && !placing}<p class="text-sm text-danger" data-testid="skill-error">{error}</p>{/if}
      {#if skill && name !== null}<SkillReview {skill} />{/if}
    </div>
  </div>
</div>
