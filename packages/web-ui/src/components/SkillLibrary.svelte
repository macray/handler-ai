<script lang="ts">
  // Skills (D.17): the library, in ~/.config/handler-ai/skills. A skill is a folder (its SKILL.md,
  // scripts, references, assets), offered to every agent; a project may give it to all its agents.
  // The Library's Skills shelf: yours listed, each with who uses it and a link to its editor
  // (SkillView; a broken one says so in amber, its page has the fix), or Get more (`more`), the
  // ways to make new ones: written there, with an agent (a session of a folderless agent with the skill-creator skill,
  // D.18: saved to the library from it), or imported from a zip archive (a `.skill` file) or a
  // URL (a repository's folder): an import writes the skill to the library, used by no agent yet,
  // then opens its page saying so, with what to do next (have it reviewed, choose who gets it).
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import FilePenLine from "@lucide/svelte/icons/file-pen-line";
  import ScrollText from "@lucide/svelte/icons/scroll-text";
  import Bot from "@lucide/svelte/icons/bot";
  import Link from "@lucide/svelte/icons/link";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import Upload from "@lucide/svelte/icons/upload";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { api, ApiError } from "../lib/api";
  import type { Agent, SkillInfo } from "../lib/contracts.gen";
  import { agentLabel, projects } from "../lib/projects.svelte";
  import { who } from "../lib/skills";
  import { sessions } from "../lib/sessions.svelte";
  import HelperCard from "./HelperCard.svelte";
  import { href, navigate } from "../lib/router.svelte";
  import LoadingCards from "./LoadingCards.svelte";

  let { more = false }: { more?: boolean } = $props(); // Get more: the ways to make or import one

  let skills = $state<SkillInfo[]>([]);
  let loaded = $state(false);
  let byUrl = $state(false); // the URL field shown, once "From a URL" is chosen
  let url = $state("");
  let busy = $state(false);
  let archives = $state<HTMLInputElement | null>(null);
  let error = $state<string | null>(null);
  // the agent that writes skills with you: the skill creator Handler uses (D.18), once set up
  let creator = $state<Agent | null>(null);
  let creatorCard = $state(false); // no skill creator yet: its set-up card

  // The four ways, each a card: clickable, not a form to fill.
  const CHOICE =
    "flex w-full items-start gap-3 rounded-[10px] border bg-card p-3.5 text-left text-sm text-foreground no-underline transition-colors hover:border-primary/60 hover:bg-muted/30 disabled:opacity-50";
  const TILE = "flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground";

  async function load(): Promise<void> {
    try {
      skills = await api.skills();
      if (!projects.loaded) await projects.refresh();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      loaded = true;
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
    Promise.all([api.agents(), api.handlerNeeds()]).then(
      ([all, needs]) => {
        const given = needs.find((b) => b.name === "skill-creator")?.agentId; // D.18
        creator = all.find((a) => a.id === given) ?? null;
      },
      () => (creator = null),
    );
  });
</script>

{#snippet ways()}
  <div class="grid gap-3 sm:grid-cols-2">
    <a href={href({ view: "skill", name: null })} class={CHOICE} data-testid="skill-write">
      <span class={TILE}><FilePenLine class="size-4" /></span>
      <span class="space-y-0.5">
        <span class="block font-medium">Write your own</span>
        <span class="block text-xs text-muted-foreground">Start from a blank SKILL.md.</span>
      </span>
    </a>
    {#if creator}
      <button type="button" class={CHOICE} disabled={busy} onclick={withAgent} data-testid="skill-with-agent">
        <span class={TILE}><Bot class="size-4" /></span>
        <span class="space-y-0.5">
          <span class="block font-medium">With an agent</span>
          <span class="block text-xs text-muted-foreground">{agentLabel(creator)} writes it with you, in a folder of its own; then Save to library.</span>
        </span>
      </button>
    {:else}
      <button type="button" class={CHOICE} aria-expanded={creatorCard} onclick={() => (creatorCard = !creatorCard)} data-testid="skill-with-agent">
        <span class={TILE}><Bot class="size-4" /></span>
        <span class="space-y-0.5">
          <span class="block font-medium">With an agent</span>
          <span class="block text-xs text-muted-foreground">Turn on the skill creator, then write skills with it.</span>
        </span>
      </button>
    {/if}
    <button type="button" class={CHOICE} disabled={busy} onclick={() => archives?.click()} data-testid="import-skill">
      <span class={TILE}><Upload class="size-4" /></span>
      <span class="space-y-0.5">
        <span class="block font-medium">Upload a file</span>
        <span class="block text-xs text-muted-foreground">A <span class="font-mono">.skill</span> or <span class="font-mono">.zip</span> archive from your computer.</span>
      </span>
    </button>
    <button
      type="button"
      class="{CHOICE} {byUrl ? 'border-primary/60 bg-muted/30' : ''}"
      aria-pressed={byUrl}
      onclick={() => (byUrl = !byUrl)}
      data-testid="skill-by-url"
    >
      <span class={TILE}><Link class="size-4" /></span>
      <span class="space-y-0.5">
        <span class="block font-medium">From a URL</span>
        <span class="block text-xs text-muted-foreground">A skill's folder in a GitHub repository, or a link to an archive.</span>
      </span>
    </button>
  </div>
  {#if creatorCard && !creator}
    <HelperCard need="skill-creator" onready={(a) => ((creator = a), (creatorCard = false), void withAgent())}>
      {#snippet preview()}
        <pre class="font-mono text-xs leading-relaxed">---
name: liquid-style
when: editing .liquid files
---
Prefer {"{% render %}"} over {"{% include %}"}…</pre>
      {/snippet}
    </HelperCard>
  {/if}
  {#if byUrl}
    <form class="flex gap-2" onsubmit={(e) => (e.preventDefault(), url.trim() && fromUrl())}>
      <!-- svelte-ignore a11y_autofocus -->
      <Input bind:value={url} autofocus placeholder="https://github.com/owner/repo/tree/main/skills/name" class="font-mono text-xs" data-testid="skill-url" />
      <Button type="submit" disabled={busy || !url.trim()} data-testid="skill-url-import">{busy ? "Importing…" : "Import"}</Button>
    </form>
  {/if}
  <p class="text-xs text-muted-foreground">
    An import goes straight to your library: no agent uses it until you give it to a project's agents or an agent picks it. Its page then offers
    to have it reviewed and to choose who gets it.
  </p>
  {#if error}<p class="text-sm text-danger" data-testid="skill-error">{error}</p>{/if}
{/snippet}

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

<section class="space-y-5" data-testid="skills">
  {#if more}
    <div class="space-y-4" data-testid="skill-new">{@render ways()}</div>
  {:else if !loaded}
    <div class="space-y-3"><LoadingCards count={3} height="h-16" /></div>
  {:else if skills.length}
    {#if error}<p class="text-sm text-danger" data-testid="skill-error">{error}</p>{/if}
    <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
      {#each skills as s (s.name)}
        <li class="enter">
          <a
            href={href({ view: "skill", name: s.name })}
            class="group flex items-center gap-4 px-4 py-3.5 text-foreground no-underline transition-colors hover:bg-muted/40"
            data-testid="skill-card"
          >
            <span class="hidden size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground sm:flex"><ScrollText class="size-4" /></span>
            <div class="min-w-0 flex-1 space-y-0.5">
              <p class="font-medium">{s.name}</p>
              {#if s.description}<p class="line-clamp-2 text-muted-foreground">{s.description}</p>{/if}
              <p class="fact truncate" title={use(s)} data-testid="skill-use">{[files(s), use(s)].filter(Boolean).join(" · ")}</p>
            </div>
            {#if s.error}
              <span class="inline-flex items-center gap-1 text-xs text-warn" title={s.error} data-testid="skill-broken"><TriangleAlert class="size-3" />Broken</span>
              <span class="rounded-md border px-2.5 py-1 text-xs font-medium">Fix</span>
            {:else}
              <ChevronRight class="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
            {/if}
          </a>
        </li>
      {/each}
    </ul>
  {:else}
    <div class="rounded-[10px] border border-dashed px-6 py-8 text-center text-sm text-muted-foreground" data-testid="skills-none">
      <p>No skill yet: instructions, and the scripts that go with them, an agent reads when a task calls for them.</p>
      <Button size="sm" class="mt-3" href={href({ view: "library", shelf: "skills", more: true })} data-testid="new-skill">Get a skill</Button>
    </div>
  {/if}
</section>
