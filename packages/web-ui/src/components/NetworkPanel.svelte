<script lang="ts">
  // Network of a session's agent, changed live (A.4): log only ↔ enforce, and the
  // allowed hosts (refused ones, and in log only those enforcing would refuse, offered one click
  // each), applied to its running sandboxes at once,
  // and saved as the agent's own; those the session's model (its account or provider) and the
  // agent's addons require are listed with what requires them. The hosts the person keeps
  // blocked (A.3: refused, the agent told not to ask for them), each one allowed or removed
  // (undecided again), and refused hosts not decided yet offered to keep blocked; a host saved in
  // one list leaves the other. The mode itself (none / filtered / open) is an agent setting, for new
  // sessions. Secrets (E3): handler adds them to requests to their hosts ("key added"); one on its way anywhere else was blocked
  // (a leak, A.3), said at the top: the agent may have been told to send it there. Recent connections
  // say what became of each request: reached, could not connect (why), blocked or kept blocked.
  import { api } from "../lib/api";
  import type { EgressEvent, Agent, Session } from "../lib/contracts.gen";
  import { sameRun } from "../lib/access";
  import { href } from "../lib/router.svelte";
  import { saveHosts } from "../lib/projects.svelte";
  import { recentLines, withList, type Outcome, type OwnHosts } from "../lib/hosts";
  import { sandboxStatus } from "../lib/agents";
  import { Button } from "$lib/components/ui/button";
  import HostList from "./HostList.svelte";
  import StatusBadge from "./StatusBadge.svelte";

  let {
    agent,
    session,
    onchange,
  }: { agent: Agent; session: Pick<Session, "harness" | "account" | "provider">; onchange: (agent: Agent) => void } = $props();

  // the hosts required in this session: its model's when it runs with the agent's (D.1); one
  // picked for it alone has its own allowed too (D.19)
  const required = $derived(sameRun(agent.model, session) ? (agent.model.requiredHosts ?? []) : []);

  let events = $state<EgressEvent[]>([]);
  let error = $state<string | null>(null);
  let saving = $state(false);

  const filtered = $derived(agent.network === "filtered");
  const own = $derived<OwnHosts>({ allow: agent.allow ?? [], blocked: agent.blocked ?? [] });
  // hosts no entry allows and not kept blocked: refused (enforce), or let through in log only
  // ("unlisted")
  const unallowed = $derived(
    [...new Set(events.filter((e) => e.decision === "denied" || e.decision === "unlisted").map((e) => e.host))]
      .filter((h) => !own.blocked.includes(h))
      .sort(),
  );
  // refused, and the person has not said yet whether they stay blocked
  const undecided = $derived(
    [...new Set(events.filter((e) => e.decision === "denied").map((e) => e.host))].filter((h) => !own.blocked.includes(h) && !own.allow.includes(h)).sort(),
  );
  // each line's mark: what became of the request, said in words beside the host
  const MARK: Record<Outcome, { class: string; glyph: string; title: string }> = {
    reached: { class: "text-ok", glyph: "✓", title: "allowed, and the host answered" },
    "could not connect": { class: "text-danger", glyph: "✗", title: "allowed, but the host did not answer" },
    blocked: { class: "text-danger", glyph: "⛔", title: "blocked by the network filter" },
    "kept blocked": { class: "text-danger", glyph: "⛔", title: "blocked: you keep it blocked" },
    allowed: { class: "text-muted-foreground", glyph: "·", title: "allowed, connecting" },
    "would be blocked": { class: "text-warn", glyph: "!", title: "let through by log only: would be blocked" },
    held: { class: "text-warn", glyph: "…", title: "held a few seconds for your answer" },
    "secret added": { class: "text-ok", glyph: "✓", title: "Handler added a secret to the request" },
    "secret blocked": { class: "text-danger", glyph: "✕", title: "blocked: it carried a secret that is not for this host" },
  };
  const NOTE: Record<Outcome, (detail?: string) => string> = {
    reached: () => " · reached",
    "could not connect": (why) => ` · could not connect${why ? `: ${why}` : ""}`,
    blocked: () => " · blocked",
    "kept blocked": () => " · kept blocked",
    allowed: () => " · allowed",
    "would be blocked": () => " · would be blocked",
    held: () => " · waited for your answer",
    "secret added": (name) => ` · ${name} added`,
    "secret blocked": (name) => ` · carried ${name}: blocked`,
  };
  const leaks = $derived(events.filter((e) => e.decision === "leak"));
  const recent = $derived(recentLines(events, own.blocked));
  const learning = $derived(agent.egress === "log-only");
  // what log only let through that no entry allows yet: allowed together before enforcing
  const learned = $derived(
    [...new Set(events.filter((e) => e.decision === "unlisted").map((e) => e.host))].filter((h) => !own.allow.includes(h) && !own.blocked.includes(h)).sort(),
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

  const save = (list: keyof OwnHosts, next: string[]): Promise<Agent> => saveHosts(agent, withList(own, list, next));

  const setEgress = (egress: "enforce" | "log-only") => apply(() => api.setEgress(agent.id, egress));
  const setHosts = (allow: string[]) => apply(() => save("allow", allow));
  const allowHost = (host: string) => apply(() => save("allow", [...new Set([...own.allow, host])].sort()));
  const keepBlocked = (host: string) => apply(() => save("blocked", [...new Set([...own.blocked, host])].sort()));
  const removeBlocked = (host: string) => apply(() => save("blocked", own.blocked.filter((h) => h !== host)));
  const allowLearnedAndEnforce = () =>
    apply(async () => {
      await save("allow", [...new Set([...own.allow, ...learned])].sort());
      return api.setEgress(agent.id, "enforce");
    });
  </script>

<section class="flex flex-col gap-4 text-sm" data-testid="network-panel">
  <div class="space-y-2">
    <h3 class="section-label">Network</h3>
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
        <p class="text-xs text-warn">Learning the sites it needs: every site goes through and is logged. Those no entry allows are marked "would be blocked".</p>
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
          Learn the sites it needs
        </Button>
        <p class="text-xs text-muted-foreground">Lets everything through and logs it, to find the hosts it needs.</p>
      {/if}
      <p class="text-xs text-muted-foreground">Applies at once to the running agents.</p>
    </div>
    <div class="space-y-1.5">
      <h3 class="section-label">Hosts of this agent</h3>
      <HostList value={agent.allow ?? []} onchange={setHosts} {saving} suggestions={unallowed} />
    </div>
    <div class="space-y-1.5" data-testid="kept-blocked">
      <h3 class="section-label">Kept blocked</h3>
      <p class="text-xs text-muted-foreground">Blocked like any host not allowed, and the agent is told not to ask for them.</p>
      <ul class="space-y-1">
        {#each own.blocked as host (host)}
          <li class="flex flex-wrap items-center gap-1.5" data-testid="blocked-entry">
            <span class="font-mono text-xs">{host}</span>
            <Button variant="outline" size="sm" class="h-6 text-xs" disabled={saving} onclick={() => allowHost(host)} aria-label={`allow ${host}`}>Allow</Button>
            <Button variant="ghost" size="sm" class="h-6 text-xs" disabled={saving} onclick={() => removeBlocked(host)} aria-label={`remove ${host} from the hosts kept blocked`}>Remove</Button>
          </li>
        {:else}
          <li class="text-xs text-muted-foreground">None.</li>
        {/each}
      </ul>
      {#if undecided.length}
        <p class="text-xs text-muted-foreground">Blocked recently, not decided yet:</p>
        <ul class="flex flex-wrap gap-1.5">
          {#each undecided as host (host)}
            <li>
              <Button variant="outline" size="sm" class="h-6 font-mono text-xs" disabled={saving} onclick={() => keepBlocked(host)} aria-label={`keep ${host} blocked`} data-testid="keep-blocked">
                Keep {host} blocked
              </Button>
            </li>
          {/each}
        </ul>
      {/if}
    </div>
    {#if required.length}
      <details class="text-xs">
        <summary class="cursor-pointer text-muted-foreground">Also allowed ({required.length}): required by its account or provider, its tools</summary>
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
      <h3 class="section-label">Recent</h3>
      <ul class="space-y-0.5 font-mono text-xs">
        {#each recent as line, i (i)}
          <li class={MARK[line.outcome].class} title={MARK[line.outcome].title} data-testid="recent-connection" data-outcome={line.outcome}>
            {MARK[line.outcome].glyph} {line.host}{#if NOTE[line.outcome](line.detail)}<span class="font-sans">{NOTE[line.outcome](line.detail)}</span>{/if}
          </li>
        {:else}
          <li class="text-muted-foreground">no traffic yet</li>
        {/each}
      </ul>
    </div>
  {/if}
</section>
