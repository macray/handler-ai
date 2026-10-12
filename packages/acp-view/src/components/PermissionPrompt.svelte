<script lang="ts">
  // The agent waits for your answer: what it asks to do (the tool call's own title, its files and
  // its diff, never the agent's prose about it), then its options, allow and reject apart.
  import type { PermissionOption } from "@agentclientprotocol/sdk";
  import type { PendingPermission } from "../lib/connection.svelte";
  import Diff from "./Diff.svelte";

  let { pending }: { pending: PendingPermission } = $props();

  const tool = $derived(pending.request.toolCall);
  const options = $derived(pending.request.options);
  const allows = $derived(options.filter((o) => o.kind.startsWith("allow")));
  const rejects = $derived(options.filter((o) => o.kind.startsWith("reject")));
  const VERB: Record<string, string> = {
    execute: "run a command",
    edit: "change a file",
    delete: "delete a file",
    move: "move a file",
    fetch: "reach the network",
    read: "read a file",
  };
  const asks = $derived(tool.kind && VERB[tool.kind] ? `to ${VERB[tool.kind]}` : "for permission");
  const diffs = $derived((tool.content ?? []).filter((c) => c.type === "diff"));
  const paths = $derived((tool.locations ?? []).map((l) => l.path));

  function choose(option: PermissionOption): void {
    pending.answer({ outcome: "selected", optionId: option.optionId });
  }
</script>

<div class="permission" role="alertdialog" aria-label="permission request" aria-live="assertive" data-testid="permission-request">
  <div class="head">
    <span class="badge">Needs you</span>
    <span>The agent asks {asks}:</span>
  </div>
  <pre class="what">{tool.title ?? tool.toolCallId}</pre>
  {#if paths.length}<p class="paths">{paths.join(" · ")}</p>{/if}
  {#each diffs as d, i (i)}
    {#if d.type === "diff"}<Diff path={d.path} oldText={d.oldText} newText={d.newText} />{/if}
  {/each}
  <div class="answers">
    {#each allows as option (option.optionId)}
      <button type="button" class="allow" onclick={() => choose(option)}>{option.name}</button>
    {/each}
    {#each rejects as option (option.optionId)}
      <button type="button" class="reject" onclick={() => choose(option)}>{option.name}</button>
    {/each}
  </div>
</div>

<style>
  .permission {
    border: 1px solid var(--warn);
    border-radius: 8px;
    padding: 0.75rem 0.9rem;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
    margin: 0.5rem 0;
    background: color-mix(in srgb, var(--warn) 12%, var(--background));
  }
  .head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.6rem;
    font-weight: 600;
  }
  .badge {
    background: var(--warn);
    color: var(--background);
    border-radius: 4px;
    padding: 0.05rem 0.45rem;
    font-size: 0.85em;
    font-weight: 700;
  }
  .what {
    margin: 0;
    padding: 0.5rem 0.7rem;
    border-radius: 6px;
    background: var(--background);
    border: 1px solid color-mix(in srgb, var(--warn) 50%, transparent);
    color: var(--foreground);
    font-weight: 600;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .paths {
    margin: 0;
    color: var(--muted-foreground);
    overflow-wrap: anywhere;
  }
  .answers {
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
  }
  button {
    border-radius: 6px;
    padding: 0.35rem 0.9rem;
    font-size: 1em;
    font-weight: 600;
    border: 1px solid transparent;
  }
  .allow {
    background: var(--ok);
    color: var(--background);
  }
  .allow:hover {
    background: color-mix(in srgb, var(--ok) 85%, var(--foreground));
  }
  .reject {
    color: var(--danger);
    border-color: var(--danger);
    background: var(--background);
  }
  .reject:hover {
    background: color-mix(in srgb, var(--danger) 12%, var(--background));
  }
</style>
