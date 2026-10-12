<script lang="ts">
  // Knowledge (D.5): the knowledge root (where it is, changed here unless HANDLER_KNOWLEDGE_DIR sets
  // it), its folders (browse, create) and their notes, read-only. A folder's _index.md, when there
  // is one, is shown first: its summary, then its overview. Each agent gets the folders
  // selected in its settings; "Use in a new project" opens the project editor with the folder selected.
  import BookOpen from "@lucide/svelte/icons/book-open";
  import FileText from "@lucide/svelte/icons/file-text";
  import Folder from "@lucide/svelte/icons/folder";
  import FolderPlus from "@lucide/svelte/icons/folder-plus";
  import { Button } from "$lib/components/ui/button";
  import * as Card from "$lib/components/ui/card";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import PageHeader from "../components/PageHeader.svelte";
  import PageTitle from "../components/PageTitle.svelte";
  import { markdown } from "@handler/acp-view/lib/render";
  import { api } from "../lib/api";
  import type { KnowledgeFolderView, KnowledgeListing, KnowledgeNote } from "../lib/contracts.gen";
  import { dirname, join, resolveLink, splitFrontmatter } from "../lib/knowledge";
  import { href, navigate } from "../lib/router.svelte";

  let { path = ".", note }: { path?: string; note?: string } = $props();

  let listing = $state<KnowledgeListing | null>(null);
  let view = $state<KnowledgeFolderView | null>(null);
  let opened = $state<KnowledgeNote | null>(null);
  let error = $state<string | null>(null);
  let rootInput = $state("");
  let editingRoot = $state(false);
  let newFolder = $state("");

  const folder = $derived(note ? dirname(note) : path);
  const shown = $derived(opened ? splitFrontmatter(opened.text) : view?.index ? splitFrontmatter(view.index) : null);
  const summary = $derived(shown?.meta.find(([k]) => k === "summary")?.[1]);
  const crumbs = $derived(folder === "." ? [] : folder.split("/").map((name, i, all) => ({ name, path: all.slice(0, i + 1).join("/") })));

  async function loadListing(): Promise<void> {
    try {
      listing = await api.knowledge();
      rootInput = listing.root;
    } catch (e) {
      error = (e as Error).message;
    }
  }

  $effect(() => {
    void loadListing();
  });

  // the folder and note of the route
  $effect(() => {
    const [f, n] = [folder, note];
    if (!listing?.exists) return;
    error = null;
    api.browseKnowledge(f).then(
      (v) => (view = v),
      (e: Error) => (error = e.message),
    );
    if (n)
      api.knowledgeNote(n).then(
        (x) => (opened = x),
        (e: Error) => (error = e.message),
      );
    else opened = null;
  });

  async function saveRoot(root: string | null, create = false): Promise<void> {
    error = null;
    try {
      listing = await api.setKnowledgeRoot(root, create);
      rootInput = listing.root;
      editingRoot = false;
      navigate({ view: "knowledge" });
    } catch (e) {
      error = (e as Error).message;
    }
  }

  async function createFolder(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    const target = join(folder, newFolder.trim());
    error = null;
    try {
      listing = await api.createKnowledgeFolder(target);
      newFolder = "";
      navigate({ view: "knowledge", path: target });
    } catch (e) {
      error = (e as Error).message;
    }
  }

  // relative links between notes stay in this page
  function follow(event: MouseEvent): void {
    const anchor = (event.target as HTMLElement).closest("a");
    if (!anchor || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey) return;
    const target = resolveLink(folder, anchor.getAttribute("href") ?? "");
    if (!target) return;
    event.preventDefault();
    navigate("note" in target ? { view: "knowledge", note: target.note } : { view: "knowledge", path: target.folder });
  }

  function depth(f: string): number {
    return f.split("/").length - 1;
  }
</script>

<PageHeader titled title="Knowledge">
  {#snippet actions()}
    {#if listing?.exists}
      <Button variant="outline" size="sm" href={href({ view: "edit-project", knowledge: folder })} data-testid="use-knowledge">
        Use {folder === "." ? listing.root.split("/").at(-1) : folder.split("/").at(-1)} in a new project
      </Button>
    {/if}
  {/snippet}
</PageHeader>
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-6xl space-y-6 px-8 py-10">
    <PageTitle title="Knowledge" description="Folders of notes agents can be given to read, chosen in each agent's settings." />
    {#if error}<p class="text-sm text-danger" data-testid="knowledge-error">{error}</p>{/if}

    <Card.Root>
      <Card.Content class="space-y-2">
        <div class="flex flex-wrap items-center gap-2 text-sm">
          <span class="text-muted-foreground">Knowledge root</span>
          <code data-testid="knowledge-root">{listing?.root ?? "…"}</code>
          {#if listing?.source === "env"}
            <span class="text-xs text-muted-foreground">set by <code>HANDLER_KNOWLEDGE_DIR</code></span>
          {:else if listing}
            <span class="text-xs text-muted-foreground">{listing.source === "default" ? "default" : "set here"}</span>
            {#if !editingRoot}
              <Button variant="ghost" size="sm" onclick={() => (editingRoot = true)} data-testid="change-root">Change</Button>
            {/if}
          {/if}
        </div>
        {#if editingRoot}
          <form class="flex flex-wrap items-center gap-2" onsubmit={(e) => (e.preventDefault(), saveRoot(rootInput))}>
            <Input bind:value={rootInput} aria-label="knowledge root" class="max-w-md font-mono text-xs" placeholder="/home/you/knowledge" />
            <Button type="submit" size="sm">Save</Button>
            <Button type="button" variant="outline" size="sm" onclick={() => saveRoot(rootInput, true)}>Create and save</Button>
            {#if listing?.source === "config"}
              <Button type="button" variant="ghost" size="sm" onclick={() => saveRoot(null)}>Back to default</Button>
            {/if}
            <Button type="button" variant="ghost" size="sm" onclick={() => (editingRoot = false)}>Cancel</Button>
          </form>
        {/if}
        {#if listing && !listing.exists}
          <p class="text-sm text-muted-foreground">
            This folder does not exist yet.
            {#if listing.source !== "env"}
              <Button variant="link" size="sm" class="px-1" onclick={() => saveRoot(listing?.root ?? null, true)} data-testid="create-root">Create it</Button>
            {/if}
          </p>
        {/if}
        <p class="text-xs text-muted-foreground">
          Agents read the folders selected in their settings at <code>/knowledge/&lt;name&gt;</code>, read-only.
          A folder's summary is its <code>_index.md</code>; notes are edited in your editor or Obsidian.
        </p>
      </Card.Content>
    </Card.Root>

    {#if listing?.exists}
      <div class="grid gap-6 md:grid-cols-[16rem_1fr]">
        <nav class="space-y-3" aria-label="knowledge folders">
          <div class="space-y-0.5 text-sm">
            <a
              href={href({ view: "knowledge" })}
              class="flex items-center gap-1.5 rounded px-2 py-1 no-underline hover:bg-muted {folder === '.' && !note ? 'bg-muted font-medium' : ''}"
            ><BookOpen class="size-3.5" />{listing.root.split("/").at(-1)}</a>
            {#each listing.folders as f (f)}
              <a
                href={href({ view: "knowledge", path: f })}
                class="flex items-center gap-1.5 rounded px-2 py-1 no-underline hover:bg-muted {folder === f ? 'bg-muted font-medium' : ''}"
                style={`padding-left: ${0.5 + (depth(f) + 1) * 0.9}rem`}
                data-testid="knowledge-folder"
              ><Folder class="size-3.5 shrink-0" /><span class="truncate">{f.split("/").at(-1)}</span></a>
            {/each}
          </div>
          <form class="space-y-1.5" onsubmit={createFolder}>
            <Label for="new-folder" class="text-xs text-muted-foreground">New folder in {folder === "." ? "the root" : folder}</Label>
            <div class="flex gap-1.5">
              <Input id="new-folder" bind:value={newFolder} class="h-8 text-sm" placeholder="name" />
              <Button type="submit" size="sm" variant="outline" disabled={!newFolder.trim()} aria-label="create folder"><FolderPlus /></Button>
            </div>
          </form>
        </nav>

        <article class="min-w-0 space-y-4">
          <div class="flex flex-wrap items-center gap-1 text-sm text-muted-foreground">
            <a href={href({ view: "knowledge" })} class="hover:text-foreground">{listing.root.split("/").at(-1)}</a>
            {#each crumbs as c (c.path)}<span>/</span><a href={href({ view: "knowledge", path: c.path })} class="hover:text-foreground">{c.name}</a>{/each}
            {#if note}<span>/</span><span class="text-foreground">{note.split("/").at(-1)}</span>{/if}
          </div>

          {#if summary}
            <p class="rounded-md border bg-muted/40 px-3 py-2 text-sm" data-testid="knowledge-summary">{summary}</p>
          {/if}
          {#if shown}
            {#if shown.meta.length > 1 || (shown.meta.length === 1 && !summary)}
              <dl class="grid grid-cols-[auto_1fr] gap-x-3 text-xs text-muted-foreground">
                {#each shown.meta.filter(([k]) => k !== "summary") as [k, v] (k)}<dt>{k}</dt><dd class="font-mono">{v}</dd>{/each}
              </dl>
            {/if}
            <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
            <div class="md text-sm" data-testid="knowledge-content" onclick={follow}>{@html markdown(shown.body, { relativeLinks: true })}</div>
          {:else if view && !note}
            <p class="text-sm text-muted-foreground" data-testid="knowledge-no-index">
              No summary for this folder yet (no <code>_index.md</code>).
            </p>
          {/if}

          {#if view && !note}
            <div class="space-y-1 border-t pt-4 text-sm">
              {#each view.folders as name (name)}
                <a href={href({ view: "knowledge", path: join(view.path, name) })} class="flex items-center gap-1.5 hover:underline"><Folder class="size-3.5" />{name}/</a>
              {/each}
              {#each view.notes as name (name)}
                <a href={href({ view: "knowledge", note: join(view.path, name) })} class="flex items-center gap-1.5 hover:underline" data-testid="knowledge-note"><FileText class="size-3.5" />{name}</a>
              {/each}
              {#if !view.folders.length && !view.notes.length}<p class="text-muted-foreground">Empty folder.</p>{/if}
            </div>
          {/if}
        </article>
      </div>
    {/if}
  </div>
</div>
