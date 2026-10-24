<script lang="ts">
  // The user's toolbox Containerfile (contract B.6): edited here, used by the next toolbox rebuild,
  // which checks every harness and addon image on top of it before any switches (D.4).
  import { Button } from "$lib/components/ui/button";
  import { Textarea } from "$lib/components/ui/textarea";
  import { api } from "../lib/api";
  import { href } from "../lib/router.svelte";

  let { directory, onclose, onsaved }: { directory: string; onclose: () => void; onsaved: () => void } = $props();

  let text = $state("");
  let saved = $state(""); // what the file holds
  let defaultText = $state("");
  let loaded = $state(false);
  let busy = $state(false);
  let error = $state<string | null>(null);

  const dirty = $derived(text !== saved);

  $effect(() => {
    api.toolboxContainerfile().then(
      (file) => {
        text = saved = file.content;
        defaultText = file.defaultContent;
        loaded = true;
      },
      (e: Error) => (error = e.message),
    );
  });

  async function save(): Promise<void> {
    busy = true;
    error = null;
    try {
      const file = await api.saveToolboxContainerfile(text);
      text = saved = file.content;
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

  function restoreDefault(): void {
    if (text === defaultText || confirm("Replace the text with Handler's default Containerfile? Nothing is saved until you save.")) {
      text = defaultText;
    }
  }
</script>

<div class="enter space-y-3 rounded-[10px] border bg-card p-4 shadow-panel" data-testid="toolbox-editor">
  <div class="text-sm">
    <span class="font-medium">Toolbox Containerfile</span>
    <span class="ml-2 font-mono text-xs text-muted-foreground">{directory}/Containerfile</span>
  </div>
  {#if loaded}
    <Textarea bind:value={text} rows={22} class="font-mono text-xs" spellcheck={false} data-testid="toolbox-content" />
    <p class="text-xs text-muted-foreground">
      The tools every agent gets. Saving rebuilds nothing: <span class="font-medium">Rebuild everything</span> builds it,
      then every harness and tool image on top of it, and switches them only if all pass their checks.
      What toolchains keep between sessions is in <a class="underline underline-offset-2" href={href({ view: "settings", section: "caches" })}>Settings → Caches</a>.
    </p>
  {/if}
  <div class="flex flex-wrap items-center gap-2">
    <Button size="sm" disabled={busy || !loaded || !dirty} onclick={save} data-testid="toolbox-save">Save</Button>
    <Button variant="outline" size="sm" disabled={busy || !loaded || text === defaultText} onclick={restoreDefault} data-testid="toolbox-default">
      Restore the default
    </Button>
    <Button type="button" variant="ghost" size="sm" onclick={close}>Close</Button>
    {#if dirty}<span class="text-xs text-muted-foreground">not saved</span>{/if}
  </div>
  {#if error}<p class="text-sm text-danger" data-testid="toolbox-error">{error}</p>{/if}
</div>
