<script lang="ts">
  // Agents outside projects: the agents of no project that are not Chat's, laid out as a project's page
  // (its agents on the left, the chosen one's workspace beside them), without what only a project
  // has (its folder, caches, settings). Three groups: yours (each in its folder, or a brief or a
  // job with none); those Handler or your apps use (D.18, H.2), each saying for what; and those
  // the command line made outside projects (no name: called by their folder), folded. Who you talk
  // to with no folder is in Chat (their `chat`, D.1); the agents set up for an app are its
  // parts, on its page only (H.14).
  import AppWindow from "@lucide/svelte/icons/app-window";
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import Plus from "@lucide/svelte/icons/plus";
  import Sparkles from "@lucide/svelte/icons/sparkles";
  import SquareTerminal from "@lucide/svelte/icons/square-terminal";
  import { Button } from "$lib/components/ui/button";
  import AgentPick from "../components/AgentPick.svelte";
  import AgentWorkspace from "../components/AgentWorkspace.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import SessionStatus from "../components/SessionStatus.svelte";
  import { accessLabel } from "../lib/access";
  import { folderName, whereLabel } from "../lib/agents";
  import { api } from "../lib/api";
  import { usedFor } from "../lib/apps";
  import type { Agent, App, AutomationView, HandlerNeed, Session } from "../lib/contracts.gen";
  import { agentLabel } from "../lib/projects.svelte";
  import { href, navigate } from "../lib/router.svelte";
  import { sessions, type SessionStatus as Status } from "../lib/sessions.svelte";

  let { agent: chosenId }: { agent?: string } = $props();

  let agents = $state<Agent[]>([]);
  let list = $state<Session[]>([]); // their sessions and runs, any state
  let automations = $state<AutomationView[]>([]);
  let needs = $state<HandlerNeed[]>([]);
  let apps = $state<App[]>([]);
  let loaded = $state(false);
  let error = $state<string | null>(null);
  let unfolded = $state(false); // the command line's agents shown

  $effect(() => {
    void sessions.stopping.size; // a session closed here has stopped: load again
    const load = () =>
      Promise.all([api.agents(), api.sessions(), api.automations().catch(() => []), api.handlerNeeds().catch(() => []), api.apps().catch(() => [])]).then(
        ([all, s, auto, b, a]) => {
          agents = all.filter((x) => !x.projectId && !x.app && !x.chat).sort((x, y) => (y.lastUsedAt ?? y.createdAt).localeCompare(x.lastUsedAt ?? x.createdAt));
          list = s.filter((x) => !x.projectId);
          automations = auto;
          needs = b;
          apps = a;
          loaded = true;
        },
        (e: Error) => (error = e.message),
      );
    void load();
    const timer = setInterval(load, 5000); // sessions and terminals come and go
    return () => clearInterval(timer);
  });

  const uses = $derived(new Map(agents.map((a) => [a.id, usedFor(a, needs, apps)])));
  const used = $derived(agents.filter((a) => uses.get(a.id)?.length));
  const commandLine = $derived(agents.filter((a) => !a.name && !uses.get(a.id)?.length));
  const yours = $derived(agents.filter((a) => a.name && !uses.get(a.id)?.length));
  const agent = $derived(agents.find((a) => a.id === chosenId) ?? yours[0] ?? used[0] ?? commandLine[0]);
  const showCommandLine = $derived(unfolded || commandLine.some((a) => a.id === agent?.id));

  const isLive = (s: Session) => (s.state === "running" || s.state === "starting") && !sessions.stopping.has(s.id);
  const waiting = $derived(list.filter((s) => isLive(s) && s.pendingPermissions));

  // an agent's dot in the list: waits for you, works, or open
  function dotOf(a: Agent): Status | null {
    const open = list.filter((s) => s.agentId === a.id && isLive(s));
    if (open.some((s) => s.pendingPermissions)) return "needs-you";
    if (open.some((s) => s.busy)) return "working";
    return open.length ? "idle" : null;
  }

  function choose(a: Agent): void {
    navigate({ view: "agents", agent: a.id }, true);
  }

  function open(s: Session): void {
    const on = agents.find((a) => a.id === s.agentId);
    if (on) navigate({ view: "session", key: sessions.open(s, on).key });
  }
</script>

{#snippet pick(a: Agent, about: string)}
  <AgentPick agent={a} chosen={a.id === agent?.id} dot={dotOf(a)} {about} onclick={() => choose(a)} />
{/snippet}

<PageHeader title="Agents outside projects" parent={{ label: "Projects", href: href({ view: "projects" }) }} />
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-6xl space-y-5 px-8 py-8">
    {#if error}<p class="text-sm text-danger" data-testid="outside-error">{error}</p>{/if}

    <!-- what waits for you, whichever agent is chosen -->
    {#each waiting as s (s.id)}
      {@const on = agents.find((a) => a.id === s.agentId)}
      <div class="flex items-center gap-3 rounded-lg bg-warn/10 px-3 py-2 text-sm" data-testid="project-waiting">
        <SessionStatus status="needs-you" />
        <span class="min-w-0 flex-1 truncate"><b class="font-semibold">{on ? agentLabel(on) : s.harness}</b> needs you in “{s.title ?? "untitled"}”</span>
        <Button variant="outline" size="sm" onclick={() => open(s)}>Open</Button>
      </div>
    {/each}

    {#if loaded && !agents.length}
      <div class="space-y-3 rounded-lg border border-dashed px-6 py-8 text-center text-sm text-muted-foreground" data-testid="outside-empty">
        <p>No agent here yet. Make one for a folder that is no project's (your notes, a weekly report); those the command line makes outside a project come here too.</p>
        <Button size="sm" href={href({ view: "edit-ad-hoc" })} data-testid="new-ad-hoc"><Plus />New agent</Button>
      </div>
    {:else if agents.length}
      <div class="grid items-start gap-6 md:grid-cols-[15rem_minmax(0,1fr)]">
        <nav class="space-y-0.5" aria-label="agents">
          {#if yours.length}
            <h2 class="section-label px-2.5 pb-1.5">Yours</h2>
            <ul class="space-y-0.5" data-testid="outside-yours">
              {#each yours as a (a.id)}{@render pick(a, a.description ?? (a.scope ? `in ${folderName(a.scope)}` : whereLabel(a)))}{/each}
            </ul>
          {/if}
          {#if used.length}
            <h2 class="section-label px-2.5 pt-4 pb-1.5">For Handler and your apps</h2>
            <ul class="space-y-0.5" data-testid="outside-used">
              {#each used as a (a.id)}{@render pick(a, (uses.get(a.id) ?? []).map((r) => r.label).join(", "))}{/each}
            </ul>
          {/if}
          {#if commandLine.length}
            <button
              type="button"
              class="mt-3 flex w-full cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-accent/60"
              aria-expanded={showCommandLine}
              onclick={() => (unfolded = !showCommandLine)}
              data-testid="outside-command-line"
            >
              <SquareTerminal class="size-3.5" />From the command line · {commandLine.length}
              <ChevronDown class="ml-auto size-3.5 transition-transform {showCommandLine ? 'rotate-180' : ''}" />
            </button>
            {#if showCommandLine}
              <ul class="space-y-0.5">
                {#each commandLine as a (a.id)}{@render pick(a, accessLabel(a.model))}{/each}
              </ul>
            {/if}
          {/if}
          <Button variant="ghost" size="sm" class="mt-1 w-full justify-start text-muted-foreground" href={href({ view: "edit-ad-hoc" })} data-testid="new-ad-hoc"><Plus />New agent</Button>
        </nav>

        {#if agent}
          <AgentWorkspace {agent} {list} {automations} edit={href({ view: "edit-ad-hoc", id: agent.id })}>
            {#snippet tags()}
              {#each uses.get(agent.id) ?? [] as r (r.label)}
                <span class="inline-flex items-center gap-1 rounded-[5px] bg-muted px-1.5 py-px text-xs font-medium text-muted-foreground" data-testid="agent-role"
                  >{#if r.app}<AppWindow class="size-3" />{:else}<Sparkles class="size-3" />{/if}{r.label}</span
                >
              {/each}
            {/snippet}
          </AgentWorkspace>
        {/if}
      </div>
    {:else if !error}
      <p class="text-sm text-muted-foreground">Loading…</p>
    {/if}
  </div>
</div>
