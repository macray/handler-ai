<script lang="ts">
  // A host Handler's network filter refused (F.9): one card per host per turn, its count raised by
  // each repeat. The person allows it for the agent or keeps it blocked, saved and applied to the
  // running sandbox at once; allowed, the card says so; kept blocked, it becomes one grey line (no
  // card again for that host). Not answered, it stays, one line once the next turn starts. Where
  // the client cannot answer (`ondecide` not given: the phone), it says where to. While the filter
  // holds the agent's request for the answer (`until`), it counts the seconds down; answered while
  // a turn runs, it says the agent will be told when it finishes.
  import type { HostDecision, HostEntry } from "../lib/session.svelte";

  let {
    entry,
    past = false,
    ondecide,
  }: {
    entry: HostEntry;
    past?: boolean; // an earlier turn's
    ondecide?: (host: string, decision: HostDecision) => Promise<void>;
  } = $props();

  let saving = $state(false);
  let error = $state<string | null>(null);
  const times = $derived(entry.count > 1 ? ` (${entry.count} times)` : "");
  let now = $state(Date.now());
  $effect(() => {
    if (!entry.until) return;
    const end = Date.parse(entry.until);
    now = Date.now();
    if (end <= now) return;
    const tick = setInterval(() => {
      now = Date.now();
      if (now >= end) clearInterval(tick);
    }, 250);
    return () => clearInterval(tick);
  });
  // seconds the agent still waits for the answer; 0: not waiting
  const left = $derived(entry.until ? Math.max(0, Math.ceil((Date.parse(entry.until) - now) / 1000)) : 0);
  const told = "The agent will be told when it finishes";

  async function decide(decision: HostDecision): Promise<void> {
    if (!ondecide) return;
    saving = true;
    error = null;
    try {
      await ondecide(entry.host, decision);
    } catch (e) {
      error = (e as Error).message;
    } finally {
      saving = false;
    }
  }
</script>

{#if entry.decision === "kept blocked"}
  <div class="line host kept" data-testid="host-card" data-host={entry.host} data-state="kept blocked">
    <span class="gutter" aria-hidden="true">⊘</span>
    <div class="text"><span class="name">{entry.host}</span> kept blocked: the agent goes on without it{#if entry.queued}. {told}{/if}</div>
  </div>
{:else if entry.decision === "allowed"}
  <div class="line host allowed" data-testid="host-card" data-host={entry.host} data-state="allowed">
    <span class="gutter" aria-hidden="true">✓</span>
    <div class="text">Allowed: <span class="name">{entry.host}</span> is in this agent's allowed hosts{#if entry.queued}. {told}{/if}</div>
  </div>
{:else}
  <div class="host asks" class:past role="group" aria-label="blocked host" data-testid="host-card" data-host={entry.host} data-state="blocked">
    <div class="line">
      <span class="gutter" aria-hidden="true">✕</span>
      {#if entry.count === 0}
        <div class="text">Handler's network filter {left > 0 ? "is holding" : "held"} a request to <span class="name">{entry.host}</span></div>
      {:else}
        <div class="text">Handler's network filter blocked <span class="name">{entry.host}</span>{times}</div>
      {/if}
    </div>
    {#if left > 0}
      <p class="hint waiting" data-testid="host-waiting">The agent is waiting · <span class="tabular-nums">{left} s</span></p>
    {/if}
    {#if ondecide}
      <div class="answers">
        <button type="button" class="allow" disabled={saving} onclick={() => decide("allowed")} data-testid="host-allow">Allow for this agent</button>
        <button type="button" class="keep" disabled={saving} onclick={() => decide("kept blocked")} data-testid="host-keep-blocked">Keep blocked</button>
      </div>
    {:else if !past}
      <p class="hint">Allow it or keep it blocked in Handler on your computer.</p>
    {/if}
    {#if error}<p class="error" role="alert">{error}</p>{/if}
  </div>
{/if}

<style>
  .name {
    font-family: var(--mono);
    font-weight: 600;
  }
  .kept {
    color: var(--muted-foreground);
  }
  .kept .name {
    font-weight: 400;
  }
  .allowed .gutter {
    color: var(--ok);
  }
  .asks {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    border: 1px solid var(--warn);
    border-radius: 10px;
    padding: 0.6rem 0.8rem;
    background: color-mix(in srgb, var(--warn) 10%, var(--background));
  }
  .asks .gutter {
    color: var(--warn);
  }
  /* an earlier turn's, not answered: one line, its answers beside it */
  .asks.past {
    flex-direction: row;
    flex-wrap: wrap;
    align-items: baseline;
    border: none;
    padding: 0;
    background: none;
    color: var(--muted-foreground);
  }
  .answers {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    padding-left: 2.5ch;
  }
  .past .answers {
    padding-left: 0;
  }
  button {
    border-radius: 6px;
    padding: 0.25rem 0.8rem;
    font-weight: 600;
    border: 1px solid var(--border);
    background: var(--background);
    color: var(--foreground);
  }
  .past button {
    padding: 0 0.5rem;
    font-size: 0.9em;
    font-weight: 400;
  }
  button.allow {
    border-color: var(--ok);
    color: var(--ok);
  }
  button:hover:not(:disabled) {
    background: var(--muted);
  }
  button:disabled {
    color: var(--muted-foreground);
    border-color: var(--border);
  }
  .hint,
  .error {
    margin: 0;
    padding-left: 2.5ch;
    color: var(--muted-foreground);
  }
  .error {
    color: var(--danger);
  }
  @media (pointer: coarse) {
    button {
      min-height: 2.5rem;
    }
  }
</style>
