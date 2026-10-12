<script lang="ts">
  // What runs now, apart from what can be started: live sessions (opened here) and terminals
  // (`handler terminal`, D.16: their page, the network). Shown by a project and by the Agents page.
  import SquareTerminal from "@lucide/svelte/icons/square-terminal";
  import SessionStatus from "./SessionStatus.svelte";
  import When from "./When.svelte";
  import { accessLabel } from "../lib/access";
  import { terminalsOf } from "../lib/agents";
  import type { Agent, Session } from "../lib/contracts.gen";
  import { agentLabel } from "../lib/projects.svelte";
  import { href, navigate } from "../lib/router.svelte";
  import { sessions } from "../lib/sessions.svelte";

  let {
    agents,
    list,
    outside = false,
  }: {
    agents: Agent[]; // whose terminals are listed, and the agents of the sessions
    list: Session[]; // sessions, any state: the running ones are listed
    outside?: boolean; // mark the agents outside projects (a project's page: run with --anyway)
  } = $props();

  const live = $derived(list.filter((s) => (s.state === "running" || s.state === "starting") && !sessions.stopping.has(s.id)));
  const terminals = $derived(terminalsOf(agents));

  function open(s: Session): void {
    const on = agents.find((a) => a.id === s.agentId);
    if (on) navigate({ view: "session", key: sessions.open(s, on).key });
  }
</script>

{#if live.length || terminals.length}
  <section class="space-y-2">
    <h2 class="text-xs font-medium tracking-wide text-muted-foreground uppercase">Live</h2>
    <ul class="divide-y overflow-hidden rounded-lg border bg-card" data-testid="live-list">
      {#each live as s (s.id)}
        {@const on = agents.find((a) => a.id === s.agentId)}
        <li>
          <button type="button" class="flex w-full cursor-pointer items-center gap-3 px-3 py-2 text-left text-sm hover:bg-accent/50" onclick={() => open(s)}>
            <SessionStatus status={s.pendingPermissions ? "needs-you" : s.busy ? "working" : s.state === "starting" ? "starting" : "idle"} label />
            <span class="shrink-0 font-medium">{on ? agentLabel(on) : s.harness}</span>
            <span class="min-w-0 flex-1 truncate text-muted-foreground">{s.title ?? "—"}</span>
            <span class="shrink-0 text-xs text-muted-foreground"><When at={s.lastActivityAt} /></span>
          </button>
        </li>
      {/each}
      {#each terminals as t (t.conn.id)}
        <li>
          <a class="flex w-full items-center gap-3 px-3 py-2 text-sm text-foreground no-underline hover:bg-accent/50" href={href({ view: "terminal", agent: t.agent.id, connection: t.conn.id })} data-testid="live-terminal">
            <span class="flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground"><SquareTerminal class="size-3.5" />terminal</span>
            <span class="shrink-0 font-medium">{agentLabel(t.agent)}</span>
            <span class="min-w-0 flex-1 truncate text-muted-foreground">{accessLabel(t.conn.terminal)}</span>
            {#if outside && !t.agent.projectId}<span class="shrink-0 text-xs text-warn" title="Started with --anyway: an agent outside the project, its own settings">outside the project</span>{/if}
            <span class="shrink-0 text-xs text-muted-foreground"><When at={t.conn.since} /></span>
          </a>
        </li>
      {/each}
    </ul>
  </section>
{/if}
