<script lang="ts">
  // A session starting, step by step, as it really goes: its sandbox starts (or, already running,
  // is reached) until the agent answers, then its conversation is replayed. The current step
  // says how long it has taken; a step done gets its check. Meant to sit on a `.term-surface`.
  import type { LiveSession } from "../lib/sessions.svelte";

  let { startup, access }: { startup: NonNullable<LiveSession["startup"]>; access: string } = $props();

  let now = $state(Date.now());
  $effect(() => {
    const timer = setInterval(() => (now = Date.now()), 1000);
    return () => clearInterval(timer);
  });
  const seconds = $derived(Math.max(0, Math.floor((now - startup.since) / 1000)));

  const steps = $derived([
    { id: "sandbox", label: startup.reattach ? `Reaching its sandbox (${access})` : `Starting its sandbox (${access})` },
    { id: "conversation", label: "Opening the conversation" },
  ]);
  const at = $derived(steps.findIndex((s) => s.id === startup.step));
</script>

<ol class="steps" aria-live="polite">
  {#each steps as step, i (step.id)}
    <li class={i < at ? "done" : i === at ? "now" : "next"}>
      <span class="mark" aria-hidden="true"></span>
      <span class="label">{step.label}</span>
      {#if i === at && seconds > 0}<span class="time">{seconds}s</span>{/if}
    </li>
  {/each}
</ol>

<style>
  .steps {
    display: flex;
    flex-direction: column;
    gap: 0.45rem;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  li {
    display: flex;
    align-items: center;
    gap: 1ch;
    color: var(--muted-foreground);
    animation: enter var(--dur-2) var(--ease) backwards;
  }
  li:nth-child(2) {
    animation-delay: 60ms;
  }
  .mark {
    position: relative;
    width: 0.7rem;
    height: 0.7rem;
    flex: none;
    border-radius: 50%;
    border: 2px solid var(--border);
  }
  .now {
    color: var(--foreground);
  }
  .now .mark {
    border-color: var(--muted-foreground);
    border-right-color: transparent;
    animation: spin 0.9s linear infinite;
  }
  /* the current step's words shimmer: it is going on */
  .now .label {
    background: linear-gradient(90deg, var(--foreground) 40%, var(--muted-foreground) 50%, var(--foreground) 60%) 0 0 / 300% 100%;
    background-clip: text;
    color: transparent;
    animation: shimmer 2.2s linear infinite;
  }
  .done {
    color: var(--muted-foreground);
  }
  .done .mark {
    border-color: var(--ok);
    background: var(--ok);
    animation: pop var(--dur-3) var(--ease-spring);
  }
  .time {
    margin-left: auto;
    font-variant-numeric: tabular-nums;
    color: var(--muted-foreground);
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
  @keyframes pop {
    from {
      transform: scale(0.4);
    }
  }
  @keyframes shimmer {
    from {
      background-position: 100% 0;
    }
    to {
      background-position: 0 0;
    }
  }
</style>
