<script lang="ts">
  // Who works for an agent, read only, as the chips say it: its program, then its account or key
  // and model; on the model alone, one chip. Its program's product name, never the harness id.
  import type { Agent } from "../lib/contracts.gen";
  import { harnesses, productName } from "../lib/harnesses.svelte";

  let { agent }: { agent: Pick<Agent, "model" | "modelAlone"> } = $props();
  const m = $derived(agent.model);
  void harnesses.load();
  const CHIP = "inline-flex max-w-full items-center gap-1 truncate rounded-md border px-1.5 py-0.5 text-xs";
</script>

<span class="flex min-w-0 flex-wrap items-center gap-1" data-testid="who-works">
  {#if agent.modelAlone}
    <span class={CHIP}><span class="text-muted-foreground">the model alone</span> <span class="font-mono">{m.provider}</span>{#if m.model}<span class="text-muted-foreground">· {m.model}</span>{/if}</span>
  {:else}
    <span class="{CHIP} font-medium">{productName(m.harness ?? "")}</span>
    <span class={CHIP}><span class="font-mono">{m.account ?? m.provider}</span>{#if m.model}<span class="text-muted-foreground">· {m.model}</span>{/if}</span>
  {/if}
</span>
