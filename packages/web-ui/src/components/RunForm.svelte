<script lang="ts">
  // Start a session of an agent with an interface (D.18): its form (the interface's `fields`;
  // `skill` fills its skill field, from a skill's page), and which of the agent's models it runs
  // with when it has several. A job's run is unattended: its result is read on its page; a
  // brief's session goes on as a chat.
  import Play from "@lucide/svelte/icons/play";
  import { Button } from "$lib/components/ui/button";
  import { api } from "../lib/api";
  import type { Agent, ModelAccess, Session } from "../lib/contracts.gen";
  import { fieldsOf, fieldValues, skillField, type Schema } from "../lib/runs";
  import ModelChoice from "./ModelChoice.svelte";
  import RunFields from "./RunFields.svelte";

  let { agent, skill = "", onstarted }: { agent: Agent; skill?: string; onstarted: (run: Session) => void } = $props();

  const iface = $derived(agent.interface);
  const fields = $derived(fieldsOf(iface?.fields as Schema | undefined));
  // the props give the initial value only
  // svelte-ignore state_referenced_locally
  const key = skillField(agent.interface);
  // svelte-ignore state_referenced_locally
  let values = $state<Record<string, unknown>>(key && skill ? { [key]: skill } : {});
  // a required field the browser cannot check: a choice of skill
  const missing = $derived(fields.some((f) => f.kind === "skill" && f.required && !values[f.key]));
  let model = $state<ModelAccess | undefined>();
  let busy = $state(false);
  let error = $state<string | null>(null);

  async function start(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    busy = true;
    error = null;
    try {
      const input = { fields: fieldValues(fields, values) };
      onstarted(await api.startRun(agent.id, input, model));
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

<form class="space-y-4" onsubmit={start} data-testid="run-form">
  <RunFields {fields} bind:values />
  <div class="flex flex-wrap items-center gap-3 border-t pt-3">
    <ModelChoice {agent} bind:value={model} />
    <Button type="submit" class="ml-auto" disabled={busy || missing} data-testid="run-start"><Play />{iface?.result ? "Start the run" : "Start"}</Button>
  </div>
  {#if iface?.result}
    <p class="text-xs text-muted-foreground">
      Unattended: {agent.modelAlone ? "the model alone, nothing outside its call" : "it never asks before acting"}, it stops after
      {Math.round((iface.timeoutSec ?? 1800) / 60)} min.
    </p>
  {/if}
  {#if error}<p class="text-sm text-danger">{error}</p>{/if}
</form>
