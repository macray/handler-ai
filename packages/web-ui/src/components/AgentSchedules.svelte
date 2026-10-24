<script lang="ts">
  // The automations that are on and run an agent (I.1), each a small link: when, and its next run.
  // Shown where the agent is listed, so that an agent that runs on its own is seen as one.
  import CalendarClock from "@lucide/svelte/icons/calendar-clock";
  import type { AutomationView } from "../lib/contracts.gen";
  import { schedulesOf, whenSentence } from "../lib/automations";
  import { href } from "../lib/router.svelte";
  import When from "./When.svelte";

  let { automations, agentId }: { automations: AutomationView[]; agentId: string } = $props();

  const found = $derived(schedulesOf(automations, agentId));
</script>

{#each found as a (a.name)}
  <a
    href={href({ view: "automation", name: a.name })}
    class="inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs text-muted-foreground no-underline hover:text-foreground"
    title={`Automation ${a.name}`}
    data-testid="agent-schedule-badge"
  >
    <CalendarClock class="size-3.5" />{whenSentence(a.definition).toLowerCase()}{#if a.nextAt}, next <When at={a.nextAt} />{/if}
  </a>
{/each}
