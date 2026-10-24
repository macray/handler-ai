<script lang="ts">
  // Pick an agent's skills (D.17) from the library; the skills its project gives to all its agents
  // are listed first as such (checked, not choosable), then those used in its project, then the
  // others, each saying which other projects use it. None picked by default. Invalid skills are
  // not selectable (Settings lists them with their error).
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import { api } from "../lib/api";
  import type { SkillInfo } from "../lib/contracts.gen";
  import { byUse, projects } from "../lib/projects.svelte";
  import { href } from "../lib/router.svelte";
  import PickRow from "./PickRow.svelte";

  let {
    projectId,
    value = $bindable([]),
    pending = [],
  }: {
    projectId?: string; // none: an ad-hoc agent
    value?: string[];
    pending?: string[]; // the skills of the definition it is set up from, added to the library when it is saved (D.18)
  } = $props();

  let skills = $state<SkillInfo[]>([]);
  let loaded = $state(false);
  let error = $state<string | null>(null);

  $effect(() => {
    api.skills().then(
      (list) => {
        skills = list;
        loaded = true;
      },
      (e: Error) => (error = e.message),
    );
  });

  const isGiven = (s: SkillInfo) => !!projectId && !!s.projects?.includes(projectId); // by its project
  const given = $derived(skills.filter(isGiven));
  const offered = $derived(skills.filter((s) => !isGiven(s)));
  const selectable = $derived(offered.filter((s) => !s.error));
  const invalid = $derived(offered.length - selectable.length);
  const ordered = $derived(byUse(projects.list, selectable, projectId));

  // drop what is no longer selectable (deleted by hand, invalid), once listed
  $effect(() => {
    if (!loaded) return;
    const keep = value.filter((name) => selectable.some((s) => s.name === name) || pending.includes(name));
    if (keep.length !== value.length) value = keep;
  });

  // the definition's skills not in the library yet
  const newOnes = $derived(loaded ? pending.filter((name) => !skills.some((s) => s.name === name)) : []);
  const rows = $derived(given.length + selectable.length + newOnes.length);
  const FILTER_FROM = 8; // rows from which a filter is offered
  let query = $state("");
  function shown(s: { name: string; description?: string | null }): boolean {
    const q = query.trim().toLowerCase();
    return !q || s.name.toLowerCase().includes(q) || (s.description ?? "").toLowerCase().includes(q);
  }

  function toggle(name: string, checked: boolean): void {
    value = checked ? [...value, name] : value.filter((n) => n !== name);
  }
</script>

<div class="space-y-2" data-testid="skill-picker">
  <div class="flex items-center gap-3">
    <Label>Skills</Label>
    {#if value.length || given.length}
      <span class="text-xs text-muted-foreground" data-testid="skill-count">
        {[value.length ? `${value.length} picked` : "", given.length ? `${given.length} from the project` : ""].filter(Boolean).join(" · ")}
      </span>
    {/if}
    {#if rows > FILTER_FROM}
      <Input class="ml-auto h-7 w-48 text-xs" bind:value={query} placeholder="Filter skills" aria-label="filter skills"
        onkeydown={(e) => e.key === "Enter" && e.preventDefault()}
        data-testid="skill-filter"
      />
    {/if}
  </div>
  <p class="text-xs text-muted-foreground">
    What the agent loads when a task calls for it, from your
    <a class="text-link hover:underline" href={href({ view: "skills" })}>skill library</a>.
  </p>
  {#if error}<p class="text-sm text-danger">{error}</p>{/if}
  {#if rows}
    <div class="max-h-96 divide-y overflow-y-auto rounded-lg border bg-card">
      {#each given.filter(shown) as s (s.name)}
        <PickRow name={s.name} description={s.description ?? ""} badge="from the project" checked disabled />
      {/each}
      {#each ordered.filter((r) => shown(r.choice)) as { choice: s, note } (s.name)}
        <PickRow
          name={s.name}
          description={s.description ?? ""}
          {note}
          checked={value.includes(s.name)}
          onchange={(checked) => toggle(s.name, checked)}
          testid="skill-option"
        />
      {/each}
      {#each newOnes.filter((name) => shown({ name })) as name (name)}
        <PickRow
          {name}
          description="Comes with what you set up: added to your library when you save."
          badge="new"
          checked={value.includes(name)}
          onchange={(checked) => toggle(name, checked)}
        />
      {/each}
      {#if ![...given, ...selectable, ...newOnes.map((name) => ({ name }))].some(shown)}
        <p class="px-3 py-2 text-xs text-muted-foreground">No skill matches.</p>
      {/if}
    </div>
  {:else if loaded}
    <p class="text-xs text-muted-foreground">No skill in the library yet.</p>
  {/if}
  {#if invalid}
    <p class="text-xs text-muted-foreground">{invalid} invalid skill(s): see Settings.</p>
  {/if}
</div>
