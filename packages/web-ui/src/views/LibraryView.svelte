<script lang="ts">
  // The Library (#/library[/:shelf][/more], `project`: Agents' Community for a project): its header (the shelves as tabs, each with how many
  // you have), then the shelf, Yours or Community (lib/library.ts), each list headed by the two (ShelfBar: how many each has). Notes
  // also open at #/notes (a folder, a note: `knowledge` routes).
  import PageHeader from "../components/PageHeader.svelte";
  import { api } from "../lib/api";
  import { communityCount, GETS_MORE, LIBRARY_WIDTH, libraryTabs, yourAgents, type ShelfLists } from "../lib/library";
  import type { Source } from "../lib/contracts.gen";
  import type { LibraryShelf } from "../lib/router.svelte";
  import AddonsView from "./AddonsView.svelte";
  import AgentsShelf from "./AgentsShelf.svelte";
  import AppsShelf from "./AppsShelf.svelte";
  import AutomationsView from "./AutomationsView.svelte";
  import KnowledgeView from "./KnowledgeView.svelte";
  import SchemasView from "./SchemasView.svelte";
  import SkillsView from "./SkillsView.svelte";

  let { shelf, more = false, install, project, path, note }: { shelf: LibraryShelf; more?: boolean; install?: string; project?: string; path?: string; note?: string } = $props();

  let counts = $state<Partial<Record<LibraryShelf, number>>>({});
  let sources = $state<Source[] | null>(null);
  let examples = $state<number | null>(null); // Handler's automation examples

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
    void count("schemas", api.schemas());
    api.sources().then(
      (s) => (sources = s),
      () => undefined,
    );
    api.automationExamples().then(
      (e) => (examples = e.length),
      () => undefined,
    );
    api.knowledge().then(
      (k) => (counts = { ...counts, notes: k.folders.length }),
      () => undefined,
    );
  });

  // the shelf's two lists, at the head of its list (not on Notes and Schemas)
  const lists = $derived<ShelfLists | undefined>(GETS_MORE[shelf] ? { shelf, more, yours: counts[shelf], community: communityCount(shelf, sources, examples) } : undefined);
</script>

<PageHeader title="Library" tabs={libraryTabs(shelf, counts)} width={LIBRARY_WIDTH} />
{#if shelf === "agents"}
  <AgentsShelf {more} {project} {lists} />
{:else if shelf === "tools"}
  <AddonsView {more} {install} {lists} />
{:else if shelf === "skills"}
  <SkillsView {more} {lists} />
{:else if shelf === "notes"}
  <KnowledgeView {path} {note} />
{:else if shelf === "schemas"}
  <SchemasView />
{:else if shelf === "automations"}
  <AutomationsView {more} {lists} />
{:else}
  <AppsShelf {more} {lists} />
{/if}
