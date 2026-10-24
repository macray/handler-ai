<script lang="ts">
  // Settings → Helpers: the agents given for Handler's needs (D.18), one row each: what it does for
  // Handler, the agent it uses (opened from here) and what it runs on, or Set it up; another agent
  // of yours that fits can be given instead. Each is also met where it acts (Ask, a skill's
  // review, Improve, New app): this is the one place that lists them all.
  import { Button } from "$lib/components/ui/button";
  import { accessLabel } from "../lib/access";
  import { api } from "../lib/api";
  import type { Agent, HandlerNeed } from "../lib/contracts.gen";
  import { href } from "../lib/router.svelte";

  let needs = $state<HandlerNeed[] | null>(null);
  let agents = $state<Agent[]>([]);
  let error = $state<string | null>(null);

  // where each acts, in the person's words
  const WHERE: Record<string, string> = {
    "ask-router": "Ask",
    "skill-review": "a skill's Review",
    "skill-creator": "Skills → Write with an agent",
    "prompt-writer": "a job's Improve",
    "app-creator": "Apps → Make your own",
  };

  async function load(): Promise<void> {
    try {
      [needs, agents] = await Promise.all([api.handlerNeeds(), api.agents()]);
      error = null;
    } catch (e) {
      error = (e as Error).message;
    }
  }

  $effect(() => void load());

  async function give(need: HandlerNeed, agentId: string): Promise<void> {
    try {
      await api.giveHandlerNeedAgent(need.name, agentId);
      await load();
    } catch (e) {
      error = (e as Error).message;
    }
  }
</script>

<section class="space-y-3" data-testid="helpers">
  <p class="max-w-2xl text-sm text-muted-foreground">
    Agents Handler's own features use. Each is set up the first time its feature needs it (you choose its model), and is yours to change like any agent.
  </p>
  {#if error}<p class="text-sm text-danger">{error}</p>{/if}
  <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
    {#each needs ?? [] as need (need.name)}
      {@const given = need.agentId ? agents.find((a) => a.id === need.agentId) : undefined}
      {@const others = (need.fits ?? []).filter((id) => id !== need.agentId)}
      <li class="flex flex-wrap items-start gap-3 px-4 py-3.5" data-testid="helper">
        <div class="min-w-0 flex-1 space-y-0.5">
          <p class="font-medium">{need.definition.agentName} <span class="text-xs font-normal text-muted-foreground">· used by {WHERE[need.name] ?? need.name}</span></p>
          <p class="text-muted-foreground">{need.description}</p>
          {#if given}
            <p class="fact">
              <a class="text-link hover:underline" href={href({ view: "agent", id: given.id })}>{given.name ?? need.definition.agentName}</a> · {given.modelAlone
                ? "the model alone · "
                : ""}{accessLabel(given.model)}
            </p>
          {/if}
        </div>
        {#if !given}
          <Button size="sm" variant="outline" href={href({ view: "set-up-helper", need: need.name })} data-testid="helper-set-up">Set it up</Button>
        {:else if others.length}
          <select
            class="h-8 rounded-lg border bg-background px-2 text-sm"
            aria-label={`another agent for the ${need.definition.agentName}`}
            value=""
            onchange={(e) => e.currentTarget.value && give(need, e.currentTarget.value)}
          >
            <option value="" disabled>Give another…</option>
            {#each others as id (id)}<option value={id}>{agents.find((a) => a.id === id)?.name ?? id}</option>{/each}
          </select>
        {/if}
      </li>
    {/each}
  </ul>
</section>
