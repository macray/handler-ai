<script lang="ts">
  // Pick the schemas an agent reads or writes (D.29, its knowledge uses): schemas of the Library
  // (Library → Schemas), as chips, the list behind + Add; then each one's Writes switch (it may
  // make and change documents of that schema, in the notes folders it can write). Writing a
  // schema is no risk of its own: a notes folder given read-write is (amber, in Notes).
  import PickRow from "./PickRow.svelte";
  import PickerChips from "./PickerChips.svelte";
  import Switch from "./Switch.svelte";
  import { api } from "../lib/api";
  import type { KnowledgeUse, SchemaInfo } from "../lib/contracts.gen";
  import { href } from "../lib/router.svelte";

  let { value = $bindable([]) }: { value?: KnowledgeUse[] } = $props();

  let library = $state<SchemaInfo[] | null>(null);
  let error = $state<string | null>(null);

  $effect(() => {
    api.schemas().then(
      (l) => (library = l),
      (e: Error) => (error = e.message),
    );
  });

  const picked = $derived(value.map((u) => u.schemaId));

  function toggle(id: string, checked: boolean): void {
    const rest = value.filter((u) => u.schemaId !== id);
    value = checked ? [...rest, { schemaId: id, access: "read" }] : rest;
  }

  function setAccess(id: string, write: boolean): void {
    value = value.map((u) => (u.schemaId === id ? { ...u, access: write ? "write" : "read" } : u));
  }
</script>

<div class="space-y-2">
  <PickerChips chips={value.map((u) => ({ key: u.schemaId, name: u.schemaId }))} onremove={(id) => toggle(id, false)} label="Add a schema" testid="schema-picker">
    {#snippet list()}
      <div class="divide-y">
        {#each library ?? [] as s (s.id)}
          <PickRow name={s.id} description={s.title ?? ""} badge={s.error ? "broken" : ""} checked={picked.includes(s.id)} disabled={!!s.error && !picked.includes(s.id)} onchange={(on) => toggle(s.id, on)} testid="schema-option" />
        {/each}
        {#if library && !library.length}<p class="px-3 py-2 text-xs text-muted-foreground">No schema yet: add one in <a href={href({ view: "library", shelf: "schemas" })}>Library → Schemas</a>.</p>{/if}
      </div>
    {/snippet}
  </PickerChips>
  {#if value.length}
    <ul class="space-y-1.5" data-testid="schema-access">
      {#each value as u (u.schemaId)}
        <li class="flex items-center gap-3 text-sm">
          <span class="min-w-0 truncate font-mono text-xs">{u.schemaId}</span>
          <span class="text-xs text-muted-foreground">{u.access === "write" ? "makes and changes its documents" : "reads its documents"}</span>
          <span class="ml-auto text-xs text-muted-foreground">Writes</span>
          <Switch checked={u.access === "write"} onchange={(on) => setAccess(u.schemaId, on)} label="Writes {u.schemaId}" testid="schema-write" />
        </li>
      {/each}
    </ul>
  {/if}
</div>
{#if error}<p class="text-sm text-danger">{error}</p>{/if}
