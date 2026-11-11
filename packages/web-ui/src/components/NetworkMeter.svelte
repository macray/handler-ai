<script lang="ts">
  // The network's meter (D.8): three bars, more is safer. No network 3, Only these sites 2, in
  // sage; Any site one bar, amber. It stands for the network only: what else weakens the sandbox
  // is its own amber chip.
  import { barsOf, type NetworkMode } from "../lib/safety";

  let { network }: { network: NetworkMode | null | undefined } = $props();
  const bars = $derived(barsOf(network));
</script>

<span class="meter" aria-hidden="true" data-testid="network-meter" data-bars={bars}>
  {#each [0, 1, 2] as i (i)}<i class={i < bars ? (bars === 1 ? "warn" : "on") : ""}></i>{/each}
</span>

<style>
  .meter {
    display: inline-flex;
    flex: none;
    align-items: center;
    gap: 2px;
  }
  .meter i {
    width: 5px;
    height: 10px;
    border-radius: 1.5px;
    background: color-mix(in oklab, currentColor 22%, transparent);
  }
  .meter i.on {
    background: var(--safe);
  }
  .meter i.warn {
    background: var(--warn-bar);
  }
</style>
