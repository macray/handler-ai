<script lang="ts">
  // The Library (#/library[/:shelf][/more], `project`: Agents' Get more for a project): its header (the shelves as tabs, each with how many
  // you have; at their right, Yours or Get more, links so the browser's back goes between them), then the shelf, yours or what you can get more of (lib/library.ts). The old
  // addresses (#/tools, #/skills, #/notes, #/automations) open their shelf here too.
  import PageHeader from "../components/PageHeader.svelte";
  import { api } from "../lib/api";
  import { GETS_MORE, LIBRARY_WIDTH, libraryTabs, yourAgents } from "../lib/library";
  import { href, type LibraryShelf } from "../lib/router.svelte";
  import AddonsView from "./AddonsView.svelte";
  import AgentsShelf from "./AgentsShelf.svelte";
  import AppsShelf from "./AppsShelf.svelte";
  import AutomationsView from "./AutomationsView.svelte";
  import KnowledgeView from "./KnowledgeView.svelte";
  import SkillsView from "./SkillsView.svelte";

  let { shelf, more = false, install, project, path, note }: { shelf: LibraryShelf; more?: boolean; install?: string; project?: string; path?: string; note?: string } = $props();

  let counts = $state<Partial<Record<LibraryShelf, number>>>({});

  $effect(() => {
    void shelf; // read again on each shelf: what was got or made there
    void more;
    const count = <T,>(shelf: LibraryShelf, list: Promise<T[]>, keep: (x: T) => boolean = () => true) =>
      list.then(
        (l) => (counts = { ...counts, [shelf]: l.filter(keep).length }),
        () => undefined,
      );
    void count("apps", api.apps());
    api.agents().then(
      (l) => (counts = { ...counts, agents: yourAgents(l).length }),
      () => undefined,
    );
    void count("tools", api.addons(), (a) => !a.builtin);
    void count("skills", api.skills());
    void count("automations", api.automations());
    api.knowledge().then(
      (k) => (counts = { ...counts, notes: k.folders.length }),
      () => undefined,
    );
  });
</script>

<PageHeader title="Library" tabs={libraryTabs(shelf, counts)} width={LIBRARY_WIDTH}>
  {#snippet tabsEnd()}
    {#if GETS_MORE[shelf]}
      <nav class="inline-flex rounded-lg bg-muted p-0.5 text-sm" aria-label="yours or get more">
        {#each [{ more: false, label: "Yours" }, { more: true, label: "Get more" }] as o (o.label)}
          <a
            href={href({ view: "library", shelf, more: o.more })}
            class="rounded-md px-3 py-1 no-underline {o.more === more ? 'bg-background font-medium text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}"
            aria-current={o.more === more ? "page" : undefined}
            data-testid={o.more ? "shelf-more" : "shelf-yours"}>{o.label}</a
          >
        {/each}
      </nav>
    {/if}
  {/snippet}
</PageHeader>
{#if shelf === "agents"}
  <AgentsShelf {more} {project} />
{:else if shelf === "tools"}
  <AddonsView {more} {install} />
{:else if shelf === "skills"}
  <SkillsView {more} />
{:else if shelf === "notes"}
  <KnowledgeView {path} {note} />
{:else if shelf === "automations"}
  <AutomationsView {more} />
{:else}
  <AppsShelf {more} />
{/if}
