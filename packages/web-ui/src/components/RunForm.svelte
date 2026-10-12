<script lang="ts">
  // Start a run of an agent with an interface (D.18): its form (the interface's `fields`) and what
  // it works on (a skill of the library, mounted read-only), and which of the agent's models it
  // runs with when it has several. The run is unattended: its result is read on its page.
  import Play from "@lucide/svelte/icons/play";
  import { Button } from "$lib/components/ui/button";
  import { api } from "../lib/api";
  import type { Agent, ModelAccess, Session } from "../lib/contracts.gen";
  import { fieldsOf, fieldValues, type Schema } from "../lib/runs";
  import ModelChoice from "./ModelChoice.svelte";
  import RunFields from "./RunFields.svelte";

  let { agent, skill = "", onstarted }: { agent: Agent; skill?: string; onstarted: (run: Session) => void } = $props();

  const iface = $derived(agent.interface);
  const fields = $derived(fieldsOf(iface?.fields as Schema | undefined));
  let values = $state<Record<string, unknown>>({});
  // the props give the initial value only
  // svelte-ignore state_referenced_locally
  let subject = $state(skill);
  let model = $state<ModelAccess | undefined>();
  let busy = $state(false);
  let error = $state<string | null>(null);

  async function start(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    busy = true;
    error = null;
    try {
      const input = {
        fields: fieldValues(fields, values),
        ...(iface?.subject === "skill" ? { subject: { skill: subject } } : {}),
      };
      onstarted(await api.startRun(agent.id, input, model));
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

<form class="space-y-4" onsubmit={start} data-testid="run-form">
  <RunFields {agent} {fields} bind:values bind:subject />
  <ModelChoice {agent} bind:value={model} />
  <div class="flex items-center gap-3">
    <Button type="submit" disabled={busy || (iface?.subject === "skill" && !subject)} data-testid="run-start"><Play />Run</Button>
    <p class="text-xs text-muted-foreground">
      Unattended: it never asks before acting, it stops after
      {Math.round((iface?.timeoutSec ?? 1800) / 60)} min.
    </p>
  </div>
  {#if error}<p class="text-sm text-danger">{error}</p>{/if}
</form>
