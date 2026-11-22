<script lang="ts">
  // The Library's Schemas shelf (D.29, structured knowledge): each schema is one kind of
  // document (contacts, decisions) agents read or write in your notes folders, found by its
  // `$id` (contacts@1) alone. One place only: added here (a `.schema.json` file) or with an
  // agent that brings one; a different one with an `$id` already here asks before replacing.
  // Each row opens to its file, who uses it, and Remove. Agents never add one themselves.
  import { ask } from "../lib/ask.svelte";
  import Braces from "@lucide/svelte/icons/braces";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import Upload from "@lucide/svelte/icons/upload";
  import { Button } from "$lib/components/ui/button";
  import LoadingCards from "../components/LoadingCards.svelte";
  import ShelfBar from "../components/ShelfBar.svelte";
  import UsesPanel from "../components/UsesPanel.svelte";
  import { api, ApiError } from "../lib/api";
  import type { SchemaInfo } from "../lib/contracts.gen";
  import { LIBRARY_WIDTH } from "../lib/library";

  let schemas = $state<SchemaInfo[]>([]);
  let loaded = $state(false);
  let open = $state<string | null>(null); // the schema whose file is shown
  let content = $state<string | null>(null);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let files = $state<HTMLInputElement | null>(null);

  async function load(): Promise<void> {
    try {
      schemas = await api.schemas();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      loaded = true;
    }
  }

  async function show(id: string): Promise<void> {
    if (open === id) return void (open = null);
    open = id;
    content = null;
    try {
      content = (await api.schema(id)).content ?? "";
    } catch (e) {
      error = (e as Error).message;
    }
  }

  /** A schema file into the Library; one of its `$id` already there and different: asked. */
  async function add(file: File): Promise<void> {
    busy = true;
    error = null;
    try {
      const text = await file.text();
      let added: SchemaInfo;
      try {
        added = await api.addSchema(text);
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 409)) throw e;
        if (!(await ask({ title: `Replace it with ${file.name}?`, detail: e.detail ?? undefined, yes: "Replace", danger: true }))) return;
        added = await api.addSchema(text, true);
      }
      await load();
      open = null;
      await show(added.id);
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
      if (files) files.value = "";
    }
  }

  async function remove(id: string): Promise<void> {
    if (!(await ask({ title: `Remove ${id} from your Library?`, detail: "Its documents stay in your notes.", yes: "Remove", danger: true }))) return;
    error = null;
    try {
      await api.deleteSchema(id);
      open = null;
      await load();
    } catch (e) {
      error = (e as Error).message;
    }
  }

  $effect(() => void load());
</script>

<input
  bind:this={files}
  type="file"
  accept=".json"
  class="hidden"
  onchange={(e) => {
    const file = e.currentTarget.files?.[0];
    if (file) void add(file);
  }}
  data-testid="add-schema-file"
/>

<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full {LIBRARY_WIDTH} space-y-5 px-8 py-6" data-testid="schemas-page">
    <ShelfBar>
      {#snippet actions()}
        <Button size="sm" variant="outline" disabled={busy} onclick={() => files?.click()} data-testid="add-schema"><Upload />Add a schema</Button>
      {/snippet}
    </ShelfBar>
    {#if error}<p class="text-sm text-danger" data-testid="schema-error">{error}</p>{/if}
    {#if !loaded}
      <div class="space-y-3"><LoadingCards count={2} height="h-16" /></div>
    {:else if schemas.length}
      <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
        {#each schemas as s (s.id)}
          <li class="enter" data-testid="schema-card">
            <button type="button" class="flex w-full cursor-pointer items-center gap-4 px-4 py-3.5 text-left hover:bg-muted/40" aria-expanded={open === s.id} onclick={() => show(s.id)}>
              <span class="hidden size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground sm:flex"><Braces class="size-4" /></span>
              <div class="min-w-0 flex-1 space-y-0.5">
                <p class="font-medium">{s.title ?? s.id} <span class="font-mono text-xs text-muted-foreground">{s.id}</span></p>
                {#if s.description}<p class="line-clamp-2 text-muted-foreground">{s.description}</p>{/if}
                {#if s.extends}<p class="fact">extends {s.extends}</p>{/if}
              </div>
              {#if s.error}<span class="inline-flex items-center gap-1 text-xs text-warn" title={s.error} data-testid="schema-broken"><TriangleAlert class="size-3" />Broken</span>{/if}
            </button>
            {#if open === s.id}
              <div class="space-y-3 border-t px-4 py-3.5" data-testid="schema-open">
                {#if s.error}<p class="text-sm text-warn">{s.error}</p>{/if}
                <pre class="max-h-80 overflow-auto rounded-md bg-muted/40 p-3 font-mono text-xs" data-testid="schema-content">{content ?? "…"}</pre>
                <UsesPanel kind="schema" id={s.id} />
                <Button size="sm" variant="ghost" class="text-danger" onclick={() => remove(s.id)} data-testid="schema-remove">Remove</Button>
              </div>
            {/if}
          </li>
        {/each}
      </ul>
    {:else}
      <div class="rounded-[10px] border border-dashed px-6 py-8 text-center text-sm text-muted-foreground" data-testid="schemas-none">
        <p>No schema yet. A schema is one kind of document an agent keeps in your notes (contacts, decisions): its fields and sections, so every document of that kind has the same shape.</p>
        <Button size="sm" class="mt-3" disabled={busy} onclick={() => files?.click()}>Add a schema</Button>
      </div>
    {/if}
  </div>
</div>
