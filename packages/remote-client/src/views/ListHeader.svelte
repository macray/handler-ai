<script lang="ts" module>
  /** A count under the header: its words, and amber for what waits for the person. */
  export interface Count {
    words: string;
    tone?: "needs" | "working" | "idle";
    testid?: string;
  }
</script>

<script lang="ts">
  // A screen with a list (and Ask): a one-line header, its title in mono, and the computer as a
  // chip on the right ("● laptop", its light; a tap asks it again); its counts as small chips
  // under it. A big title is for a state only (BigState), never over a list.
  import { app } from "../lib/app.svelte";
  import { computerName } from "../lib/pairing";
  import { ago } from "../lib/time";
  import { status } from "./Lights.svelte";

  let { title, counts = [] }: { title: string; counts?: Count[] } = $props();

  const link = $derived(status(app.mailbox));
  const computer = $derived(app.device ? computerName(app.device) : "");
  // the link's state when it is not plain "connected", in a word after the name
  const SHORT = { "Computer away": "away", "No connection": "offline", "Not recognized": "not recognized", "Connecting…": "…" } as const;
  const word = $derived(link.light === "ok" ? "" : (SHORT[link.words as keyof typeof SHORT] ?? link.words));
  // the Home shown is the last launch's: said quietly, until the host answers
  const since = $derived(app.fresh || app.homeAt === null ? null : ago(app.homeAt, app.mailbox?.now ?? Date.now()));
</script>

<header class="head">
  <div class="line">
    <h1>{title}</h1>
    <button
      type="button"
      class="host"
      class:loading={app.loading}
      onclick={() => app.refresh()}
      disabled={app.loading || !app.mailbox}
      title={link.title}
      aria-label="{link.words}: {computer}. Refresh"
      data-testid="lights"
    >
      <span class="light {link.light}" aria-hidden="true"></span>
      <span class="name">{computer}</span>
      {#if word}<span class="word">· {word}</span>{/if}
    </button>
  </div>
  {#if counts.length || since !== null}
    <div class="counts">
      {#each counts as c (c.words)}
        <span class="chip {c.tone ?? ''}" data-testid={c.testid}>
          {#if c.tone}<span class="dot" aria-hidden="true"></span>{/if}{c.words}
        </span>
      {/each}
      {#if since !== null}<span class="chip quiet" data-testid="updated-ago">{since === "now" ? "updated just now" : `updated ${since} ago`}</span>{/if}
    </div>
  {/if}
</header>

<style>
  .head {
    flex: none;
    padding: max(0.6rem, env(safe-area-inset-top)) 1rem 0.5rem;
  }
  .line {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    min-height: 2rem;
  }
  h1 {
    min-width: 0;
    font: 700 19px/1.2 var(--mono);
    letter-spacing: -0.03em;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .host {
    flex: none;
    max-width: 60%;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 3px 10px 3px 8px;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--card);
    font: 11px/1.4 var(--mono);
    color: var(--muted-foreground);
  }
  .host:disabled {
    opacity: 1;
  }
  .name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .word {
    white-space: nowrap;
  }
  .light {
    flex: none;
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--muted-foreground);
  }
  .light.unknown,
  .loading .light {
    animation: waiting 1.4s var(--ease) infinite alternate;
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
  @keyframes waiting {
    to {
      opacity: 0.25;
    }
  }
  .counts {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 0.5rem;
  }
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    white-space: nowrap;
    padding: 4px 10px;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--card);
    font: 600 11px/1.3 var(--mono);
    color: var(--muted-foreground);
  }
  .chip.needs {
    color: var(--warn);
    background: color-mix(in srgb, var(--warn-bar) 16%, var(--card));
    border-color: color-mix(in srgb, var(--warn-bar) 40%, var(--card));
  }
  .chip.quiet {
    font-weight: 400;
    border-style: dashed;
  }
  .dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--muted-foreground);
  }
  .needs .dot {
    background: var(--warn-bar);
  }
  .working .dot {
    background: var(--ok);
  }
  .idle .dot {
    background: var(--border);
  }
</style>
