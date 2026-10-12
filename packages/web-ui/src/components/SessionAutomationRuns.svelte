<script lang="ts">
  // The side panel of a session's page listing the automation runs on it, or the one that started
  // it (an agent's run, contract I), each linked to its automation's page.
  import { RUN_STATE, usage } from "../lib/automations";
  import type { AutomationRun } from "../lib/contracts.gen";
  import { href } from "../lib/router.svelte";
  import When from "./When.svelte";

  let { runs }: { runs: AutomationRun[] } = $props();
</script>

<div class="space-y-3 text-sm" data-testid="session-automation-runs">
  <div>
    <h2 class="font-semibold">Automations</h2>
    <p class="text-xs text-muted-foreground">What ran on this conversation when it stopped, or started this run.</p>
  </div>
  <ul class="space-y-2">
    {#each runs as run (run.id)}
      <li class="space-y-0.5 rounded-md border p-2">
        <a class="font-medium text-link hover:underline" href={href({ view: "automation", name: run.automation })}>{run.automation}</a>
        <p class="text-xs text-muted-foreground">
          {RUN_STATE[run.state]}{run.trial ? " (a try)" : ""} · <When at={run.createdAt} />
          · {run.sessionId ? `events ${run.seqFrom}–${run.seqTo}` : "started this run"}{usage(run) ? ` · ${usage(run)}` : ""}
        </p>
        {#each run.appended ?? [] as a (a.to)}
          <p class="text-xs text-muted-foreground">{run.trial ? "would add" : "added"} to <code>{a.to}</code></p>
        {/each}
        {#if run.error}<p class="text-xs text-danger">{run.error}</p>{/if}
      </li>
    {/each}
  </ul>
</div>
