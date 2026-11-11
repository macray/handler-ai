<script lang="ts">
  // What the agent gets and may do, as chips in its box's footer after who works (ModelChoice):
  // its tools, its network (the meter: more bars, safer; then "4 sites", "No network" or "Any
  // site" in amber), then one amber chip per switch that weakens its sandbox beyond the default
  // (learning the sites, runs containers, windows on my screen, privileged, shared caches). Each
  // opens the agent's settings, where they change.
  import Wrench from "@lucide/svelte/icons/wrench";
  import type { Agent, Project } from "../lib/contracts.gen";
  import { networkWords, widenings } from "../lib/safety";
  import NetworkMeter from "./NetworkMeter.svelte";

  let { agent, caches, edit }: { agent: Agent; caches?: Project["caches"]; edit: string } = $props();

  const tools = $derived([...(agent.addons ?? []), ...(agent.projectAddons ?? [])].map((u) => (u.binding ? `${u.addon}: ${u.binding}` : u.addon)));
  const sites = $derived([...new Set([...(agent.model.requiredHosts ?? []).map((r) => r.host), ...(agent.allow ?? [])])]);
  const widened = $derived(widenings(agent, caches));
  const CHIP = "inline-flex h-7 items-center gap-1.5 rounded-md border px-2 font-sans text-xs no-underline";
</script>

{#if !agent.modelAlone}
  <a class="{CHIP} text-foreground/85 hover:bg-secondary" href={edit} title={tools.length ? tools.join(", ") : "No tools: add one in its settings"} data-testid="chip-tools">
    <Wrench class="size-3.5" />{tools.length} tool{tools.length === 1 ? "" : "s"}
  </a>
  <a
    class="{CHIP} hover:bg-secondary {agent.network === 'open' ? 'border-warn/60 text-warn' : 'text-foreground/85'}"
    href={edit}
    title={agent.network === "filtered" ? (sites.length ? `Only these sites: ${sites.join(", ")}` : "Only these sites: none yet") : agent.network === "open" ? "Any site on the internet and your network" : "No network at all"}
    data-testid="chip-network"
  >
    <NetworkMeter network={agent.network} />{networkWords(agent.network, sites.length)}
  </a>
  {#each widened as w (w.label)}
    <a class="{CHIP} border-warn/60 text-warn hover:bg-warn/10" href={edit} title={w.why} data-testid="chip-widened">{w.label}</a>
  {/each}
{/if}
