<script lang="ts">
  // One change of a folder others write (D.5), as a row of its history or of an app's Activity:
  // who could write then, when, its first files and what changed in them ("added 2 lines under
  // Platform"); the whole row a button opening its files' lines, the raw diff folded, and "Undo
  // this change" (a dialog says what is put back). `where`: the folder's name, said after who
  // ("changed Your work experience", in an app's Activity, where several folders mix); `clock`:
  // its time of day (a timeline headed by days) instead of "12 min ago".
  import Undo2 from "@lucide/svelte/icons/undo-2";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import { Button } from "$lib/components/ui/button";
  import Dialog from "./Dialog.svelte";
  import { api } from "../lib/api";
  import type { NotesCommit, NotesCommitDiff, NotesFileChange } from "../lib/contracts.gen";
  import { ago, clockTime, exactTime } from "../lib/agents";
  import { changeTitle, diffLines, fileChange } from "../lib/knowledge";

  let {
    folder,
    commit: c,
    where,
    clock = false,
    ondone,
  }: {
    folder: string;
    commit: NotesCommit;
    where?: string;
    clock?: boolean;
    ondone: (told: string) => void; // undone: what to tell, the history to read again
  } = $props();

  const SAID = 3; // files said on a closed entry, lines boxes open on an opened one

  let opened = $state<NotesCommitDiff | null>(null);
  let asking = $state(false); // the Undo dialog open
  let error = $state<string | null>(null);
  let busy = $state(false);
  const wasUndo = $derived(c.kind === "undo");
  const when = $derived(clock ? clockTime(c.at) : ago(c.at));

  async function toggle(): Promise<void> {
    if (opened) {
      opened = null;
      return;
    }
    try {
      opened = await api.notesChange(folder, c.id);
    } catch (e) {
      error = (e as Error).message;
    }
  }

  async function undo(): Promise<void> {
    busy = true;
    error = null;
    try {
      const done = await api.undoNotesChange(folder, c.id);
      const skipped = done.skipped ?? [];
      const n = skipped.length;
      asking = false;
      opened = null;
      ondone(
        done.commit
          ? `Put back as before. To undo this, open the newest change.${n ? ` ${n} file${n === 1 ? "" : "s"} left as ${n === 1 ? "it is" : "they are"}, a link on the way: ${skipped.join(", ")}` : ""}`
          : "The files were already as before this change.",
      );
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

{#snippet fileLine(f: NotesFileChange)}
  {@const said = fileChange(f, wasUndo)}
  <span class="min-w-0 truncate font-mono text-xs" title={f.path}>{f.path}</span>
  <span class="min-w-0 text-[13px] text-muted-foreground">{said.says}{#if said.under}{" under "}<b class="font-medium text-foreground">{said.under}</b>{/if}</span>
{/snippet}

{#snippet lines(shown: ReturnType<typeof diffLines>)}
  <div class="mt-1.5 overflow-x-auto rounded-md border bg-card py-1 font-mono text-xs leading-5" data-testid="notes-change-lines">
    {#each shown as l, i (i)}
      <div class="flex min-h-5 whitespace-pre {l.kind === 'add' ? 'bg-ok/10 text-foreground' : l.kind === 'del' ? 'bg-danger/10 text-foreground' : 'text-muted-foreground'}">
        <span class="w-6 shrink-0 select-none text-center {l.kind === 'add' ? 'text-ok' : l.kind === 'del' ? 'text-danger' : ''}" aria-hidden={l.kind === "same" || l.kind === "gap"}>{l.sign}</span><span class="pr-2">{l.text}</span>
      </div>
    {/each}
  </div>
{/snippet}

<div class={opened ? "bg-muted/40" : ""} data-testid="notes-change">
  {#if c.kind === "first"}
    <p class="px-4 py-2.5 pl-10 text-[13px] text-muted-foreground">{changeTitle(c)} · <span title={exactTime(c.at)}>{when}</span></p>
  {:else}
    <button
      type="button"
      class="group flex w-full cursor-pointer items-start gap-2 px-4 py-2.5 text-left hover:bg-muted/40 focus-visible:outline-2 focus-visible:outline-ring"
      aria-expanded={!!opened}
      aria-label={`${changeTitle(c)}, ${when}, ${opened ? "hide" : "show"} its lines`}
      onclick={toggle}
      data-testid="notes-change-toggle"
    >
      <ChevronRight class="mt-0.5 size-4 shrink-0 text-muted-foreground transition-transform group-hover:text-foreground {opened ? 'rotate-90 text-foreground' : ''}" />
      <span class="min-w-0 flex-1 space-y-1">
        <span class="block truncate"
          ><span class="font-medium">{changeTitle(c)}</span>
          <span class="text-muted-foreground">{#if where}· changed {where}{" "}{/if}· <span title={exactTime(c.at)}>{when}</span></span></span
        >
        {#if !opened}
          <span class="grid grid-cols-[minmax(0,max-content)_1fr] gap-x-6 gap-y-0.5" data-testid="notes-change-said">
            {#each c.files.slice(0, SAID) as f (f.path)}{@render fileLine(f)}{/each}
          </span>
          {#if c.fileCount > SAID}<span class="block text-xs text-muted-foreground">and {c.fileCount - SAID} more files</span>{/if}
        {/if}
      </span>
    </button>
  {/if}
  {#if error}<p class="px-4 pb-2 pl-10 text-sm text-danger" data-testid="notes-history-error">{error}</p>{/if}
  {#if opened}
    <div class="space-y-3 px-4 pt-1 pb-3 pl-10" data-testid="notes-change-files">
      {#each opened.files as f, i (f.path)}
        {@const shown = f.diff ? diffLines(f.diff) : null}
        <div class="space-y-1.5" data-testid="notes-change-file">
          {#if shown && (i >= SAID || f.change === "deleted")}
            <details class="group/f">
              <summary class="grid cursor-pointer list-none grid-cols-[auto_minmax(0,max-content)_1fr] items-baseline gap-x-2 [&::-webkit-details-marker]:hidden">
                <ChevronRight class="size-3.5 self-center text-muted-foreground transition-transform group-open/f:rotate-90" />{@render fileLine(f)}
              </summary>
              {@render lines(shown)}
            </details>
          {:else}
            <p class="grid grid-cols-[minmax(0,max-content)_1fr] items-baseline gap-x-6">{@render fileLine(f)}</p>
            {#if shown}
              {@render lines(shown)}
            {:else if !f.link && f.change !== "deleted"}
              <p class="fact">not shown: not text, or too large</p>
            {/if}
          {/if}
        </div>
      {/each}
      <div class="flex items-center gap-2 pt-1">
        {#if opened.files.some((f) => f.diff)}
          <details class="group min-w-0 flex-1 text-[13px]" data-testid="notes-raw-diff">
            <summary class="flex cursor-pointer list-none items-center gap-1 text-muted-foreground hover:text-foreground [&::-webkit-details-marker]:hidden">
              <ChevronRight class="size-3.5 transition-transform group-open:rotate-90" />Show the raw diff
            </summary>
            <pre class="mt-2 overflow-x-auto rounded-md border bg-card p-2 text-xs leading-5">{#each opened.files.filter((f) => f.diff) as f (f.path)}{`--- ${f.change === "added" ? "/dev/null" : `a/${f.path}`}\n+++ ${f.change === "deleted" ? "/dev/null" : `b/${f.path}`}\n${f.diff}`}{/each}</pre>
          </details>
        {:else}
          <span class="flex-1"></span>
        {/if}
        <Button variant="ghost" size="sm" class="self-start" onclick={() => ((asking = true), (error = null))} data-testid="notes-undo"><Undo2 />Undo this change</Button>
      </div>
    </div>
  {/if}
</div>

<Dialog
  bind:open={asking}
  title="Undo this change?"
  description="Its files are put back as they were before it. What the folder holds now is kept in the history first: the undo can be undone too."
  testid="notes-undo-dialog"
>
  <div class="space-y-4">
    {#if c.kind === "while-off"}<p class="text-sm text-muted-foreground">This change was made outside Handler: by you or another program.</p>{/if}
    <ul class="max-h-64 space-y-0.5 overflow-y-auto font-mono text-[13px]">
      {#each c.files as f (f.path)}<li>{f.path} <span class="fact">{f.change === "added" ? "removed" : "put back"}</span></li>{/each}
    </ul>
    {#if error}<p class="text-sm text-danger">{error}</p>{/if}
    <div class="flex justify-end gap-2 border-t pt-4">
      <Button variant="ghost" size="sm" onclick={() => (asking = false)}>Cancel</Button>
      <Button size="sm" disabled={busy} onclick={undo} data-testid="notes-undo-confirm">Undo</Button>
    </div>
  </div>
</Dialog>
