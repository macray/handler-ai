<script lang="ts">
  // A feature's line naming its helper (D.18) and linking to it: "Written by the plan builder ·
  // Claude Code · Opus", or that it is set up the first time the feature is used.
  import { api } from "../lib/api";
  import type { Agent } from "../lib/contracts.gen";
  import { programLabel } from "../lib/access";
  import { featureOf, needLabel } from "../lib/helpers";
  import { href } from "../lib/router.svelte";

  let { need }: { need: string } = $props();

  let agent = $state<Agent | null | undefined>(undefined); // null: none given yet
  $effect(() => {
    api.handlerNeeds().then(
      async (needs) => {
        const id = needs.find((n) => n.name === need)?.agentId;
        agent = id ? await api.agent(id) : null;
      },
      () => (agent = null),
    );
  });
  const who = $derived(agent ? [agent.modelAlone ? "the model alone" : programLabel(agent.model), agent.model.model].filter(Boolean).join(" · ") : "");
</script>

<span data-testid="helper-link" data-need={need}>
  {featureOf(need).verb} the <a class="text-link hover:underline" href={href({ view: "settings", section: "helpers", helper: need })}>{needLabel(need).toLowerCase()}</a
  >{#if who}{" · "}<span class="fact">{who}</span>{:else if agent === null}<span class="text-muted-foreground">, set up the first time you use it</span>{/if}
</span>
