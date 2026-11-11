<script lang="ts">
  // The user's own lines of the toolbox (custom.containerfile, contract B.7), appended last to
  // the recipe Handler generates: edited here, used by the next toolbox build, which checks every
  // harness and addon image on top of it before any switches (D.4).
  import { Button } from "$lib/components/ui/button";
  import { Textarea } from "$lib/components/ui/textarea";
  import { api } from "../lib/api";
  import { href } from "../lib/router.svelte";

  let { directory, onclose, onsaved }: { directory: string; onclose: () => void; onsaved: () => void } = $props();

  let text = $state("");
  let saved = $state(""); // what the file holds
  let loaded = $state(false);
  let busy = $state(false);
  let error = $state<string | null>(null);

  const dirty = $derived(text !== saved);

  $effect(() => {
    api.toolboxLines().then(
      (lines) => {
        text = saved = lines.content;
        loaded = true;
      },
      (e: Error) => (error = e.message),
    );
  });

  async function save(): Promise<void> {
    busy = true;
    error = null;
    try {
      const lines = await api.saveToolboxLines(text);
      text = saved = lines.content;
      onsaved();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  function close(): void {
    if (!dirty || confirm("Close without saving your changes?")) onclose();
  }
</script>

<div class="enter space-y-3 rounded-[10px] border bg-card p-4 shadow-panel" data-testid="toolbox-editor">
  <div class="text-sm">
    <span class="font-medium">Your lines</span>
    <span class="ml-2 font-mono text-xs text-muted-foreground">{directory}/custom.containerfile</span>
  </div>
  {#if loaded}
    <Textarea bind:value={text} rows={12} class="font-mono text-xs" spellcheck={false} placeholder="RUN dnf -y install …" data-testid="toolbox-content" />
    <p class="text-xs text-muted-foreground">
      Containerfile lines added last to the toolbox, run as root: every agent gets what they install. Saving rebuilds nothing:
      <span class="font-medium">Apply</span> builds the toolbox, then every agent program and tool image already built on top of it, and switches them only if all
      pass their checks. What tools keep between sessions is in
      <a class="underline underline-offset-2" href={href({ view: "settings", section: "caches" })}>Settings → Caches</a>.
    </p>
  {/if}
  <div class="flex flex-wrap items-center gap-2">
    <Button size="sm" disabled={busy || !loaded || !dirty} onclick={save} data-testid="toolbox-save">Save</Button>
    <Button type="button" variant="ghost" size="sm" onclick={close}>Close</Button>
    {#if dirty}<span class="text-xs text-muted-foreground">not saved</span>{/if}
  </div>
  {#if error}<p class="text-sm text-danger" data-testid="toolbox-error">{error}</p>{/if}
</div>
