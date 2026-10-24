<script lang="ts">
  // The fields of a job (D.18) as rows under one header (label, type, required): under a row, the
  // choices of a choice, its hint when asked for (a run's form only), the fields of each item of a
  // list of items (one level). Used for a run's form and for its result (JobEditor). A form has
  // one skill field at most (D.18): a second one says so.
  import X from "@lucide/svelte/icons/x";
  import Plus from "@lucide/svelte/icons/plus";
  import { SvelteSet } from "svelte/reactivity";
  import { Button } from "$lib/components/ui/button";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import { Input } from "$lib/components/ui/input";
  import * as NativeSelect from "$lib/components/ui/native-select";
  import JobFields from "./JobFields.svelte";
  import { FIELD_TYPES, ITEM_TYPES, newField, type FieldDef, type FieldType } from "../lib/interface";

  let {
    fields = $bindable(),
    types,
    hints = false,
    testid,
    add = "Add a field",
  }: { fields: FieldDef[]; types: FieldType[]; hints?: boolean; testid: string; add?: string } = $props();

  const offered = $derived(FIELD_TYPES.filter((t) => types.includes(t.type)));
  const firstSkill = $derived(fields.findIndex((f) => f.type === "skill"));
  // the rows whose hint was asked for (one with a hint shows it anyway)
  const hinted = new SvelteSet<FieldDef>();

  const COLUMNS = "grid grid-cols-[minmax(0,1fr)_9.5rem_3.75rem_2rem] items-center gap-2";
  const SUB = "grid grid-cols-[4rem_minmax(0,1fr)] items-center gap-2 pl-1";
  const SUB_LABEL = "text-xs text-muted-foreground";
</script>

<div class="space-y-2" data-testid={testid}>
  {#if fields.length}
    <div class="{COLUMNS} px-2 text-xs text-muted-foreground" aria-hidden="true">
      <span>Label</span><span>Type</span><span class="text-center">Required</span><span></span>
    </div>
  {/if}
  {#each fields as f, i (i)}
    <div class="space-y-1.5 rounded-md border bg-background p-2" data-testid="{testid}-row">
      <div class={COLUMNS}>
        <Input bind:value={f.title} placeholder="e.g. Due date" class="h-8" aria-label="label" data-testid="{testid}-title" />
        <NativeSelect.Root bind:value={f.type} class="h-8 w-full" aria-label="type" data-testid="{testid}-type">
          {#each offered as t (t.type)}<NativeSelect.Option value={t.type}>{t.label}</NativeSelect.Option>{/each}
        </NativeSelect.Root>
        <div class="flex justify-center"><Checkbox bind:checked={f.required} aria-label="required" data-testid="{testid}-required" /></div>
        <Button type="button" variant="ghost" size="icon-sm" aria-label="remove" title="Remove" onclick={() => fields.splice(i, 1)} data-testid="{testid}-remove">
          <X />
        </Button>
      </div>
      {#if f.type === "choice"}
        <label class={SUB}>
          <span class={SUB_LABEL}>Choices</span>
          <Input bind:value={f.choices} placeholder="low, medium, high" class="h-7 text-xs" data-testid="{testid}-choices" />
        </label>
      {/if}
      {#if f.type === "skill"}
        {#if i === firstSkill}
          <p class="pl-1 text-xs text-muted-foreground">Picks a skill from your library. The agent gets a read-only copy.</p>
        {:else}
          <p class="pl-1 text-xs text-warn" data-testid="{testid}-second-skill">A form has one Skill field at most: change this one's type.</p>
        {/if}
      {/if}
      {#if hints && (f.description || hinted.has(f))}
        <label class={SUB}>
          <span class={SUB_LABEL}>Hint</span>
          <Input bind:value={f.description} placeholder="Shown under the field" class="h-7 text-xs" data-testid="{testid}-hint" />
        </label>
      {:else if hints}
        <button type="button" class="cursor-pointer pl-1 text-xs text-muted-foreground hover:text-foreground" onclick={() => hinted.add(f)} data-testid="{testid}-add-hint">
          + Add a hint
        </button>
      {/if}
      {#if f.type === "items"}
        <div class="space-y-1 pt-1 pl-4">
          <p class={SUB_LABEL}>Each item has:</p>
          <JobFields bind:fields={f.items} types={ITEM_TYPES} testid="{testid}-item" add="Add a field to each item" />
        </div>
      {/if}
    </div>
  {/each}
  <Button type="button" variant="outline" size="sm" onclick={() => fields.push(newField())} data-testid="{testid}-add"><Plus />{add}</Button>
</div>
