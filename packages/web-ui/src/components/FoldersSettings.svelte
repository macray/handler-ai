<script lang="ts">
  // The work folders (D.13): where agents may work, owned by this computer. A project's folder,
  // or an ad-hoc session's, must be inside one. Absolute paths or `~/…`, kept as written; never
  // handler's own folders (the daemon refuses them, and says so). Each change is saved at once and
  // applies to new sessions; each folder says how many projects it holds (their names in its
  // tooltip), or that it is missing. One is added in a dialog.
  import FolderOpen from "@lucide/svelte/icons/folder-open";
  import Plus from "@lucide/svelte/icons/plus";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import Dialog from "./Dialog.svelte";
  import { api } from "../lib/api";
  import type { WorkFolderInfo } from "../lib/contracts.gen";

  let folders = $state<WorkFolderInfo[]>([]);
  let next = $state("");
  let adding = $state(false); // the dialog open
  let busy = $state(false);
  let error = $state<string | null>(null);

  const valid = (path: string) => path.startsWith("/") || path === "~" || path.startsWith("~/");

  api.folders().then(
    (f) => (folders = f.folders),
    (e: Error) => (error = e.message),
  );

  async function save(roots: string[]): Promise<boolean> {
    busy = true;
    error = null;
    try {
      folders = (await api.setFolders(roots)).folders;
      return true;
    } catch (e) {
      error = (e as Error).message;
      return false;
    } finally {
      busy = false;
    }
  }

  async function add(): Promise<void> {
    const path = next.trim().replace(/(.)\/+$/, "$1");
    if (!path) return;
    if (!valid(path)) {
      error = "An absolute path, or one starting with ~/";
      return;
    }
    if (await save([...folders.map((f) => f.root), path])) {
      next = "";
      adding = false;
    }
  }

  function remove(folder: WorkFolderInfo): void {
    const held = folder.projects?.length ? ` Its projects (${folder.projects.join(", ")}) can no longer start sessions.` : "";
    if (held && !confirm(`Remove ${folder.root}?${held}`)) return;
    void save(folders.filter((f) => f.root !== folder.root).map((f) => f.root));
  }
</script>

<section class="space-y-4" data-testid="folders">
  <div class="flex flex-wrap items-end justify-between gap-3">
    <p class="max-w-2xl text-sm text-muted-foreground">
      Agents only work inside these folders: a project's folder must be in one of them. Each change is saved at once; sessions already running keep
      their folder.
    </p>
    <Button variant="outline" size="sm" onclick={() => ((adding = true), (error = null))} data-testid="work-folder-new"><Plus />Add a folder</Button>
  </div>
  {#if error && !adding}<p class="text-sm text-danger" data-testid="work-folder-error">{error}</p>{/if}
  <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
    {#each folders as f (f.root)}
      <li class="flex items-center gap-4 px-4 py-3.5">
        <span class="hidden size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground sm:flex"><FolderOpen class="size-4" /></span>
        <div class="min-w-0 flex-1 space-y-0.5">
          <p class="truncate font-mono text-[13px]" title={f.path} data-testid="work-folder">{f.root}</p>
          {#if !f.exists}
            <p class="inline-flex items-center gap-1 rounded-md bg-warn/10 px-1.5 py-0.5 text-xs text-warn" data-testid="work-folder-state">
              <TriangleAlert class="size-3" />does not exist on this computer
            </p>
          {:else}
            <p class="fact" title={f.projects?.join(", ")} data-testid="work-folder-state">
              {f.projects?.length ? `${f.projects.length} project${f.projects.length === 1 ? "" : "s"}` : "no project in it yet"}
            </p>
          {/if}
        </div>
        <Button
          variant="ghost"
          size="sm"
          class="text-muted-foreground hover:text-destructive"
          disabled={busy || folders.length === 1}
          title={folders.length === 1 ? "Agents need at least one folder" : undefined}
          aria-label={`Remove ${f.root}`}
          onclick={() => remove(f)}>Remove</Button
        >
      </li>
    {/each}
  </ul>

  <Dialog bind:open={adding} title="Add a folder" description="Where your code lives: agents may then work in any project inside it." testid="work-folder-dialog">
    <form class="space-y-5" onsubmit={(e) => (e.preventDefault(), void add())}>
      <div class="space-y-1.5">
        <Label for="work-folder-input">Folder</Label>
        <Input id="work-folder-input" class="font-mono text-sm" placeholder="~/code or /srv/projects" bind:value={next} data-testid="work-folder-input" />
        <p class="text-xs text-muted-foreground">An absolute path, or one starting with <span class="font-mono">~/</span>. Never Handler's own folders.</p>
      </div>
      {#if error}<p class="text-danger" data-testid="work-folder-error">{error}</p>{/if}
      <div class="flex justify-end gap-2 border-t pt-4">
        <Button type="button" variant="ghost" size="sm" onclick={() => (adding = false)}>Cancel</Button>
        <Button type="submit" size="sm" disabled={busy || !next.trim()} data-testid="work-folder-add">Add</Button>
      </div>
    </form>
  </Dialog>
</section>
