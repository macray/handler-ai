<script lang="ts">
  // One of an app's actions as a form (H.12): its fields drawn from its schema, sent as one real
  // run, then its answer. Done by the app's code it answers at once; by its agent, it is read
  // again until it ends (its result also reaches the inbox). Try on the app's page and a nudge's
  // form in the inbox (H.17, sent with the nudge's id: its success marks the nudge done) both
  // draw it; `extra` adds controls beside the button (a nudge's microphone).
  import type { Component, Snippet } from "svelte";
  import { Button } from "$lib/components/ui/button";
  import { api } from "../lib/api";
  import type { ActionRun } from "../lib/contracts.gen";
  import { fieldsOf, fieldValues, type Schema } from "../lib/runs";
  import ActionAnswer from "./ActionAnswer.svelte";
  import RunFields from "./RunFields.svelte";

  let {
    app,
    action,
    schema,
    values = $bindable({}),
    nudge,
    label,
    again = label,
    icon: Icon,
    note,
    extra,
    onran,
    testid = "action-try",
    submitTestid = "action-run",
  }: {
    app: string;
    action: string;
    schema: Schema | null | undefined;
    values?: Record<string, unknown>;
    nudge?: string;
    label: string;
    again?: string;
    icon: Component;
    note?: string;
    extra?: Snippet;
    onran?: (run: ActionRun) => void;
    testid?: string;
    submitTestid?: string;
  } = $props();

  const fields = $derived(fieldsOf(schema));
  let run = $state<ActionRun | null>(null);
  let busy = $state(false);
  let error = $state<string | null>(null);

  async function go(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    busy = true;
    error = null;
    run = null;
    try {
      run = await api.act(app, action, fieldValues(fields, values), nudge);
      while (run.state === "running" && run.runId) {
        await new Promise((r) => setTimeout(r, 1000));
        run = await api.actionRun(app, action, run.runId);
      }
      onran?.(run);
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

<form class="space-y-4" onsubmit={go} data-testid={testid}>
  {#if fields.length}<RunFields {fields} bind:values />{:else}<p class="text-sm text-muted-foreground">It takes nothing: {label} does it.</p>{/if}
  <div class="flex items-center gap-3 border-t pt-3">
    {#if note}<p class="text-xs text-muted-foreground">{note}</p>{/if}
    <div class="ml-auto flex items-center gap-2">
      {@render extra?.()}
      <Button type="submit" disabled={busy} data-testid={submitTestid}><Icon />{run ? again : label}</Button>
    </div>
  </div>
  {#if busy && run?.state === "running"}<p class="fact" data-testid="action-running">Its job is running…</p>{/if}
  {#if run}<ActionAnswer {run} />{/if}
  {#if error}<p class="text-sm text-danger" data-testid="action-error">{error}</p>{/if}
</form>
