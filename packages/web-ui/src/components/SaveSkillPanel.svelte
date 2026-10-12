<script lang="ts">
  // A folderless agent's session's folder saved as a skill of the library (D.18), given to one
  // project's agents or to none yet (any agent may pick it). The library's rules apply (D.17); a skill of that name is replaced
  // only when asked.
  import { Button } from "$lib/components/ui/button";
  import { Label } from "$lib/components/ui/label";
  import * as NativeSelect from "$lib/components/ui/native-select";
  import { api, ApiError } from "../lib/api";
  import type { SkillInfo } from "../lib/contracts.gen";
  import { projects } from "../lib/projects.svelte";
  import { href } from "../lib/router.svelte";

  let { sessionId }: { sessionId: string } = $props();

  let project = $state("");
  let busy = $state(false);
  let error = $state<string | null>(null);
  let exists = $state<string | null>(null); // a skill of that name is in the library
  let saved = $state<SkillInfo | null>(null);

  async function save(replace = false): Promise<void> {
    busy = true;
    error = null;
    try {
      saved = await api.importSkillSession(sessionId, { project: project || null, replace });
      exists = null;
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.title === "skill exists") exists = e.detail ?? "";
      else error = (e as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

<section class="flex flex-col gap-4 text-sm" data-testid="save-skill-panel">
  <h3 class="text-xs font-medium tracking-wide text-muted-foreground uppercase">Save to library</h3>
  <p class="text-xs text-muted-foreground">The skill in this session's folder (its <code>SKILL.md</code>, the files next to it, no hidden ones) into your Skills.</p>
  <div class="space-y-1.5">
    <Label for="save-skill-project">Give it to</Label>
    <NativeSelect.Root id="save-skill-project" bind:value={project} class="w-full">
      <NativeSelect.Option value="">No agent yet (any agent may pick it)</NativeSelect.Option>
      {#each projects.list as p (p.id)}<NativeSelect.Option value={p.id}>All agents of {p.name}</NativeSelect.Option>{/each}
    </NativeSelect.Root>
  </div>
  <Button size="sm" disabled={busy} onclick={() => save()} data-testid="save-skill">Save</Button>
  {#if exists !== null}
    <div class="space-y-2 rounded-md border border-warn/40 bg-warn/5 p-3 text-xs">
      <p>The library has a skill {exists}: replace its files with this folder's? It keeps who gets it.</p>
      <Button size="sm" variant="destructive" disabled={busy} onclick={() => save(true)} data-testid="save-skill-replace">Replace</Button>
    </div>
  {/if}
  {#if saved}
    <p class="text-xs" data-testid="save-skill-done">Saved: <a class="text-link hover:underline" href={href({ view: "skill", name: saved.name })}>{saved.name}</a>.</p>
  {/if}
  {#if error}<p class="text-xs text-danger">{error}</p>{/if}
</section>
