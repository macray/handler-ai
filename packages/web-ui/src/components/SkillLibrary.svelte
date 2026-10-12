<script lang="ts">
  // Skills (D.17): the library, in ~/.config/handler-ai/skills. A skill is a folder (its SKILL.md,
  // scripts, references, assets), offered to every agent; a project may give it to all its agents.
  // This page lists them, each with who uses it and a link to its editor (SkillView), and makes
  // new ones:
  // written there, with an agent (a session of a folderless agent with the skill-creator skill,
  // D.18: saved to the library from it), or imported from a zip archive (a `.skill` file) or a
  // URL (a repository's folder): an import writes the skill to the library, used by no agent yet,
  // then opens its page saying so, with what to do next (have it reviewed, choose who gets it).
  import FilePenLine from "@lucide/svelte/icons/file-pen-line";
  import Bot from "@lucide/svelte/icons/bot";
  import Link from "@lucide/svelte/icons/link";
  import Plus from "@lucide/svelte/icons/plus";
  import Upload from "@lucide/svelte/icons/upload";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { api, ApiError } from "../lib/api";
  import type { Agent, SkillInfo } from "../lib/contracts.gen";
  import { agentLabel, projects } from "../lib/projects.svelte";
  import { who } from "../lib/skills";
  import { sessions } from "../lib/sessions.svelte";
  import { href, navigate } from "../lib/router.svelte";
  import LoadingCards from "./LoadingCards.svelte";

  let skills = $state<SkillInfo[]>([]);
  let loaded = $state(false);
  let adding = $state(false); // the ways to make a new skill shown
  let byUrl = $state(false); // the URL field shown, once "From a URL" is chosen
  let url = $state("");
  let busy = $state(false);
  let archives = $state<HTMLInputElement | null>(null);
  let error = $state<string | null>(null);
  // the agent that writes skills with you: the built-in skill creator (D.18), once set up
  let creator = $state<Agent | null>(null);

  const STEPS = ["Write or import a skill", "Give it to a project's agents, or pick it in an agent's settings"];
  // The four ways, each a card like the skills' own cards: clickable, not a form to fill.
  const CHOICE =
    "flex w-full items-start gap-3 rounded-lg border bg-card p-3.5 text-left text-sm text-foreground no-underline hover:border-primary/60 disabled:opacity-50";

  async function load(): Promise<void> {
    try {
      skills = await api.skills();
      if (!projects.loaded) await projects.refresh();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      loaded = true;
      if (!skills.length) adding = true;
    }
  }

  /** An import, asking before it replaces the skill of its name; then that skill's editor. */
  async function imported(attempt: (replace: boolean) => Promise<SkillInfo>, what: string): Promise<void> {
    busy = true;
    error = null;
    try {
      let skill: SkillInfo;
      let replaced = false;
      try {
        skill = await attempt(false);
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 409)) throw e;
        if (!confirm(`The skill ${e.detail} exists: replace all its files with those of ${what}?`)) return;
        skill = await attempt(true);
        replaced = true;
      }
      navigate({ view: "skill", name: skill.name, imported: replaced ? "replaced" : "new" });
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
      if (archives) archives.value = "";
    }
  }

  /** A session of the skill creator, in a folder of its own: the skill is saved from there. */
  async function withAgent(): Promise<void> {
    if (!creator) return;
    busy = true;
    error = null;
    try {
      navigate({ view: "session", key: (await sessions.start(creator)).key });
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  const fromArchive = (file: File) => imported((replace) => api.importSkill(file, { replace }), file.name);
  const fromUrl = () => imported((replace) => api.importSkillUrl(url.trim(), { replace }), url.trim());

  function files(s: SkillInfo): string {
    const n = s.files?.length ?? 0;
    const runs = s.files?.filter((f) => f.executable).length ?? 0;
    if (!n) return "";
    return `+ ${n} file${n === 1 ? "" : "s"}${runs ? `, ${runs} script${runs === 1 ? "" : "s"}` : ""}`;
  }

  function use(s: SkillInfo): string {
    return who(s, projects.list) || "not used yet";
  }

  $effect(() => {
    void load();
    api.agents().then(
      (all) => (creator = all.find((a) => a.origin === "skill-creator") ?? null),
      () => (creator = null),
    );
  });
</script>

<section class="space-y-8" data-testid="skills">
  <div class="flex flex-wrap items-start justify-between gap-3">
    <div class="space-y-3">
      <p class="max-w-2xl text-sm text-muted-foreground">
        Instructions, and the scripts that go with them, an agent reads when a task calls for them: how to review code, how this
        shop's theme is deployed… Optional.
      </p>
      <ol class="flex flex-wrap gap-x-6 gap-y-1.5 text-sm" data-testid="skills-steps">
        {#each STEPS as step, i (step)}
          <li class="flex items-center gap-2">
            <span class="flex size-5 shrink-0 items-center justify-center rounded-full bg-muted text-xs text-muted-foreground">{i + 1}</span>{step}
          </li>
        {/each}
      </ol>
    </div>
    {#if loaded && !adding}
      <Button variant="outline" size="sm" onclick={() => (adding = true)} data-testid="new-skill"><Plus />New skill</Button>
    {/if}
  </div>

  {#if adding}
    <div class="space-y-3 text-sm" data-testid="skill-new">
      <div class="flex items-center justify-between">
        <h2 class="text-base font-semibold">New skill <span class="text-sm font-normal text-muted-foreground">· choose how to start</span></h2>
        {#if skills.length}<Button variant="ghost" size="sm" onclick={() => ((adding = false), (byUrl = false))}>Close</Button>{/if}
      </div>
      <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <a href={href({ view: "skill", name: null })} class={CHOICE} data-testid="skill-write">
          <FilePenLine class="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          <span class="space-y-1">
            <span class="block font-medium">Write your own</span>
            <span class="block text-xs text-muted-foreground">Start from a blank SKILL.md.</span>
          </span>
        </a>
        {#if creator}
          <button type="button" class={CHOICE} disabled={busy} onclick={withAgent} data-testid="skill-with-agent">
            <Bot class="mt-0.5 size-4 shrink-0 text-muted-foreground" />
            <span class="space-y-1">
              <span class="block font-medium">With an agent</span>
              <span class="block text-xs text-muted-foreground">{agentLabel(creator)} writes it with you, in a folder of its own; then Save to library.</span>
            </span>
          </button>
        {:else}
          <a href={href({ view: "edit-ad-hoc", builtin: "skill-creator" })} class={CHOICE} data-testid="skill-with-agent">
            <Bot class="mt-0.5 size-4 shrink-0 text-muted-foreground" />
            <span class="space-y-1">
              <span class="block font-medium">With an agent</span>
              <span class="block text-xs text-muted-foreground">First set up the Skill creator (choose its models), then write skills with it.</span>
            </span>
          </a>
        {/if}
        <button type="button" class={CHOICE} disabled={busy} onclick={() => archives?.click()} data-testid="import-skill">
          <Upload class="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          <span class="space-y-1">
            <span class="block font-medium">Upload a file</span>
            <span class="block text-xs text-muted-foreground">A <code>.skill</code> or <code>.zip</code> archive from your computer.</span>
          </span>
        </button>
        <button
          type="button"
          class="{CHOICE} {byUrl ? 'border-primary' : ''}"
          aria-pressed={byUrl}
          onclick={() => (byUrl = !byUrl)}
          data-testid="skill-by-url"
        >
          <Link class="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          <span class="space-y-1">
            <span class="block font-medium">From a URL</span>
            <span class="block text-xs text-muted-foreground">A skill's folder in a GitHub repository, or a link to an archive.</span>
          </span>
        </button>
      </div>
      <input
        bind:this={archives}
        type="file"
        accept=".zip,.skill"
        class="hidden"
        onchange={(e) => {
          const file = e.currentTarget.files?.[0];
          if (file) void fromArchive(file);
        }}
        data-testid="import-skill-file"
      />
      {#if byUrl}
        <form class="flex gap-2" onsubmit={(e) => (e.preventDefault(), url.trim() && fromUrl())}>
          <!-- svelte-ignore a11y_autofocus -->
          <Input
            bind:value={url}
            autofocus
            placeholder="https://github.com/owner/repo/tree/main/skills/name"
            class="font-mono text-xs"
            data-testid="skill-url"
          />
          <Button type="submit" disabled={busy || !url.trim()} data-testid="skill-url-import">{busy ? "Importing…" : "Import"}</Button>
        </form>
      {/if}
      <p class="text-xs text-muted-foreground">
        An import goes straight to your library: no agent uses it until you give it to a project's agents or an agent picks it. Its page
        then offers to have it reviewed and to choose who gets it.
      </p>
      {#if error}<p class="text-sm text-danger" data-testid="skill-error">{error}</p>{/if}
    </div>
  {/if}

  {#if !loaded}
    <div class="grid gap-3 md:grid-cols-2"><LoadingCards /></div>
  {:else}
    <div class="grid gap-3 md:grid-cols-2">
      {#each skills as s (s.name)}
        <a
          href={href({ view: "skill", name: s.name })}
          class="block space-y-1.5 rounded-lg border bg-card p-3.5 text-sm text-foreground no-underline hover:border-primary/60"
          data-testid="skill-card"
        >
          <div class="font-medium">{s.name}</div>
          {#if s.description}<p class="line-clamp-2 text-xs text-muted-foreground">{s.description}</p>{/if}
          {#if s.error}<p class="text-xs text-danger">invalid: {s.error}</p>{/if}
          <p class="truncate text-xs text-muted-foreground" title={use(s)} data-testid="skill-use">
            {[files(s), use(s)].filter(Boolean).join(" · ")}
          </p>
        </a>
      {/each}
    </div>
  {/if}
</section>
