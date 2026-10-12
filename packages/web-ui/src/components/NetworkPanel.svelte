<script lang="ts">
  // Network of a session's agent, changed live (A.4): log only ↔ enforce, and the
  // allowed hosts (refused ones, and in log only those enforcing would refuse, offered one click
  // each), applied to its running sandboxes at once,
  // and saved as the agent's own; those the session's model (its account or provider) and the
  // agent's addons require are listed with what requires them. The mode itself (none / filtered / open) is an agent setting, for new
  // sessions. Secrets (E3): handler adds them to requests to their hosts ("key added"); one on its way anywhere else was blocked
  // (a leak, A.3), said at the top: the agent may have been told to send it there.
  import { api } from "../lib/api";
  import type { EgressEvent, Agent, Session } from "../lib/contracts.gen";
  import { sameRun } from "../lib/access";
  import { href } from "../lib/router.svelte";
  import { saveHosts } from "../lib/projects.svelte";
  import { saveAdHoc, sandboxStatus, specOf } from "../lib/agents";
  import { Button } from "$lib/components/ui/button";
  import HostList from "./HostList.svelte";
  import StatusBadge from "./StatusBadge.svelte";

  let {
    agent,
    session,
    onchange,
  }: { agent: Agent; session: Pick<Session, "harness" | "account" | "provider">; onchange: (agent: Agent) => void } = $props();

  // the hosts required in this session: its model's, never the agent's other models' (D.1)
  const required = $derived((agent.models.find((m) => sameRun(m, session)) ?? agent.models[0])?.requiredHosts ?? []);

  let events = $state<EgressEvent[]>([]);
  let error = $state<string | null>(null);
  let saving = $state(false);

  const filtered = $derived(agent.network === "filtered");
  // hosts no entry allows: refused (enforce), or let through in log only ("unlisted")
  const unallowed = $derived(
    [...new Set(events.filter((e) => e.decision === "denied" || e.decision === "unlisted").map((e) => e.host))].sort(),
  );
  const MARK = {
    allowed: { class: "text-ok", glyph: "✓", title: "allowed" },
    denied: { class: "text-danger", glyph: "✕", title: "blocked" },
    unlisted: { class: "text-warn", glyph: "!", title: "let through by log only: would be blocked" },
    injected: { class: "text-ok", glyph: "✓", title: "Handler added a secret to the request" },
    leak: { class: "text-danger", glyph: "✕", title: "blocked: it carried a secret that is not for this host" },
  } as const;
  const leaks = $derived(events.filter((e) => e.decision === "leak"));
  const recent = $derived(events.slice(-15).reverse());
  const learning = $derived(agent.egress === "log-only");
  // what log only let through that no entry allows yet: allowed together before enforcing
  const learned = $derived(
    [...new Set(events.filter((e) => e.decision === "unlisted").map((e) => e.host))].filter((h) => !(agent.allow ?? []).includes(h)).sort(),
  );

  $effect(() => {
    if (agent.network === "none") return; // an open agent reports its secrets only
    const refresh = () =>
      api.egressEvents(agent.id).then(
        (list) => (events = list),
        (e: Error) => (error = e.message),
      );
    void refresh();
    const timer = setInterval(refresh, 3000);
    return () => clearInterval(timer);
  });

  async function apply(change: () => Promise<Agent>): Promise<void> {
    saving = true;
    error = null;
    try {
      onchange(await change());
    } catch (e) {
      error = (e as Error).message;
    } finally {
      saving = false;
    }
  }

  async function saveAllow(allow: string[]): Promise<Agent> {
    if (!agent.projectId) return saveAdHoc(agent.id, { ...specOf(agent), allow });
    await saveHosts(agent, allow);
    return api.agent(agent.id);
  }

  const setEgress = (egress: "enforce" | "log-only") => apply(() => api.setEgress(agent.id, egress));
  const setHosts = (allow: string[]) => apply(() => saveAllow(allow));
  const allowLearnedAndEnforce = () =>
    apply(async () => {
      await saveAllow([...new Set([...(agent.allow ?? []), ...learned])].sort());
      return api.setEgress(agent.id, "enforce");
    });
  </script>

<section class="flex flex-col gap-4 text-sm" data-testid="network-panel">
  <div class="space-y-2">
    <h3 class="text-xs font-medium tracking-wide text-muted-foreground uppercase">Network</h3>
    <div class="flex flex-wrap gap-1.5">
      <StatusBadge status={agent.network} />
      {#if agent.egress}<StatusBadge status={agent.egress} />{/if}
      {#if sandboxStatus(agent) !== "container"}<StatusBadge status={sandboxStatus(agent)} />{/if}
      {#if agent.display}<StatusBadge status="display" />{/if}
    </div>
    {#if agent.network === "open"}
      <p class="text-xs text-muted-foreground">Unfiltered: the agent reaches anything.</p>
    {:else if agent.network === "none"}
      <p class="text-xs text-muted-foreground">No network at all.</p>
    {/if}
    {#if agent.projectId}
      <a class="text-xs text-link hover:underline" href={href({ view: "edit-agent", project: agent.projectId, id: agent.id })}>Change in the agent's settings</a>
    {/if}
  </div>

  {#if filtered}
    <div class="flex flex-col gap-1.5">
      {#if learning}
        <p class="text-xs text-warn">Learning hosts: every host goes through and is logged. Those no entry allows are marked "would be blocked".</p>
        <div class="flex flex-wrap gap-2">
          {#if learned.length}
            <Button size="sm" class="h-auto py-1.5 whitespace-normal text-left" onclick={allowLearnedAndEnforce} disabled={saving} data-testid="egress-allow-learned">
              Allow {learned.length} {learned.length === 1 ? "host" : "hosts"} and block the rest
            </Button>
          {/if}
          <Button variant="outline" size="sm" onclick={() => setEgress("enforce")} disabled={saving} data-testid="egress-toggle">
            {learned.length ? "Block them all" : "Block other hosts"}
          </Button>
        </div>
      {:else}
        <Button variant="outline" size="sm" class="self-start" onclick={() => setEgress("log-only")} disabled={saving} data-testid="egress-toggle">
          Learn hosts
        </Button>
        <p class="text-xs text-muted-foreground">Lets everything through and logs it, to find the hosts it needs.</p>
      {/if}
      <p class="text-xs text-muted-foreground">Applies at once to the running agents.</p>
    </div>
    <div class="space-y-1.5">
      <h3 class="text-xs font-medium tracking-wide text-muted-foreground uppercase">Hosts of this agent</h3>
      <HostList value={agent.allow ?? []} onchange={setHosts} {saving} suggestions={unallowed} empty="None: only the hosts below." />
    </div>
    {#if required.length}
      <details class="text-xs">
        <summary class="cursor-pointer text-muted-foreground">Also allowed ({required.length}): required by its account or provider, its addons</summary>
        <ul class="mt-1.5 space-y-0.5">
          {#each required as r (r.host + r.by)}<li><span class="font-mono">{r.host}</span> <span class="text-muted-foreground">required by {r.by}</span></li>{/each}
        </ul>
      </details>
    {/if}
  {/if}
  {#if error}<p class="text-xs text-danger">{error}</p>{/if}

  {#if leaks.length}
    <div class="space-y-1 rounded-md border border-danger/40 bg-danger/5 p-2.5 text-xs" data-testid="secret-leaks">
      <p class="font-medium text-danger">A secret was on its way to a host it is not for: Handler blocked it.</p>
      <ul class="space-y-0.5">
        {#each [...new Set(leaks.map((e) => `${e.secret} → ${e.host}`))] as line (line)}<li class="font-mono">{line}</li>{/each}
      </ul>
      <p class="text-muted-foreground">The agent may have been told to send it there (by a page or a file it read). Check what it was doing.</p>
    </div>
  {/if}

  {#if agent.network !== "none" && (filtered || recent.length)}
    <div class="space-y-1.5">
      <h3 class="text-xs font-medium tracking-wide text-muted-foreground uppercase">Recent</h3>
      <ul class="space-y-0.5 font-mono text-xs">
        {#each recent as e, i (i)}
          <li class={MARK[e.decision].class} title={MARK[e.decision].title}>
            {MARK[e.decision].glyph} {e.host}{#if e.decision === "unlisted"}<span class="font-sans"> · would be blocked</span>{:else if e.decision === "injected"}<span
                class="font-sans"> · {e.secret} added</span
              >{:else if e.decision === "leak"}<span class="font-sans"> · carried {e.secret}: blocked</span>{/if}
          </li>
        {:else}
          <li class="text-muted-foreground">no traffic yet</li>
        {/each}
      </ul>
    </div>
  {/if}
</section>
