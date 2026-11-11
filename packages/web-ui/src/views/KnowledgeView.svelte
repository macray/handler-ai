<script lang="ts">
  // Notes (D.5; in the files and the API, knowledge), the Library's Notes shelf: the notes root
  // (where it is, changed here unless HANDLER_NOTES_DIR sets it), its folders (browse, create)
  // and their notes, read-only. There is nothing to set up: the default root is made by handlerd.
  // A folder's _index.md, when there is one, is shown first: its summary, then its overview. Each
  // agent gets the folders selected in its settings (only there). The root is changed, and a
  // folder made, in a dialog; the root's is one path, its button saying what it will do
  // (Use this folder / Create this folder, from GET /v1/knowledge/check).
  import UsesPanel from "../components/UsesPanel.svelte";
  import BookOpen from "@lucide/svelte/icons/book-open";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import FileText from "@lucide/svelte/icons/file-text";
  import Folder from "@lucide/svelte/icons/folder";
  import FolderPlus from "@lucide/svelte/icons/folder-plus";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import Dialog from "../components/Dialog.svelte";
  import { LIBRARY_WIDTH } from "../lib/library";
  import { markdown } from "@handler/acp-view/lib/render";
  import { api } from "../lib/api";
  import type { KnowledgeFolderView, KnowledgeListing, KnowledgeNote, KnowledgeRootCheck } from "../lib/contracts.gen";
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
  let makingFolder = $state(false); // the "New folder" dialog open
  let rootCheck = $state<KnowledgeRootCheck | null>(null); // what the typed root is

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

  // what the typed root is, a moment after typing stops
  $effect(() => {
    const typed = rootInput.trim();
    rootCheck = null;
    if (!editingRoot || !typed) return;
    const timer = setTimeout(() => {
      api.checkKnowledgeRoot(typed).then(
        (c) => rootInput.trim() === typed && ((rootCheck = c), (error = null)),
        (e: Error) => rootInput.trim() === typed && (error = e.message),
      );
    }, 250);
    return () => clearTimeout(timer);
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
      makingFolder = false;
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

<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full {LIBRARY_WIDTH} space-y-6 px-8 py-6">
    {#if error && !editingRoot && !makingFolder}<p class="text-sm text-danger" data-testid="knowledge-error">{error}</p>{/if}

    <div class="flex items-center gap-4 rounded-[10px] border bg-card px-4 py-3.5 text-sm shadow-panel">
      <span class="hidden size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground sm:flex"><BookOpen class="size-4" /></span>
      <div class="min-w-0 flex-1 space-y-0.5">
        <p class="truncate font-mono text-[13px]" title={listing?.root} data-testid="knowledge-root">{listing?.root ?? "…"}</p>
        {#if listing}
          <p class="fact">
            {#if listing.source === "env"}where your notes are, set by HANDLER_NOTES_DIR{:else}where your notes are{listing.source === "default" ? ", the default place" : ", chosen here"}{/if}
            · {#if listing.exists}{listing.folders.length} folder{listing.folders.length === 1 ? "" : "s"} · agents get them in their settings, read only{:else}<span class="text-danger">this folder does not exist</span>{/if}
          </p>
        {/if}
      </div>
      {#if listing && listing.source !== "env"}
        <Button variant="outline" size="sm" onclick={() => ((editingRoot = true), (rootInput = listing?.root ?? ""), (error = null))} data-testid="change-root">Change</Button>
      {/if}
    </div>

    {#if listing?.exists}
      <div class="grid gap-6 md:grid-cols-[15rem_1fr]">
        <nav class="space-y-3" aria-label="notes folders">
          <div class="flex items-center justify-between px-2">
            <h2 class="section-label">folders</h2>
            <Button
              variant="ghost"
              size="icon-sm"
              class="text-muted-foreground hover:text-foreground"
              title={`New folder in ${folder === "." ? "the root" : folder}`}
              aria-label="new folder"
              onclick={() => ((makingFolder = true), (error = null))}
              data-testid="knowledge-new-folder"><FolderPlus /></Button
            >
          </div>
          <div class="space-y-0.5 text-sm">
            <a
              href={href({ view: "knowledge" })}
              class="flex items-center gap-2 rounded-lg px-2 py-1.5 text-foreground no-underline transition-colors hover:bg-muted {folder === '.' && !note
                ? 'bg-muted font-medium'
                : ''}"
            ><BookOpen class="size-4 shrink-0 text-muted-foreground" /><span class="truncate">{listing.root.split("/").at(-1)}</span></a>
            {#each listing.folders as f (f)}
              <a
                href={href({ view: "knowledge", path: f })}
                class="flex items-center gap-2 rounded-lg px-2 py-1.5 text-foreground no-underline transition-colors hover:bg-muted {folder === f ? 'bg-muted font-medium' : ''}"
                style={`padding-left: ${0.5 + (depth(f) + 1) * 0.9}rem`}
                data-testid="knowledge-folder"
              ><Folder class="size-4 shrink-0 text-muted-foreground" /><span class="truncate">{f.split("/").at(-1)}</span></a>
            {/each}
          </div>
        </nav>

        <article class="min-w-0 space-y-4">
          <div class="fact flex flex-wrap items-center gap-1">
            <a href={href({ view: "knowledge" })} class="text-muted-foreground no-underline hover:text-foreground">{listing.root.split("/").at(-1)}</a>
            {#each crumbs as c (c.path)}<ChevronRight class="size-3" /><a href={href({ view: "knowledge", path: c.path })} class="text-muted-foreground no-underline hover:text-foreground"
                >{c.name}</a
              >{/each}
            {#if note}<ChevronRight class="size-3" /><span class="text-foreground">{note.split("/").at(-1)}</span>{/if}
          </div>
          {#if !note}<UsesPanel kind="knowledge" id={folder} />{/if}

          {#if shown}
            <div class="space-y-4 rounded-[10px] border bg-card px-6 py-5 shadow-panel">
              {#if summary}
                <p class="rounded-lg bg-muted/60 px-3 py-2 text-sm" data-testid="knowledge-summary">{summary}</p>
              {/if}
              {#if shown.meta.length > 1 || (shown.meta.length === 1 && !summary)}
                <dl class="fact grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
                  {#each shown.meta.filter(([k]) => k !== "summary") as [k, v] (k)}<dt>{k}</dt><dd class="text-foreground">{v}</dd>{/each}
                </dl>
              {/if}
              <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
              <div class="md text-sm" data-testid="knowledge-content" onclick={follow}>{@html markdown(shown.body, { relativeLinks: true })}</div>
            </div>
          {:else if view && !note}
            <p class="rounded-[10px] border border-dashed px-4 py-3 text-sm text-muted-foreground" data-testid="knowledge-no-index">
              No summary for this folder yet: write one in its <span class="font-mono">_index.md</span>.
            </p>
          {/if}

          {#if view && !note}
            {#if view.folders.length || view.notes.length}
              <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
                {#each view.folders as name (name)}
                  <li>
                    <a href={href({ view: "knowledge", path: join(view.path, name) })} class="group flex items-center gap-3 px-4 py-2.5 text-foreground no-underline hover:bg-muted/40"
                      ><Folder class="size-4 shrink-0 text-muted-foreground" /><span class="flex-1 truncate">{name}</span><ChevronRight
                        class="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5"
                      /></a
                    >
                  </li>
                {/each}
                {#each view.notes as name (name)}
                  <li>
                    <a
                      href={href({ view: "knowledge", note: join(view.path, name) })}
                      class="group flex items-center gap-3 px-4 py-2.5 text-foreground no-underline hover:bg-muted/40"
                      data-testid="knowledge-note"
                      ><FileText class="size-4 shrink-0 text-muted-foreground" /><span class="flex-1 truncate">{name}</span><ChevronRight
                        class="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5"
                      /></a
                    >
                  </li>
                {/each}
              </ul>
            {:else}
              <p class="text-sm text-muted-foreground">This folder is empty.</p>
            {/if}
          {/if}
        </article>
      </div>
    {/if}
  </div>
</div>

<Dialog bind:open={editingRoot} title="Where your notes are" description="A folder on this computer: a full path, starting with / or ~/. Agents keep their folders by name." testid="knowledge-root-dialog">
  <form class="space-y-5" onsubmit={(e) => (e.preventDefault(), void saveRoot(rootInput, rootCheck?.state === "missing"))}>
    <div class="space-y-1.5">
      <Label for="knowledge-root-input">Folder</Label>
      <Input id="knowledge-root-input" bind:value={rootInput} class="font-mono text-sm" placeholder="~/notes" aria-invalid={!!error || rootCheck?.state === "not-a-folder"} />
      {#if error}<p class="text-xs text-danger" data-testid="knowledge-error">{error}</p>
      {:else if rootCheck?.state === "not-a-folder"}<p class="text-xs text-danger">{rootCheck.root} is a file, not a folder.</p>
      {:else if rootCheck?.state === "missing"}<p class="fact">New: Handler creates it.</p>{/if}
    </div>
    <div class="flex flex-wrap justify-end gap-2 border-t pt-4">
      {#if listing?.source === "config"}
        <Button type="button" variant="ghost" size="sm" class="mr-auto" onclick={() => saveRoot(null)}>Back to the default</Button>
      {/if}
      <Button type="button" variant="ghost" size="sm" onclick={() => (editingRoot = false)}>Cancel</Button>
      <Button type="submit" size="sm" disabled={!rootCheck || rootCheck.state === "not-a-folder"} data-testid="knowledge-save-root"
        >{rootCheck?.state === "missing" ? "Create this folder" : "Use this folder"}</Button
      >
    </div>
  </form>
</Dialog>

<Dialog
  bind:open={makingFolder}
  title="New folder"
  description={`In ${folder === "." ? "the notes root" : folder}. Agents can then be given it in their settings.`}
  testid="knowledge-folder-dialog"
>
  <form class="space-y-5" onsubmit={createFolder}>
    <div class="space-y-1.5">
      <Label for="new-folder">Name</Label>
      <Input id="new-folder" bind:value={newFolder} placeholder="name" />
    </div>
    {#if error}<p class="text-danger" data-testid="knowledge-error">{error}</p>{/if}
    <div class="flex justify-end gap-2 border-t pt-4">
      <Button type="button" variant="ghost" size="sm" onclick={() => (makingFolder = false)}>Cancel</Button>
      <Button type="submit" size="sm" disabled={!newFolder.trim()} aria-label="create folder" data-testid="knowledge-create-folder">Create</Button>
    </div>
  </form>
</Dialog>
