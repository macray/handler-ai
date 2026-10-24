<script lang="ts">
  // The input of a run of an agent with an interface (D.18): its form (the interface's `fields`;
  // a skill field picks a skill of the library, mounted read-only). A run started now
  // (RunForm) or by an automation (the new automation form) fills it the same way; the agent
  // editor shows it as a preview of the form it is making.
  import { Checkbox } from "$lib/components/ui/checkbox";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import * as NativeSelect from "$lib/components/ui/native-select";
  import { Textarea } from "$lib/components/ui/textarea";
  import { api } from "../lib/api";
  import type { SkillInfo } from "../lib/contracts.gen";
  import type { Field } from "../lib/runs";

  let { fields, values = $bindable() }: { fields: Field[]; values: Record<string, unknown> } = $props();

  let skills = $state<SkillInfo[]>([]);
  let error = $state<string | null>(null);

  $effect(() => {
    if (!fields.some((f) => f.kind === "skill")) return;
    api.skills().then(
      (list) => (skills = list.filter((s) => !s.error)),
      (e: Error) => (error = e.message),
    );
  });
</script>

{#each fields as f (f.key)}
  <div class="space-y-1.5">
    {#if f.kind === "boolean"}
      <div class="flex items-center gap-2">
        <Checkbox id={`run-${f.key}`} checked={values[f.key] === true} onCheckedChange={(c) => (values[f.key] = c === true)} data-testid={`run-field-${f.key}`} />
        <Label for={`run-${f.key}`} class="font-normal">{f.title}</Label>
      </div>
    {:else}
      <Label for={`run-${f.key}`}>{f.title}{f.required ? "" : " (optional)"}</Label>
      {#if f.kind === "skill"}
        <NativeSelect.Root id={`run-${f.key}`} bind:value={values[f.key] as string} class="w-full" data-testid={`run-field-${f.key}`}>
          <NativeSelect.Option value="" disabled={f.required}>{f.required ? "Choose a skill from your library" : "—"}</NativeSelect.Option>
          {#each skills as s (s.name)}<NativeSelect.Option value={s.name}>{s.name}</NativeSelect.Option>{/each}
        </NativeSelect.Root>
        <p class="text-xs text-muted-foreground">The agent gets a read-only copy.</p>
      {:else if f.kind === "choice"}
        <NativeSelect.Root id={`run-${f.key}`} bind:value={values[f.key] as string} class="w-full" data-testid={`run-field-${f.key}`}>
          <NativeSelect.Option value="">—</NativeSelect.Option>
          {#each f.choices as c (c)}<NativeSelect.Option value={c}>{c}</NativeSelect.Option>{/each}
        </NativeSelect.Root>
      {:else if f.kind === "number"}
        <Input id={`run-${f.key}`} type="number" bind:value={values[f.key]} required={f.required} data-testid={`run-field-${f.key}`} />
      {:else if f.kind === "text"}
        <Input id={`run-${f.key}`} bind:value={values[f.key] as string} required={f.required} data-testid={`run-field-${f.key}`} />
      {:else}
        <Textarea
          id={`run-${f.key}`}
          bind:value={values[f.key] as string}
          rows={f.kind === "json" || f.kind === "list" ? 4 : 3}
          class={f.kind === "json" ? "font-mono text-xs" : ""}
          placeholder={f.kind === "json" ? "JSON" : f.kind === "list" ? "One per line" : ""}
          required={f.required}
          data-testid={`run-field-${f.key}`}
        />
      {/if}
    {/if}
    {#if f.description}<p class="text-xs text-muted-foreground">{f.description}</p>{/if}
  </div>
{/each}
{#if error}<p class="text-sm text-danger">{error}</p>{/if}
