<script lang="ts">
  // The agents Handler asks to work on skills (D.18, its needs): the skill reviewer (a skill's page:
  // Review) and skill creator (New skill → With an agent, Edit with an agent), each a row: the one
  // given, or the way to set one up, and the others of yours that fit. They are your agents,
  // outside projects.
  import Plus from "@lucide/svelte/icons/plus";
  import { Button } from "$lib/components/ui/button";
  import * as NativeSelect from "$lib/components/ui/native-select";
  import SettingRow from "./SettingRow.svelte";
  import { api } from "../lib/api";
  import type { Agent, HandlerNeed } from "../lib/contracts.gen";
  import { agentLabel } from "../lib/projects.svelte";
  import { href } from "../lib/router.svelte";

  // Handler's needs for skills, in this order
  const FOR_SKILLS = ["skill-review", "skill-creator"];

  let needs = $state<HandlerNeed[]>([]);
  let agents = $state<Agent[]>([]);
  let error = $state<string | null>(null);

  const rows = $derived(FOR_SKILLS.flatMap((n) => needs.filter((b) => b.name === n)));
  const label = (id: string) => {
    const a = agents.find((x) => x.id === id);
    return a ? agentLabel(a) : id;
  };

  async function load(): Promise<void> {
    try {
      [needs, agents] = await Promise.all([api.handlerNeeds(), api.agents()]);
    } catch (e) {
      error = (e as Error).message;
    }
  }

  $effect(() => {
    void load();
  });

  /** Handler's feature uses another of the agents that fit (D.18). */
  async function give(b: HandlerNeed, agentId: string): Promise<void> {
    error = null;
    try {
      await api.giveHandlerNeedAgent(b.name, agentId);
      await load();
    } catch (e) {
      error = (e as Error).message;
    }
  }
</script>

{#if rows.length}
  <section class="space-y-3 pt-6" data-testid="skill-agents">
    <div>
      <h2 class="text-base font-semibold">Agents for skills</h2>
      <p class="text-sm text-muted-foreground">Handler asks an agent to review a skill, or to write one with you. Choose which: they are your agents, outside projects.</p>
    </div>
    {#if error}<p class="text-sm text-danger">{error}</p>{/if}
    <div class="divide-y overflow-hidden rounded-[10px] border bg-card shadow-panel">
      {#each rows as b (b.name)}
        {@const fits = b.fits ?? []}
        <SettingRow label={b.definition.agentName} hint={b.description} for={`skill-agent-${b.name}-choice`} data-testid={`skill-agent-${b.name}`}>
          {#if b.agentId}
            <NativeSelect.Root
              id={`skill-agent-${b.name}-choice`}
              value={b.agentId}
              onchange={(e) => give(b, e.currentTarget.value)}
              class="w-full"
              data-testid={`skill-agent-${b.name}-choice`}
            >
              {#each [b.agentId, ...fits.filter((id) => id !== b.agentId)] as id (id)}<NativeSelect.Option value={id}>{label(id)}</NativeSelect.Option>{/each}
            </NativeSelect.Root>
            <p class="text-xs text-muted-foreground">
              <a class="text-link hover:underline" href={href({ view: "agents", agent: b.agentId })}>Open {label(b.agentId)}</a>: its models, its runs, its settings.
            </p>
          {:else}
            <div class="flex flex-wrap items-center gap-2">
              <Button size="sm" variant="outline" href={href({ view: "set-up-helper", need: b.name })} data-testid={`skill-agent-${b.name}-setup`}
                ><Plus />Set up the {b.definition.agentName}</Button
              >
              {#if fits.length}
                <NativeSelect.Root
                  id={`skill-agent-${b.name}-choice`}
                  value=""
                  onchange={(e) => give(b, e.currentTarget.value)}
                  class="min-w-0 flex-1"
                  data-testid={`skill-agent-${b.name}-choice`}
                >
                  <NativeSelect.Option value="" disabled>or use one of yours…</NativeSelect.Option>
                  {#each fits as id (id)}<NativeSelect.Option value={id}>{label(id)}</NativeSelect.Option>{/each}
                </NativeSelect.Root>
              {/if}
            </div>
            <p class="text-xs text-muted-foreground">None yet: you choose its models, the rest is ready.</p>
          {/if}
        </SettingRow>
      {/each}
    </div>
  </section>
{/if}
