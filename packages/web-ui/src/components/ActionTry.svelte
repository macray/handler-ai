<script lang="ts">
  // Try one of an app's actions (H.12), from its page: its form (the route's, or its agent's), one
  // real run, its answer. Done by the app's code it answers at once; by its agent, it is read
  // again until it ends (its result also reaches the inbox).
  import Play from "@lucide/svelte/icons/play";
  import { Button } from "$lib/components/ui/button";
  import { api } from "../lib/api";
  import type { AppAction, ActionRun } from "../lib/contracts.gen";
  import { href } from "../lib/router.svelte";
  import { fieldsOf, fieldValues, type Schema } from "../lib/runs";
  import RunFields from "./RunFields.svelte";

  let { app, action, initial = {} }: { app: string; action: AppAction; initial?: Record<string, unknown> } = $props();

  const fields = $derived(fieldsOf(action.fields as Schema | undefined));
  // the props give the initial values only (Ask's Not this: what the router had filled)
  // svelte-ignore state_referenced_locally
  let values = $state<Record<string, unknown>>({ ...initial });
  let run = $state<ActionRun | null>(null);
  let busy = $state(false);
  let error = $state<string | null>(null);

  const TONE: Record<string, string> = { ok: "bg-ok", attention: "bg-warn", failed: "bg-danger" };

  async function go(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    busy = true;
    error = null;
    run = null;
    try {
      run = await api.act(app, action.name, fieldValues(fields, values));
      while (run.state === "running" && run.runId) {
        await new Promise((r) => setTimeout(r, 1000));
        run = await api.actionRun(app, action.name, run.runId);
      }
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

<form class="space-y-4" onsubmit={go} data-testid="action-try">
  {#if fields.length}<RunFields {fields} bind:values />{:else}<p class="text-sm text-muted-foreground">It takes nothing: Run does it.</p>{/if}
  <div class="flex items-center gap-3 border-t pt-3">
    <p class="text-xs text-muted-foreground">One real run, as if you asked it: {action.by === "code" ? "its code answers at once" : "its agent works on it, which may take a while"}.</p>
    <Button type="submit" class="ml-auto" disabled={busy} data-testid="action-run"><Play />{run ? "Run again" : "Run"}</Button>
  </div>
  {#if busy && run?.state === "running"}<p class="fact" data-testid="action-running">Its agent is working…</p>{/if}
  {#if run?.state === "succeeded" && run.result}
    <div class="flex gap-2.5 rounded-lg bg-muted px-3 py-2.5 text-sm" data-testid="action-answer">
      <span class="mt-1.5 size-2 shrink-0 rounded-full {TONE[run.result.status]}"></span>
      <div class="space-y-1">
        <p>{run.result.summary}</p>
        {#if run.sessionId}<a class="text-xs text-link hover:underline" href={href({ view: "session", key: run.sessionId })}>Its run</a>{/if}
      </div>
    </div>
  {:else if run?.state === "failed"}
    <p class="text-sm text-danger" data-testid="action-failed">{run.error ?? "It failed."}</p>
  {/if}
  {#if error}<p class="text-sm text-danger" data-testid="action-error">{error}</p>{/if}
</form>
