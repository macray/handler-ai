<script lang="ts">
  // A state, said big (never over a list): a small line with the computer and its light, the big
  // mono title, a sub under it ("laptop is away", "As it was at 22:14"; "all quiet", "Nothing
  // needs you."). What the screen still shows comes under it (children). With `onrefresh`, the
  // small line is a button that asks the computer again (as the one-line header's chip).
  import type { Snippet } from "svelte";

  let {
    title,
    host,
    light = "unknown",
    sub = "",
    tone = "",
    onrefresh,
    busy = false,
    label = "",
    children,
  }: {
    title: string;
    host: string;
    light?: "ok" | "warn" | "danger" | "unknown";
    sub?: string;
    tone?: "" | "ok" | "warn" | "grey";
    onrefresh?: () => void;
    busy?: boolean;
    label?: string;
    children?: Snippet;
  } = $props();
</script>

<header class="state">
  {#if onrefresh}
    <button type="button" class="host" class:busy onclick={onrefresh} disabled={busy} aria-label={label || undefined} data-testid="lights">
      <span class="light {light}" aria-hidden="true"></span>{host}
    </button>
  {:else}
    <p class="host"><span class="light {light}" aria-hidden="true"></span>{host}</p>
  {/if}
  <h1 class={tone}>{title}</h1>
  {#if sub}<p class="sub">{sub}</p>{/if}
</header>
{@render children?.()}

<style>
  .state {
    flex: none;
    padding: max(0.6rem, env(safe-area-inset-top)) 1.25rem 0.9rem;
  }
  .host {
    display: flex;
    align-items: center;
    gap: 6px;
    font: 11.5px/1.4 var(--mono);
    color: var(--muted-foreground);
  }
  button.host {
    min-height: 1.75rem;
    margin: -0.3rem 0;
    text-align: left;
  }
  button.host:disabled {
    opacity: 1;
  }
  .busy .light {
    animation: waiting 1.4s var(--ease) infinite alternate;
  }
  @keyframes waiting {
    to {
      opacity: 0.25;
    }
  }
  h1 {
    margin-top: 0.9rem;
    font: 800 38px/1.02 var(--mono);
    letter-spacing: -0.05em;
    overflow-wrap: anywhere;
  }
  h1.ok {
    color: var(--ok);
  }
  h1.warn {
    color: var(--warn);
  }
  h1.grey {
    color: var(--muted-foreground);
  }
  .sub {
    margin-top: 0.4rem;
    font: 500 14px/1.35 var(--mono);
    letter-spacing: -0.01em;
    color: var(--muted-foreground);
  }
  .light {
    flex: none;
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--muted-foreground);
  }
  .light.ok {
    background: var(--ok);
  }
  .light.warn {
    background: var(--warn-bar);
  }
  .light.danger {
    background: var(--danger);
  }
</style>
