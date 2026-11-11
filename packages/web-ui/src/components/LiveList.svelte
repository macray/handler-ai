<script lang="ts">
  // The terminals open now (`handler terminal`, D.16: their page, the network) of the agents
  // outside projects working in a project's folder (run with --anyway): shown by the project.
  import SquareTerminal from "@lucide/svelte/icons/square-terminal";
  import When from "./When.svelte";
  import { accessLabel } from "../lib/access";
  import { terminalsOf } from "../lib/agents";
  import type { Agent } from "../lib/contracts.gen";
  import { agentLabel } from "../lib/projects.svelte";
  import { href } from "../lib/router.svelte";

  let { agents }: { agents: Agent[] } = $props();

  const terminals = $derived(terminalsOf(agents));
</script>

{#if terminals.length}
  <section class="space-y-2">
    <h2 class="section-label">Live</h2>
    <ul class="divide-y overflow-hidden rounded-lg border bg-card" data-testid="live-list">
      {#each terminals as t (t.conn.id)}
        <li>
          <a class="flex w-full items-center gap-3 px-3 py-2 text-sm text-foreground no-underline hover:bg-accent/50" href={href({ view: "terminal", agent: t.agent.id, connection: t.conn.id })} data-testid="live-terminal">
            <span class="flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground"><SquareTerminal class="size-3.5" />terminal</span>
            <span class="shrink-0 font-medium">{agentLabel(t.agent)}</span>
            <span class="min-w-0 flex-1 truncate text-muted-foreground">{accessLabel(t.conn.terminal)}</span>
            <span class="shrink-0 text-xs text-warn" title="Started with --anyway: an agent outside the project, its own settings">outside the project</span>
            <span class="shrink-0 text-xs text-muted-foreground"><When at={t.conn.since} /></span>
          </a>
        </li>
      {/each}
    </ul>
  </section>
{/if}
