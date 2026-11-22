<script lang="ts">
  // An agent's own environment variables (D.8), in the agent form: rows of NAME = value, added
  // and removed; none at first, so only "Add a variable". Plain values, kept in its settings:
  // a key or a token goes in a tool's connection instead. What Handler, its harness or its tools
  // set already is refused when it is saved, saying who sets it.
  import Plus from "@lucide/svelte/icons/plus";
  import X from "@lucide/svelte/icons/x";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import type { EnvRow } from "../lib/env";

  let { rows = $bindable() }: { rows: EnvRow[] } = $props();
</script>

<section class="space-y-2" aria-labelledby="group-env" data-testid="agent-env">
  <h2 id="group-env" class="text-sm font-semibold">Environment variables</h2>
  {#if rows.length}
    <div class="divide-y overflow-hidden rounded-[10px] border bg-card shadow-panel">
      {#each rows as row, i (i)}
        <div class="flex items-center gap-2 px-4 py-2" data-testid="agent-env-row">
          <Input class="w-64 font-mono text-sm" placeholder="NAME" aria-label="Name" bind:value={row.name} data-testid="agent-env-name" />
          <span class="text-muted-foreground">=</span>
          <Input class="min-w-0 flex-1 font-mono text-sm" placeholder="value" aria-label="Value of {row.name || 'the variable'}" bind:value={row.value} data-testid="agent-env-value" />
          <Button type="button" size="icon" variant="ghost" aria-label="Remove {row.name || 'the variable'}" onclick={() => (rows = rows.filter((_, j) => j !== i))} data-testid="agent-env-remove"><X /></Button>
        </div>
      {/each}
    </div>
  {/if}
  <p class="flex items-center gap-3">
    <Button type="button" size="sm" variant="outline" onclick={() => (rows = [...rows, { name: "", value: "" }])} data-testid="agent-env-add"><Plus />Add a variable</Button>
    <span class="text-xs text-muted-foreground">set in its sandbox, e.g. ASTRO_TELEMETRY_DISABLED = 1. Never a key or a token: give those through a tool's connection.</span>
  </p>
</section>
