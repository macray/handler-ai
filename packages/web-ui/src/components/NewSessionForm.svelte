<script lang="ts">
  // A new session, from Running ("+": its new-session pane; the empty stage): the dark console's
  // Project ▾ · Agent ▾ · Model ▾ · Start. No prompt: Start makes the pane the session, its
  // composer focused, where the first message is typed. The model is optional: the agent's own,
  // another for this session only (WhoWorksChoice). Defaults: the project given (the chip chosen),
  // else the last one used here, and its agent used last. An open select lists its options in
  // place, pushing what follows down: it never covers another. The agents listed are those
  // started with a message (a brief's or a job's form is on their project's page).
  import Check from "@lucide/svelte/icons/check";
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import Play from "@lucide/svelte/icons/play";
  import { Button } from "$lib/components/ui/button";
  import WhoWorksChoice from "./WhoWorksChoice.svelte";
  import { accessLabel } from "../lib/access";
  import { api } from "../lib/api";
  import { areas } from "../lib/areas.svelte";
  import type { Agent, ModelAccess } from "../lib/contracts.gen";
  import { agentLabel, byName, makeModelDefault, projects } from "../lib/projects.svelte";
  import { href } from "../lib/router.svelte";
  import { sessions, type LiveSession } from "../lib/sessions.svelte";

  let { project: given, onstarted }: { project?: string | null; onstarted: (session: LiveSession) => void } = $props();

  const LAST = "handler.running.last"; // the project ("" outside projects) and agent used last here
  const OUTSIDE = "";

  function lastUsed(): { project?: string; agent?: string } {
    try {
      return JSON.parse(localStorage.getItem(LAST) ?? "{}") as { project?: string; agent?: string };
    } catch {
      return {};
    }
  }

  // the agents outside projects (`handler run`, `handler terminal` in a folder): one more place
  let outside = $state<Agent[]>([]);
  api.agents().then(
    (all) => (outside = all.filter((a) => !a.projectId && !a.chat && !a.interface)),
    () => {},
  );

  type Place = { id: string; name: string; area?: string | null; agents: Agent[] };
  const places = $derived<Place[]>([
    ...byName(projects.list).map((p) => ({ id: p.id, name: p.name, area: p.area, agents: p.agents.filter((a) => !a.interface) })),
    ...(outside.length ? [{ id: OUTSIDE, name: "Agents outside projects", agents: outside }] : []),
  ]);

  const last = lastUsed();
  let placeId = $state<string | undefined>(undefined);
  let agentId = $state<string | undefined>(undefined);
  const place = $derived(places.find((p) => p.id === (placeId ?? given ?? last.project)) ?? places[0]);
  const agent = $derived.by(() => {
    const list = place?.agents ?? [];
    const project = place ? projects.get(place.id) : undefined;
    return list.find((a) => a.id === agentId) ?? list.find((a) => a.id === last.agent) ?? list.find((a) => a.id === project?.defaultAgent) ?? list[0];
  });
  let model = $state<ModelAccess | undefined>(); // another for this session; undefined: the agent's own
  $effect(() => {
    void agent?.id;
    model = undefined;
  });

  let open = $state<"project" | "agent" | null>(null);
  let starting = $state(false);
  let error = $state<string | null>(null);

  async function start(): Promise<void> {
    if (!agent) return;
    starting = true;
    error = null;
    try {
      const session = await sessions.start(agent, undefined, model);
      try {
        localStorage.setItem(LAST, JSON.stringify({ project: place?.id, agent: agent.id }));
      } catch {
        /* not remembered */
      }
      onstarted(session);
    } catch (e) {
      error = (e as Error).message;
    } finally {
      starting = false;
    }
  }
</script>

<form
  class="new-session"
  onsubmit={(e) => {
    e.preventDefault();
    void start();
  }}
  data-testid="new-session-form"
>
  {#if !places.length}
    <p class="text-sm text-muted-foreground">No project yet: <a class="text-link hover:underline" href={href({ view: "edit-project" })} data-testid="new-session-new-project">New project</a>, then start its agents here.</p>
  {:else}
    <p class="label" id="new-session-project-label">Project</p>
    <button type="button" class="select" aria-labelledby="new-session-project-label" aria-expanded={open === "project"} onclick={() => (open = open === "project" ? null : "project")} data-testid="new-session-project">
      <span class="swatch {areas.colorClass(place?.area)}" aria-hidden="true"></span><span class="value">{place?.name}</span><ChevronDown class="size-3.5 opacity-60" />
    </button>
    {#if open === "project"}
      <ul class="options" role="listbox" aria-labelledby="new-session-project-label">
        {#each places as p (p.id)}
          <li role="option" aria-selected={p.id === place?.id}>
            <button type="button" onclick={() => ((placeId = p.id), (agentId = undefined), (open = null))} data-testid="new-session-project-option"
              ><span class="tick">{#if p.id === place?.id}<Check class="size-3.5" />{/if}</span><span class="swatch {areas.colorClass(p.area)}" aria-hidden="true"></span>{p.name}<span class="note">{p.agents.length} agent{p.agents.length === 1 ? "" : "s"}</span></button
            >
          </li>
        {/each}
      </ul>
    {/if}

    <p class="label" id="new-session-agent-label">Agent</p>
    {#if place?.agents.length}
      <button type="button" class="select" aria-labelledby="new-session-agent-label" aria-expanded={open === "agent"} onclick={() => (open = open === "agent" ? null : "agent")} data-testid="new-session-agent">
        <span class="value">{agent ? agentLabel(agent) : ""}</span><ChevronDown class="size-3.5 opacity-60" />
      </button>
      {#if open === "agent"}
        <ul class="options" role="listbox" aria-labelledby="new-session-agent-label">
          {#each place.agents as a (a.id)}
            <li role="option" aria-selected={a.id === agent?.id}>
              <button type="button" onclick={() => ((agentId = a.id), (open = null))} data-testid="new-session-agent-option"
                ><span class="tick">{#if a.id === agent?.id}<Check class="size-3.5" />{/if}</span>{agentLabel(a)}<span class="note">{accessLabel(a.model)}</span></button
              >
            </li>
          {/each}
        </ul>
      {/if}
    {:else}
      <p class="text-sm text-muted-foreground">No agent to talk to in {place?.name}: add one on its page.</p>
    {/if}

    {#if agent}
      <p class="label">Model</p>
      <div class="model">
        {#key agent.id}<WhoWorksChoice {agent} bind:value={model} ondefault={(m) => makeModelDefault(agent, m).then(() => void projects.refresh())} />{/key}
      </div>
    {/if}

    {#if error}<p class="text-sm text-danger" data-testid="new-session-error">{error}</p>{/if}
    <Button type="submit" class="start" disabled={!agent || starting} data-testid="new-session-start"><Play />{starting ? "Starting…" : "Start"}</Button>
  {/if}
</form>

<style>
  .new-session {
    display: flex;
    flex-direction: column;
    width: 100%;
    max-width: 19rem;
    margin: auto;
    font-family: var(--mono);
    font-size: 0.8125rem;
  }
  .label {
    margin: 0.9rem 0 0.35rem;
    font-family: var(--sans);
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--muted-foreground);
  }
  .label:first-child {
    margin-top: 0;
  }
  .select {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    width: 100%;
    padding: 0.5rem 0.7rem;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--background);
    text-align: left;
  }
  .select[aria-expanded="true"] {
    border-color: var(--primary);
    border-bottom-left-radius: 0;
    border-bottom-right-radius: 0;
  }
  .value {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  /* in place, under its field: what follows moves down */
  .options {
    margin: 0;
    padding: 0.25rem;
    list-style: none;
    border: 1px solid var(--primary);
    border-top: 0;
    border-radius: 0 0 6px 6px;
    background: var(--background);
  }
  .options button {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    width: 100%;
    padding: 0.35rem 0.5rem;
    border-radius: 4px;
    text-align: left;
  }
  .options button:hover {
    background: var(--muted);
  }
  .tick {
    width: 0.9rem;
    flex: none;
    color: var(--primary);
  }
  .note {
    margin-left: auto;
    padding-left: 1rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--muted-foreground);
    font-size: 0.75rem;
  }
  .swatch {
    width: 0.5rem;
    height: 0.5rem;
    flex: none;
    border-radius: 2px;
    background: var(--area, var(--muted-foreground));
  }
  .model {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
  }
  .new-session :global(.start) {
    margin-top: 1.1rem;
    width: 100%;
  }
</style>
