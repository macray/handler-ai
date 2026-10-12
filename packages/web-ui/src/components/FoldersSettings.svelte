<script lang="ts">
  // The work folders (D.13): where agents may work, owned by this computer. A project's folder,
  // or an ad-hoc session's, must be inside one. Absolute paths or `~/…`, kept as written; never
  // handler's own folders (the daemon refuses them, and says so). Each change is saved at once and
  // applies to new sessions; each folder says which projects it holds, or that it is missing.
  import X from "@lucide/svelte/icons/x";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { api } from "../lib/api";
  import type { WorkFolderInfo } from "../lib/contracts.gen";

  let folders = $state<WorkFolderInfo[]>([]);
  let next = $state("");
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
    if (await save([...folders.map((f) => f.root), path])) next = "";
  }

  function remove(folder: WorkFolderInfo): void {
    const held = folder.projects?.length ? ` Its projects (${folder.projects.join(", ")}) can no longer start sessions.` : "";
    if (held && !confirm(`Remove ${folder.root}?${held}`)) return;
    void save(folders.filter((f) => f.root !== folder.root).map((f) => f.root));
  }
</script>

<section class="space-y-4" data-testid="folders">
  <p class="max-w-2xl text-sm text-muted-foreground">
    Agents only work inside these folders: a project's folder must be in one of them. Add the folders where your code lives.
  </p>
  <div class="max-w-2xl space-y-3">
    <ul class="divide-y rounded-lg border bg-card text-sm">
      {#each folders as f (f.root)}
        <li class="flex items-center justify-between gap-3 px-3.5 py-2.5">
          <div class="min-w-0">
            <div class="truncate font-mono text-xs" title={f.path} data-testid="work-folder">{f.root}</div>
            <div class="truncate text-xs {f.exists ? 'text-muted-foreground' : 'text-warn'}" data-testid="work-folder-state">
              {#if !f.exists}does not exist on this computer{:else if f.projects?.length}{f.projects.length} project{f.projects.length === 1 ? "" : "s"}: {f.projects.join(", ")}{:else}no project in it yet{/if}
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon-sm"
            disabled={busy || folders.length === 1}
            title={folders.length === 1 ? "Agents need at least one folder" : undefined}
            aria-label={`Remove ${f.root}`}
            onclick={() => remove(f)}><X /></Button
          >
        </li>
      {/each}
    </ul>
    <form class="flex gap-2" onsubmit={(e) => (e.preventDefault(), void add())}>
      <Input class="h-8 font-mono text-xs" placeholder="~/code or /srv/projects" bind:value={next} data-testid="work-folder-input" />
      <Button type="submit" variant="outline" size="sm" disabled={busy || !next.trim()} data-testid="work-folder-add">Add</Button>
    </form>
    {#if error}<p class="text-sm text-danger" data-testid="work-folder-error">{error}</p>{/if}
    <p class="text-xs text-muted-foreground">Each change is saved at once; sessions already running keep their folder.</p>
  </div>
</section>
