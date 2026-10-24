<script lang="ts">
  // An agent's job or brief (its interface, D.18), edited as fields: its form (a skill field, one
  // at most: a skill of the library to work on); a job's result (a status and a summary, always,
  // then fields of its own) and how long a turn may take; under it (beside it when wide), the form
  // and a job's result card as they will look, filled with made-up values. A brief always has a
  // field (a brief without one is a chat). "Edit as JSON" (beside the section's heading) shows the schemas it writes; one
  // the editor cannot show as it is (the skill reviewer's) stays JSON.
  import Braces from "@lucide/svelte/icons/braces";
  import ListChecks from "@lucide/svelte/icons/list-checks";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import { Textarea } from "$lib/components/ui/textarea";
  import type { AgentInterface } from "../lib/contracts.gen";
  import { FORM_TYPES, RESULT_TYPES, interfaceOf, jobOf, newBrief, newJob, sampleInput, sampleOf, unsaved, type Job } from "../lib/interface";
  import { GROUP } from "../lib/form";
  import { fieldsOf, type Schema } from "../lib/runs";
  import JobFields from "./JobFields.svelte";
  import OutputView from "./OutputView.svelte";
  import RunFields from "./RunFields.svelte";

  // fresh: not saved with this job yet and not started from one (a definition's, a copied agent's:
  // their keys are what its callers send), so its fields' keys follow their labels; brief: the form
  // alone (the job's result kept here, given back when it is a job again)
  let { value = $bindable(), fresh, brief }: { value: string; fresh: boolean; brief: boolean } = $props();

  function parsed(text: string): AgentInterface | null {
    try {
      return JSON.parse(text) as AgentInterface;
    } catch {
      return null;
    }
  }

  // the job a JSON value is, as the editor shows it; null: it cannot
  function jobFrom(text: string): Job | null {
    const read = jobOf(parsed(text));
    return read && fresh ? unsaved(read) : read;
  }

  // the props give the initial value only
  // svelte-ignore state_referenced_locally
  const first = jobFrom(value);
  // svelte-ignore state_referenced_locally
  let job = $state<Job>(first ?? (brief ? newBrief() : newJob()));
  let asJson = $state(first === null);
  let cannot = $state(false); // "Back to the editor" refused: it cannot show this JSON

  // the editor writes the JSON
  $effect(() => {
    if (brief && !job.fields.length) job.fields = newBrief().fields;
  });
  $effect(() => {
    if (!asJson) value = JSON.stringify(interfaceOf(job, brief), null, 2);
  });

  function toFields(): void {
    const next = jobFrom(value);
    cannot = next === null;
    if (next) {
      job = next;
      asJson = false;
    }
  }

  const shown = $derived(asJson ? parsed(value) : interfaceOf(job, brief));
  const form = $derived(fieldsOf(shown?.fields as Schema | undefined));
  let previewValues = $state<Record<string, unknown>>({});
  $effect(() => {
    previewValues = sampleInput(form);
  });
  const minutes = $derived(Math.round(job.timeoutSec / 60));
</script>

<div class="@container space-y-4" data-testid="job-editor">
  <div class="flex flex-wrap items-center justify-between gap-2">
    <h2 id="group-job" class={GROUP}>{brief ? "The brief" : "The job"}</h2>
    {#if asJson}
      <Button type="button" variant="outline" onclick={toFields} data-testid="job-as-fields"><ListChecks />Back to the form</Button>
    {:else}
      <Button type="button" variant="outline" onclick={() => ((asJson = true), (cannot = false))} data-testid="job-as-json"><Braces />Edit as JSON</Button>
    {/if}
  </div>
  {#if asJson && cannot}
    <p class="text-xs text-warn" data-testid="job-cannot">The editor doesn't support this JSON. Keep editing it as JSON.</p>
  {/if}

  <div class="grid gap-6 @4xl:grid-cols-2">
    <div class="space-y-6">
      {#if asJson}
        <div class="space-y-2">
          <p class="text-xs text-muted-foreground">
            {#if brief}
              A JSON Schema: the form (<code>fields</code>; a string marked <code>"x-handler": "skill"</code> picks a skill to work on,
              read-only).
            {:else}
              JSON Schemas: the form (<code>fields</code>; a string marked <code>"x-handler": "skill"</code> picks a skill to work on,
              read-only), the result its final message must hold (<code>result</code>), and the time limit per turn (<code>timeoutSec</code>).
            {/if}
          </p>
          <Textarea bind:value rows={18} class="font-mono text-xs" spellcheck={false} data-testid="agent-interface-json" />
        </div>
      {:else}
        <div class="space-y-3">
          <h3 class="text-sm font-medium">Form</h3>
          {#if brief}
            <p class="text-xs text-muted-foreground">Filled in to start each session; then you work on it together.</p>
          {:else if !job.fields.length}
            <p class="text-xs text-muted-foreground" data-testid="job-no-fields">No fields: each run starts from its instructions alone.</p>
          {/if}
          <JobFields bind:fields={job.fields} types={FORM_TYPES} hints testid="job-field" />
        </div>

        {#if !brief}

        <div class="space-y-3">
          <h3 class="text-sm font-medium">Result</h3>
          <p class="rounded-md border bg-muted/50 p-2 text-xs text-muted-foreground" data-testid="job-fixed-result">
            Always included: <strong class="font-medium text-foreground">Status</strong> (ok, attention, failed) and
            <strong class="font-medium text-foreground">Summary</strong>. Your inbox, phone and automations use them.
          </p>
          <JobFields bind:fields={job.result} types={RESULT_TYPES} testid="job-result" add="Add a result field" />
        </div>

        <div class="flex flex-wrap items-center gap-2">
          <Label for="job-timeout" class="text-sm font-medium">Time limit</Label>
          <Input
            id="job-timeout"
            type="number"
            min={1}
            max={1440}
            value={minutes}
            oninput={(e) => {
              const n = Math.round(Number((e.currentTarget as HTMLInputElement).value));
              if (n >= 1 && n <= 1440) job.timeoutSec = n * 60;
            }}
            class="h-8 w-20"
            data-testid="job-timeout"
          />
          <span class="text-sm text-muted-foreground">min per turn</span>
        </div>
        {/if}
      {/if}
    </div>

    <div class="space-y-4 self-start @4xl:sticky @4xl:top-4" data-testid="job-preview">
      <div class="space-y-2">
        <p class="section-label">Preview: form</p>
        <div class="space-y-4 rounded-lg border bg-card p-4 [&_input]:text-muted-foreground [&_select]:text-muted-foreground [&_textarea]:text-muted-foreground" inert>
          {#if form.length}
            <RunFields fields={form} bind:values={previewValues} />
          {:else}
            <p class="text-sm text-muted-foreground">No form: each run starts right away.</p>
          {/if}
        </div>
      </div>
      {#if !shown || shown.result || !brief}
      <div class="space-y-2">
        <p class="section-label">Preview: result (sample values)</p>
        <div class="rounded-lg border bg-card p-4" data-testid="job-preview-result">
          {#if shown?.result}
            <OutputView schema={shown.result as Schema} value={sampleOf(shown.result as Schema)} />
          {:else}
            <p class="text-sm text-muted-foreground">Invalid JSON.</p>
          {/if}
        </div>
      </div>
      {/if}
    </div>
  </div>
</div>
