<script lang="ts">
  // What one run of an app's action answered (H.12): its result's summary with its status's dot,
  // a link to its agent's run; or why it failed.
  import type { ActionRun } from "../lib/contracts.gen";
  import { href } from "../lib/router.svelte";

  let { run }: { run: ActionRun } = $props();

  const TONE: Record<string, string> = { ok: "bg-ok", attention: "bg-warn", failed: "bg-danger" };
</script>

{#if run.state === "succeeded" && run.result}
  <div class="flex gap-2.5 rounded-lg bg-muted px-3 py-2.5 text-sm" data-testid="action-answer">
    <span class="mt-1.5 size-2 shrink-0 rounded-full {TONE[run.result.status]}"></span>
    <div class="space-y-1">
      <p>{run.result.summary}</p>
      {#if run.sessionId}<a class="text-xs text-link hover:underline" href={href({ view: "session", key: run.sessionId })}>Its run</a>{/if}
    </div>
  </div>
{:else if run.state === "failed"}
  <p class="text-sm text-danger" data-testid="action-failed">{run.error ?? "It failed."}</p>
{/if}
