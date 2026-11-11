<script lang="ts">
  // A terminal of an agent (`handler terminal`, D.16): the harness's own program runs in the terminal
  // that started it, not here; what is here is its network, changed live (A.4). handlerd knows it
  // until it ends, or until handlerd restarts (the program goes on, unknown to the new one).
  import NetworkPanel from "../components/NetworkPanel.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import When from "../components/When.svelte";
  import { accessLabel } from "../lib/access";
  import { api } from "../lib/api";
  import type { Agent } from "../lib/contracts.gen";
  import { agentLabel } from "../lib/projects.svelte";
  import { href } from "../lib/router.svelte";

  let { agent: agentId, connection }: { agent: string; connection: string } = $props();

  let agent = $state<Agent | null>(null);
  let error = $state<string | null>(null);

  $effect(() => {
    const load = () =>
      api.agent(agentId).then(
        (a) => ((agent = a), (error = null)),
        (e: Error) => (error = e.message),
      );
    void load();
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
  });

  const conn = $derived(agent?.connections.find((c) => c.id === connection && c.terminal));
  const parent = $derived(
    agent?.projectId
      ? { label: "Project", href: href({ view: "project", id: agent.projectId }) }
      : { label: "Agent", href: href({ view: "agent", id: agentId }) },
  );
</script>

<PageHeader width="max-w-2xl" title={agent ? `Terminal · ${agentLabel(agent)}` : "Terminal"} {parent} />
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-2xl space-y-6 px-8 py-10">
    {#if error}<p class="text-sm text-danger">{error}</p>{/if}
    {#if agent && conn?.terminal}
      <div class="space-y-1.5" data-testid="terminal-info">
        <p class="text-xs text-muted-foreground">{accessLabel(conn.terminal)} · started <When at={conn.since} /></p>
        <p class="text-sm text-muted-foreground">
          It runs in the terminal where <code>handler terminal</code> started it: you talk to it there, and closing that
          terminal stops it. Its network is changed here, at once.
        </p>
      </div>
      <div class="rounded-lg border bg-card p-4">
        <NetworkPanel
          {agent}
          session={{ harness: conn.terminal.harness ?? "", account: conn.terminal.account, provider: conn.terminal.provider }}
          onchange={(a) => (agent = a)}
        />
      </div>
    {:else if agent}
      <p class="text-sm text-muted-foreground" data-testid="terminal-gone">
        This terminal is not running any more, or handlerd restarted since it started: the program may still run in its
        terminal, but handlerd no longer knows it.
      </p>
    {:else if !error}
      <p class="text-sm text-muted-foreground">Loading…</p>
    {/if}
  </div>
</div>
