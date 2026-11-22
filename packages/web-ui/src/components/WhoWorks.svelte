<script lang="ts">
  // Who works for an agent, read only, in the three parts of the choice (E2): its account or
  // provider · its program (the product name, never the harness id; or the model alone) · its
  // model ("default model" when it names none).
  import type { Agent } from "../lib/contracts.gen";
  import { harnesses, productName } from "../lib/harnesses.svelte";
  import { ALONE } from "../lib/whoworks";

  let { agent }: { agent: Pick<Agent, "model" | "modelAlone"> } = $props();
  const m = $derived(agent.model);
  const name = $derived(m.account ?? m.provider ?? "");
  void harnesses.load();
</script>

<span class="who" data-testid="who-works">
  <span class="part">
    <span class="grid size-4 shrink-0 place-items-center rounded-[4px] bg-muted text-[9.5px] font-semibold text-muted-foreground" aria-hidden="true">{name.charAt(0).toUpperCase()}</span>
    <span class="truncate font-medium" data-testid="who-works-account">{name}</span>
  </span>
  <span class="part text-muted-foreground" data-testid="who-works-program">{agent.modelAlone ? ALONE : productName(m.harness ?? "")}</span>
  <span class="part text-muted-foreground" data-testid="who-works-model">{m.model ?? "default model"}</span>
</span>

<style>
  .who {
    display: inline-flex;
    max-width: 100%;
    min-width: 0;
    align-items: stretch;
    overflow: hidden;
    border: 1px solid var(--border);
    border-radius: 0.375rem;
    font-size: 0.75rem;
    white-space: nowrap;
  }
  .part {
    display: inline-flex;
    min-width: 0;
    align-items: center;
    gap: 0.3rem;
    padding: 0.125rem 0.4rem;
    border-left: 1px solid var(--border);
  }
  .part:first-child {
    border-left: 0;
    padding-left: 0.25rem;
  }
</style>
