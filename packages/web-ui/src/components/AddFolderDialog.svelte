<script lang="ts">
  // Add a work folder (D.13): an absolute path or `~/…`, kept as written, added to those there
  // are; never handler's own folders (the daemon refuses them, and says so). Settings → Folders'
  // own, and the one over any page (lib/workfolders, mounted once in App).
  import { untrack } from "svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import Dialog from "./Dialog.svelte";
  import { api } from "../lib/api";
  import type { WorkFolderInfo } from "../lib/contracts.gen";

  let { open = $bindable(false), onadded }: { open: boolean; onadded: (folders: WorkFolderInfo[]) => void } = $props();

  let next = $state("");
  let busy = $state(false);
  let error = $state<string | null>(null);

  const valid = (path: string) => path.startsWith("/") || path === "~" || path.startsWith("~/");

  // opened: a fresh form
  $effect(() => {
    if (open) untrack(() => ((next = ""), (error = null)));
  });

  async function add(): Promise<void> {
    const path = next.trim().replace(/(.)\/+$/, "$1");
    if (!path) return;
    if (!valid(path)) {
      error = "An absolute path, or one starting with ~/";
      return;
    }
    busy = true;
    error = null;
    try {
      const roots = (await api.folders()).folders.map((f) => f.root);
      onadded((await api.setFolders([...roots, path])).folders);
      open = false;
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

<Dialog bind:open title="Add a folder" description="Where your code lives: agents may then work in any project inside it." testid="work-folder-dialog">
  <form class="space-y-5" onsubmit={(e) => (e.preventDefault(), void add())}>
    <div class="space-y-1.5">
      <Label for="work-folder-input">Folder</Label>
      <Input id="work-folder-input" class="font-mono text-sm" placeholder="~/code or /srv/projects" bind:value={next} data-testid="work-folder-input" />
      <p class="text-xs text-muted-foreground">An absolute path, or one starting with <span class="font-mono">~/</span>. Never Handler's own folders.</p>
    </div>
    {#if error}<p class="text-danger" data-testid="work-folder-error">{error}</p>{/if}
    <div class="flex justify-end gap-2 border-t pt-4">
      <Button type="button" variant="ghost" size="sm" onclick={() => (open = false)}>Cancel</Button>
      <Button type="submit" size="sm" disabled={busy || !next.trim()} data-testid="work-folder-add">Add</Button>
    </div>
  </form>
</Dialog>
