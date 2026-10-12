<script lang="ts">
  // Runs of agents with an interface (D.18), most recent first: how each went, what it was given,
  // its verdict when its result has one, and (a skill's reviews) whether the skill changed since.
  // The agent of each only when they come from several (a skill's reviewers). Each opens its page.
  import When from "./When.svelte";
  import * as Table from "$lib/components/ui/table";
  import StatusBadge from "./StatusBadge.svelte";
  import type { Agent, Session } from "../lib/contracts.gen";
  import { href } from "../lib/router.svelte";
  import { inputSummary, runState, verdictOf, type Schema } from "../lib/runs";
  import { agentLabel } from "../lib/projects.svelte";

  let { runs, agents, digest }: { runs: Session[]; agents: Agent[]; digest?: string | null } = $props();

  const TONE = { ok: "text-ok", warn: "text-warn", danger: "text-danger", muted: "text-muted-foreground" };
  const STATE: Record<string, string> = { running: "running", done: "succeeded", invalid: "failed", "no result": "failed" };
  const several = $derived(new Set(runs.map((r) => r.agentId)).size > 1);

  function agentOf(r: Session): Agent | undefined {
    return agents.find((a) => a.id === r.agentId);
  }
</script>

<div class="overflow-hidden rounded-lg border bg-card">
  <Table.Root>
    <Table.Header>
      <Table.Row>
        <Table.Head>Run</Table.Head><Table.Head>Given</Table.Head><Table.Head>Result</Table.Head>
        {#if several}<Table.Head>Agent</Table.Head>{/if}
        <Table.Head>Started</Table.Head>
      </Table.Row>
    </Table.Header>
    <Table.Body>
      {#each runs as r (r.id)}
        {@const agent = agentOf(r)}
        {@const verdict = verdictOf(agent?.interface?.result as Schema | undefined, r.output?.value)}
        <Table.Row>
          <Table.Cell><a href={href({ view: "run", id: r.id })} data-testid="run-link"><StatusBadge status={STATE[runState(r)] ?? "failed"} /></a></Table.Cell>
          <Table.Cell class="max-w-80 truncate">
            <a class="text-foreground hover:underline" href={href({ view: "run", id: r.id })}>{inputSummary(r.input) ?? "nothing"}</a>
          </Table.Cell>
          <Table.Cell>
            {#if verdict}<span class="text-sm font-medium {TONE[verdict.tone]}">{verdict.value}</span>{:else}<span class="text-muted-foreground">{runState(r)}</span>{/if}
            {#if digest && r.input?.subject?.digest && r.input.subject.digest !== digest}
              <span class="ml-2 text-xs text-warn" title="The skill's files changed after this run read them">changed since</span>
            {/if}
          </Table.Cell>
          {#if several}<Table.Cell class="text-muted-foreground">{agent ? agentLabel(agent) : "removed"}</Table.Cell>{/if}
          <Table.Cell class="text-muted-foreground"><When at={r.createdAt} /></Table.Cell>
        </Table.Row>
      {:else}
        <Table.Row><Table.Cell colspan={4} class="py-6 text-center text-muted-foreground">No run yet.</Table.Cell></Table.Row>
      {/each}
    </Table.Body>
  </Table.Root>
</div>
