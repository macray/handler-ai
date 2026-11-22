<script lang="ts">
  // Why an app could not be deployed, updated or started, with the end of its log right under
  // it: its tests' output, or what its backend printed before it stopped. The error says "see
  // the log": it is here, not on another tab. "Whole log" shows all of it.
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import { api } from "../lib/api";
  import { logTail } from "../lib/apps";

  let {
    name,
    message,
    from = "deploy",
    testid = "app-failure",
  }: {
    name: string;
    message: string;
    from?: "deploy" | "start"; // what failed: the log is shown from that step's start
    testid?: string;
  } = $props();

  let log = $state<string | null>(null);
  let whole = $state(false);

  $effect(() => {
    void message; // a new failure: its log read again
    log = null;
    whole = false;
    api
      .appLog(name)
      .then((l) => (log = l.text))
      .catch((e: Error) => (log = `Its log cannot be read: ${e.message}`));
  });

  const shown = $derived(log === null ? null : whole ? log : logTail(log, from));
</script>

<div class="space-y-2 rounded-[10px] bg-danger/8 px-4 py-3 text-sm" role="alert" data-testid={testid}>
  <p class="flex items-start gap-2 text-danger"><TriangleAlert class="mt-0.5 size-4 shrink-0" />{message}</p>
  {#if shown === null}
    <p class="text-xs text-muted-foreground">Reading its log…</p>
  {:else}
    <div class="flex items-baseline justify-between gap-3">
      <p class="text-xs text-muted-foreground">{whole ? "Its whole log, newest last" : "The end of its log"}</p>
      {#if log && logTail(log, from) !== log}
        <button type="button" class="cursor-pointer text-xs text-link hover:underline" onclick={() => (whole = !whole)} data-testid="{testid}-whole">{whole ? "Only the end" : "Whole log"}</button>
      {/if}
    </div>
    <pre class="max-h-[50vh] overflow-auto rounded-lg bg-muted p-3 font-mono text-xs whitespace-pre-wrap" data-testid="{testid}-log">{shown || "(empty)"}</pre>
  {/if}
</div>
