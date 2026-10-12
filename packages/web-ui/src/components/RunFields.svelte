<script lang="ts">
  // The input of a run of an agent with an interface (D.18): what it works on (a skill of the
  // library, mounted read-only) and its form (the interface's `fields`). A run started now
  // (RunForm) or by an automation (the new automation form) fills it the same way.
  import { Checkbox } from "$lib/components/ui/checkbox";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import * as NativeSelect from "$lib/components/ui/native-select";
  import { Textarea } from "$lib/components/ui/textarea";
  import { api } from "../lib/api";
  import type { Agent, SkillInfo } from "../lib/contracts.gen";
  import type { Field } from "../lib/runs";

  let {
    agent,
    fields,
    values = $bindable(),
    subject = $bindable(),
  }: { agent: Agent; fields: Field[]; values: Record<string, unknown>; subject: string } = $props();

  let skills = $state<SkillInfo[]>([]);
  let error = $state<string | null>(null);

  $effect(() => {
    if (agent.interface?.subject !== "skill") return;
    api.skills().then(
      (list) => (skills = list.filter((s) => !s.error)),
      (e: Error) => (error = e.message),
    );
  });
</script>

{#if agent.interface?.subject === "skill"}
  <div class="space-y-1.5">
    <Label for="run-subject">Skill</Label>
    <NativeSelect.Root id="run-subject" bind:value={subject} class="w-full" data-testid="run-subject">
      <NativeSelect.Option value="" disabled>Choose a skill of the library</NativeSelect.Option>
      {#each skills as s (s.name)}<NativeSelect.Option value={s.name}>{s.name}</NativeSelect.Option>{/each}
    </NativeSelect.Root>
    <p class="text-xs text-muted-foreground">Mounted read-only: the agent reads it, never changes it.</p>
  </div>
{/if}
{#each fields as f (f.key)}
  <div class="space-y-1.5">
    {#if f.kind === "boolean"}
      <div class="flex items-center gap-2">
        <Checkbox id={`run-${f.key}`} checked={values[f.key] === true} onCheckedChange={(c) => (values[f.key] = c === true)} />
        <Label for={`run-${f.key}`} class="font-normal">{f.title}</Label>
      </div>
    {:else}
      <Label for={`run-${f.key}`}>{f.title}{f.required ? "" : " (optional)"}</Label>
      {#if f.kind === "choice"}
        <NativeSelect.Root id={`run-${f.key}`} bind:value={values[f.key] as string} class="w-full">
          <NativeSelect.Option value="">—</NativeSelect.Option>
          {#each f.choices as c (c)}<NativeSelect.Option value={c}>{c}</NativeSelect.Option>{/each}
        </NativeSelect.Root>
      {:else if f.kind === "number"}
        <Input id={`run-${f.key}`} type="number" bind:value={values[f.key]} required={f.required} />
      {:else}
        <Textarea
          id={`run-${f.key}`}
          bind:value={values[f.key] as string}
          rows={f.kind === "json" ? 4 : 2}
          class={f.kind === "json" ? "font-mono text-xs" : ""}
          placeholder={f.kind === "json" ? "JSON" : ""}
          required={f.required}
          data-testid={`run-field-${f.key}`}
        />
      {/if}
    {/if}
    {#if f.description}<p class="text-xs text-muted-foreground">{f.description}</p>{/if}
  </div>
{/each}
{#if error}<p class="text-sm text-danger">{error}</p>{/if}
