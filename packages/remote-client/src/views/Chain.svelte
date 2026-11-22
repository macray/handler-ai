<script lang="ts">
  // The chain this phone → the gateway → the computer, lit link by link: a part's light, and the
  // link to it lit as it (the first launch's screen, Settings → Connection).
  import type { Light } from "./Lights.svelte";

  let { gateway, host, computer }: { gateway: Light; host: Light; computer: string } = $props();
</script>

{#snippet node(light: Light, label: string, kind: "phone" | "gateway" | "computer")}
  <li class="node">
    <span class="box">
      <svg viewBox="0 0 24 24" aria-hidden="true">
        {#if kind === "phone"}<rect x="6" y="2" width="12" height="20" rx="2" /><path d="M12 18h.01" />
        {:else if kind === "gateway"}<path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z" />
        {:else}<rect x="4" y="4" width="16" height="12" rx="2" /><path d="M2 20h20" />{/if}
      </svg>
      <span class="light {light}" aria-hidden="true"></span>
    </span>
    <span class="label">{label}</span>
  </li>
{/snippet}

<ol class="chain" aria-label="this phone, the gateway, {computer}">
  {@render node("ok", "this phone", "phone")}
  <li class="wire {gateway}" aria-hidden="true"></li>
  {@render node(gateway, "gateway", "gateway")}
  <li class="wire {host}" aria-hidden="true"></li>
  {@render node(host, computer, "computer")}
</ol>

<style>
  .chain {
    display: flex;
    align-items: flex-start;
  }
  .node {
    flex: none;
    width: 5.2rem;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.35rem;
  }
  .box {
    position: relative;
    display: grid;
    place-items: center;
    width: 2.8rem;
    height: 2.8rem;
    border: 1px solid var(--border);
    border-radius: 12px;
    background: var(--card);
    color: var(--foreground);
  }
  .box .light {
    position: absolute;
    top: -0.25rem;
    right: -0.25rem;
    width: 0.7rem;
    height: 0.7rem;
    border-radius: 50%;
    background: var(--muted-foreground);
    box-shadow: 0 0 0 2px var(--card);
  }
  .box .light.unknown {
    animation: waiting 1.4s var(--ease) infinite alternate; /* asked, not answered yet */
  }
  .box .light.ok {
    background: var(--ok);
  }
  .box .light.warn {
    background: var(--warn);
  }
  .box .light.danger {
    background: var(--danger);
  }
  @keyframes waiting {
    to {
      opacity: 0.25;
    }
  }
  svg {
    width: 1.15rem;
    height: 1.15rem;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .label {
    max-width: 100%;
    font: 0.75em var(--mono);
    color: var(--muted-foreground);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  /* a link between two: lit as the part it reaches, dashed while not reached */
  .wire {
    flex: 1;
    min-width: 0.75rem;
    height: 2px;
    margin-top: 1.4rem;
    border-radius: 1px;
    background: repeating-linear-gradient(90deg, var(--border) 0 4px, transparent 4px 8px);
  }
  .wire.ok {
    background: var(--ok);
  }
  .wire.warn {
    background: var(--warn);
  }
  .wire.danger {
    background: repeating-linear-gradient(90deg, var(--danger) 0 4px, transparent 4px 8px);
  }
</style>
