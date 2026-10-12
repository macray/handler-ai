<script lang="ts">
  // The side pane of a session's page showing its folder (F.8): what changed since the session
  // started, every file, and one file at a time (its changes when an earlier version is known);
  // what else of the computer its sandbox sees, the readable ones browsed like its folder.
  import ArrowLeft from "@lucide/svelte/icons/arrow-left";
  import BookOpen from "@lucide/svelte/icons/book-open";
  import Box from "@lucide/svelte/icons/box";
  import Database from "@lucide/svelte/icons/database";
  import FileSearch from "@lucide/svelte/icons/file-search";
  import FolderSearch from "@lucide/svelte/icons/folder-search";
  import Package from "@lucide/svelte/icons/package";
  import Settings from "@lucide/svelte/icons/settings";
  import Sparkles from "@lucide/svelte/icons/sparkles";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import Copy from "@lucide/svelte/icons/copy";
  import FileIcon from "@lucide/svelte/icons/file";
  import Folder from "@lucide/svelte/icons/folder";
  import Link from "@lucide/svelte/icons/link";
  import X from "@lucide/svelte/icons/x";
  import { diffLines } from "diff";
  import { Button } from "$lib/components/ui/button";
  import { api } from "../lib/api";
  import type { SessionChanges, SessionFile, SessionFileChange, SessionFolder, SessionMount, SessionMounts } from "../lib/contracts.gen";
  import When from "./When.svelte";

  let {
    sessionId,
    folder: root,
    changes,
    onclose,
  }: { sessionId: string; folder: string; changes: SessionChanges | null; onclose: () => void } = $props();

  type Change = SessionFileChange["change"];
  const CHANGE: Record<Change, { label: string; tone: string }> = {
    added: { label: "New", tone: "bg-ok/10 text-ok" },
    modified: { label: "Changed", tone: "bg-warn/10 text-warn" },
    deleted: { label: "Deleted", tone: "bg-danger/10 text-danger" },
  };

  // what the agent sees, in plain words (contracts F.8), in this order
  const MOUNT: Record<SessionMount["kind"], { label: string; icon: typeof Folder }> = {
    scope: { label: "This session's folder", icon: Folder },
    subject: { label: "What this run works on", icon: FileSearch },
    knowledge: { label: "Knowledge folder", icon: BookOpen },
    config: { label: "Skill", icon: Sparkles },
    state: { label: "The agent's own settings and history", icon: Settings },
    cache: { label: "Cache kept between sessions", icon: Database },
    tools: { label: "Addon tools", icon: Package },
    app: { label: "Mini app", icon: Box },
  };

  let tab = $state<"changes" | "all" | "access">("changes");
  let mounts = $state<SessionMounts | null>(null);
  let mountsError = $state<string | null>(null);
  let mount = $state<SessionMount | null>(null); // browsed in "All files"; null: the session's folder
  let at = $state(""); // the folder shown in "All files", relative to the mount
  let listing = $state<SessionFolder | null>(null);
  let listingError = $state<string | null>(null);
  let open = $state<string | null>(null); // the file shown, relative to the session's folder
  let file = $state<SessionFile | null>(null);
  let fileError = $state<string | null>(null);
  let copied = $state(false);
  let revealError = $state<string | null>(null);

  const ORDER = Object.keys(MOUNT);
  const sorted = $derived(
    [...(mounts?.mounts ?? [])].sort((a, b) => ORDER.indexOf(a.kind) - ORDER.indexOf(b.kind) || a.target.localeCompare(b.target)),
  );
  const files = $derived(changes?.files ?? []);
  const reading = $derived(tab === "all" ? mount : null); // where the open file is
  // changes are its folder's: not marked elsewhere
  const changed = $derived(new Map(reading ? [] : files.map((c) => [c.path, c])));
  const crumbs = $derived(at ? at.split("/") : []);
  // the open file's last change: shown again when it changes
  const openVersion = $derived(open ? `${changed.get(open)?.change}:${changed.get(open)?.at}` : "");

  $effect(() => {
    if (tab !== "all" || open) return;
    void changes; // refreshed with the changes
    const path = at;
    api
      .sessionFolder(sessionId, path, mount?.target)
      .then((found) => {
        listing = found;
        listingError = null;
      })
      .catch((e: Error) => (listingError = e.message));
  });

  $effect(() => {
    const path = open;
    void openVersion;
    if (!path) return;
    api
      .sessionFile(sessionId, path, reading?.target)
      .then((found) => {
        if (open !== path) return;
        file = found;
        fileError = null;
      })
      .catch((e: Error) => (fileError = e.message));
  });

  $effect(() => {
    if (tab !== "access") return;
    api
      .sessionMounts(sessionId)
      .then((found) => {
        mounts = found;
        mountsError = null;
      })
      .catch((e: Error) => (mountsError = e.message));
  });

  /** Browse a mount (null: the session's folder) in "All files". */
  function browse(m: SessionMount | null): void {
    mount = m?.kind === "scope" ? null : m;
    at = "";
    listing = null;
    tab = "all";
    back();
  }

  function show(path: string): void {
    file = null;
    fileError = null;
    open = path;
  }

  function back(): void {
    revealError = null;
    open = null;
    file = null;
  }

  function folderOf(path: string): string {
    const slash = path.lastIndexOf("/");
    return slash < 0 ? "" : path.slice(0, slash + 1);
  }

  function nameOf(path: string): string {
    return path.slice(path.lastIndexOf("/") + 1);
  }

  function size(bytes: number | null | undefined): string {
    if (bytes == null) return "";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  }

  /** Shown in the computer's file manager (selected in its folder, not opened). */
  async function reveal(path: string, where: SessionMount | null): Promise<void> {
    revealError = null;
    try {
      await api.revealSessionPath(sessionId, path, where?.target);
    } catch (e) {
      revealError = (e as Error).message;
    }
  }

  async function copyPath(path: string): Promise<void> {
    await navigator.clipboard.writeText(`${reading?.source ?? root}/${path}`);
    copied = true;
    setTimeout(() => (copied = false), 1500);
  }
</script>

{#snippet access(readOnly: boolean)}
  <span class="shrink-0 rounded px-1.5 py-px text-[0.7rem] font-medium {readOnly ? 'bg-muted text-muted-foreground' : 'bg-warn/10 text-warn'}"
    >{readOnly ? "read-only" : "can change"}</span
  >
{/snippet}

{#snippet chip(change: Change)}
  <span class="shrink-0 rounded px-1.5 py-px text-[0.7rem] font-medium {CHANGE[change].tone}">{CHANGE[change].label}</span>
{/snippet}

<div class="flex h-full min-h-0 flex-col text-sm" data-testid="session-files">
  <header class="flex items-center gap-1 border-b px-2 py-1.5">
    <div class="flex gap-1" role="tablist">
      <Button
        variant={tab === "changes" ? "secondary" : "ghost"}
        size="sm"
        role="tab"
        aria-selected={tab === "changes"}
        onclick={() => ((tab = "changes"), back())}
        data-testid="files-tab-changes"
      >
        Changes{#if files.length}<span class="text-muted-foreground tabular-nums">{files.length}</span>{/if}
      </Button>
      <Button
        variant={tab === "all" ? "secondary" : "ghost"}
        size="sm"
        role="tab"
        aria-selected={tab === "all"}
        onclick={() => ((tab = "all"), back())}
        data-testid="files-tab-all"
      >
        All files
      </Button>
      <Button
        variant={tab === "access" ? "secondary" : "ghost"}
        size="sm"
        role="tab"
        aria-selected={tab === "access"}
        onclick={() => ((tab = "access"), back())}
        title="What the agent sees of your computer"
        data-testid="files-tab-access"
      >
        Access
      </Button>
    </div>
    <Button variant="ghost" size="icon-sm" class="ml-auto" onclick={onclose} title="Close" aria-label="Close the files">
      <X />
    </Button>
  </header>

  <div class="min-h-0 flex-1 overflow-y-auto">
    {#if open}
      <div class="space-y-3 p-3" data-testid="file-view">
        <div class="flex items-center gap-2">
          <Button variant="ghost" size="icon-sm" onclick={back} title={tab === "changes" ? "Back to the changes" : "Back to the folder"} aria-label="Back">
            <ArrowLeft />
          </Button>
          <span class="min-w-0 flex-1 truncate font-mono text-xs" title={open}>
            <span class="text-muted-foreground">{reading ? `${reading.target}/` : ""}{folderOf(open)}</span><span class="font-medium">{nameOf(open)}</span>
          </span>
          {#if file?.change}{@render chip(file.change)}{/if}
          {#if file?.change !== "deleted"}
            <Button
              variant="ghost"
              size="icon-sm"
              onclick={() => open && reveal(open, reading)}
              title="Show it in your file manager"
              aria-label="Show it in your file manager"
              data-testid="reveal-file"
            >
              <FolderSearch />
            </Button>
          {/if}
          <Button variant="ghost" size="icon-sm" onclick={() => open && copyPath(open)} title={copied ? "Copied" : "Copy its full path"} aria-label="Copy its full path">
            <Copy />
          </Button>
        </div>
        {#if revealError}<p class="text-xs text-danger">{revealError}</p>{/if}
        {#if fileError}
          <p class="text-danger">{fileError}</p>
        {:else if !file}
          <p class="text-muted-foreground">Loading…</p>
        {:else}
          {#if file.change === "deleted"}
            <p class="text-muted-foreground">Deleted during this session{file.before == null ? "." : ". What it held:"}</p>
          {:else if file.change === "modified" && file.before == null && file.text != null}
            <p class="text-xs text-muted-foreground">
              Changed during this session. Its earlier version is not known ({changes?.git
                ? "it was not committed when the session started"
                : "this folder is not a git repository"}): here it is as it is now.
            </p>
          {/if}
          {#if file.before != null}
            <pre class="code" data-testid="file-diff">{#each diffLines(file.before, file.text ?? "") as part, i (i)}<span
                  class:add={part.added}
                  class:del={part.removed}>{part.value}</span
                >{/each}</pre>
          {:else if file.text != null}
            <pre class="code">{file.text}</pre>
          {:else if file.image}
            <img src={file.image} alt={open} class="max-w-full rounded border" />
          {:else if file.change !== "deleted"}
            <p class="text-muted-foreground">This file cannot be shown here: it is not text, or larger than 1 MB ({size(file.size)}).</p>
          {/if}
        {/if}
      </div>
    {:else if tab === "changes"}
      {#if !changes}
        <p class="p-3 text-muted-foreground">Loading…</p>
      {:else if changes.notFollowed}
        <p class="p-3 text-muted-foreground">Changes are not followed for this session: {changes.notFollowed}. Its files are in All files.</p>
      {:else if !files.length}
        <p class="p-3 text-muted-foreground">Nothing changed yet. Files the agent creates, changes or deletes appear here.</p>
      {:else}
        <ul class="py-1" data-testid="changes-list">
          {#each files as c (c.path)}
            <li>
              <button class="row" onclick={() => show(c.path)} title={c.path}>
                {@render chip(c.change)}
                <span class="min-w-0 flex-1 truncate font-mono text-xs">
                  <span class="text-muted-foreground">{folderOf(c.path)}</span>{nameOf(c.path)}
                </span>
                {#if c.at}<span class="shrink-0 text-xs text-muted-foreground"><When at={c.at} /></span>{/if}
              </button>
            </li>
          {/each}
        </ul>
      {/if}
      {#if changes && !changes.notFollowed}
        <p class="border-t px-3 py-2 text-xs text-muted-foreground">
          Since the session started <When at={changes.since} />{changes.git ? ", compared with the last commit then" : ""}. Files ignored by
          .gitignore are left out.
        </p>
      {/if}
    {:else if tab === "all"}
      {#if mount}
        <div class="flex items-center gap-2 border-b px-3 py-1.5 text-xs text-muted-foreground" data-testid="browsing-mount">
          <span class="min-w-0 flex-1 truncate">{MOUNT[mount.kind].label} · the agent reads it, cannot change it</span>
          <button class="text-link hover:underline" onclick={() => browse(null)}>Session's folder</button>
        </div>
      {/if}
      <nav class="flex flex-wrap items-center gap-0.5 px-3 pt-2.5 pb-1 font-mono text-xs" aria-label="Folder">
        <button class="crumb" onclick={() => (at = "")} title={mount ? `${mount.target} (on your computer: ${mount.source})` : root}
          >{mount ? mount.target : nameOf(root)}</button
        >
        {#each crumbs as name, i (i)}
          <ChevronRight class="size-3 text-muted-foreground" />
          <button class="crumb" onclick={() => (at = crumbs.slice(0, i + 1).join("/"))}>{name}</button>
        {/each}
        <Button
          variant="ghost"
          size="icon-sm"
          class="ml-auto"
          onclick={() => reveal(at, mount)}
          title="Show this folder in your file manager"
          aria-label="Show this folder in your file manager"
          data-testid="reveal-folder"
        >
          <FolderSearch />
        </Button>
      </nav>
      {#if revealError}<p class="px-3 text-xs text-danger">{revealError}</p>{/if}
      {#if listingError}
        <p class="p-3 text-danger">{listingError}</p>
      {:else if listing && !listing.entries.length}
        <p class="p-3 text-muted-foreground">This folder is empty.</p>
      {:else if listing}
        <ul class="py-1" data-testid="folder-list">
          {#each listing.entries as entry (entry.name)}
            {@const path = at ? `${at}/${entry.name}` : entry.name}
            <li>
              {#if entry.kind === "folder"}
                <button class="row" onclick={() => (at = path)}>
                  <Folder class="size-4 shrink-0 text-muted-foreground" />
                  <span class="min-w-0 flex-1 truncate">{entry.name}</span>
                </button>
              {:else if entry.kind === "file"}
                <button class="row" onclick={() => show(path)}>
                  <FileIcon class="size-4 shrink-0 text-muted-foreground" />
                  <span class="min-w-0 flex-1 truncate">{entry.name}</span>
                  {#if changed.get(path)}{@render chip(changed.get(path)!.change)}{/if}
                  <span class="shrink-0 text-xs text-muted-foreground tabular-nums">{size(entry.size)}</span>
                </button>
              {:else}
                <div class="row cursor-default" title="A link: not opened here">
                  <Link class="size-4 shrink-0 text-muted-foreground" />
                  <span class="min-w-0 flex-1 truncate">{entry.name} <span class="text-muted-foreground">→ {entry.target}</span></span>
                </div>
              {/if}
            </li>
          {/each}
        </ul>
      {/if}
    {:else}
      <p class="px-3 pt-3 text-xs text-muted-foreground">
        What the agent sees of your computer{#if mounts?.startedAt}, as of its last start (<When at={mounts.startedAt} />){/if}. The rest of its sandbox (its
        programs) comes from its image.
      </p>
      {#if mountsError}
        <p class="p-3 text-danger">{mountsError}</p>
      {:else if !mounts}
        <p class="p-3 text-muted-foreground">Loading…</p>
      {:else}
        {#if !mounts.startedAt}<p class="px-3 pt-2 text-xs text-muted-foreground">It has not started yet: only its folder is known.</p>{/if}
        <ul class="py-2" data-testid="mounts-list">
          {#each sorted as m (m.target)}
            {@const Icon = MOUNT[m.kind].icon}
            <li>
              {#if m.browsable}
                <button class="row items-start" onclick={() => browse(m)} title="Show its files">
                  <Icon class="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                  <span class="min-w-0 flex-1 space-y-0.5">
                    <span class="flex items-center gap-2">
                      <span class="font-medium">{MOUNT[m.kind].label}</span>
                      {@render access(m.readOnly)}
                    </span>
                    <span class="block truncate font-mono text-xs" title={m.target}>{m.target}</span>
                    {#if m.source !== m.target}
                      <span class="block truncate text-xs text-muted-foreground" title={m.source}>on your computer: {m.source}</span>
                    {/if}
                  </span>
                  <ChevronRight class="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                </button>
              {:else}
                <div class="row cursor-default text-muted-foreground" title={`${m.kind === "tools" ? "image" : "on your computer"}: ${m.source}`}>
                  <Icon class="size-4 shrink-0" />
                  <span class="shrink-0">{MOUNT[m.kind].label}</span>
                  <span class="min-w-0 flex-1 truncate font-mono text-xs">{m.target}</span>
                  {@render access(m.readOnly)}
                </div>
              {/if}
            </li>
          {/each}
        </ul>
        {#if mounts.mounts.some((m) => !m.browsable)}
          <p class="border-t px-3 py-2 text-xs text-muted-foreground">
            Not shown here: the agent's own settings and history (they hold your account's sign-in), caches and addon tools. Hover one to
            see where it is.
          </p>
        {/if}
      {/if}
    {/if}
  </div>
</div>

<style>
  .row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    width: 100%;
    padding: 0.3rem 0.75rem;
    text-align: left;
  }
  button.row:hover {
    background: var(--muted);
  }
  .crumb {
    padding: 0.05rem 0.25rem;
    border-radius: 0.25rem;
  }
  .crumb:hover {
    background: var(--muted);
  }
  .code {
    font-family: var(--mono);
    font-size: 0.78rem;
    line-height: 1.5;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    padding: 0.5rem 0.75rem;
    border: 1px solid var(--border);
    border-radius: 0.375rem;
    background: var(--code-bg);
  }
  .add {
    display: block;
    background: var(--diff-add);
  }
  .del {
    display: block;
    background: var(--diff-del);
    text-decoration: line-through;
    opacity: 0.8;
  }
</style>
