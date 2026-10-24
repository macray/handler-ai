<script lang="ts" module>
  /** One thing an agent did or does: a session or a run, at a time, with what can be done. */
  export type TimelineEntry = {
    key: string;
    at: string; // ISO
    dot: "needs-you" | "working" | "idle" | "ended" | "ok" | "warn" | "danger";
    title: string;
    note?: string; // beside the title: its state, where it came from, a run's verdict
    fact?: string; // under it, in the mono face: what it ran on
    action?: { label: string; href?: string; onclick?: () => void; primary?: boolean; testid?: string };
    testid?: string;
  };
</script>

<script lang="ts">
  // What an agent did, as a timeline by day (today, yesterday, a date): the time, a dot on the
  // rail (amber: it needs you; green: it works or went well; red: it went wrong; hollow: ended),
  // the title and a note, what it ran on, one action. The most recent first; the older ones
  // behind "N earlier…".
  import RotateCcw from "@lucide/svelte/icons/rotate-ccw";
  import { Button } from "$lib/components/ui/button";
  import { clockTime, dayOf, exactTime } from "../lib/agents";

  let { entries, shown = 8, empty }: { entries: TimelineEntry[]; shown?: number; empty: string } = $props();

  let all = $state(false);
  const sorted = $derived([...entries].sort((a, b) => b.at.localeCompare(a.at)));
  const visible = $derived(all ? sorted : sorted.slice(0, shown));
  const days = $derived(
    visible.reduce<{ day: string; entries: TimelineEntry[] }[]>((out, e) => {
      const day = dayOf(e.at);
      if (out.at(-1)?.day === day) out.at(-1)?.entries.push(e);
      else out.push({ day, entries: [e] });
      return out;
    }, []),
  );
  const NOTE: Record<TimelineEntry["dot"], string> = {
    "needs-you": "text-warn",
    working: "text-muted-foreground",
    idle: "text-muted-foreground",
    ended: "text-muted-foreground",
    ok: "text-ok",
    warn: "text-warn",
    danger: "text-danger",
  };
</script>

{#if sorted.length}
  <ol class="timeline">
    {#each days as d (d.day)}
      <li class="day section-label">{d.day}</li>
      {#each d.entries as e (e.key)}
        <li class="entry" data-testid={e.testid}>
          <time class="fact" datetime={e.at} title={exactTime(e.at)}>{clockTime(e.at)}</time>
          <span class="dot {e.dot}" aria-hidden="true"></span>
          <div class="min-w-0">
            <p class="flex flex-wrap items-baseline gap-x-2">
              <span class="font-medium [overflow-wrap:anywhere]">{e.title}</span>
              {#if e.note}<span class="text-xs {NOTE[e.dot]}">{e.note}</span>{/if}
            </p>
            {#if e.fact}<p class="fact truncate">{e.fact}</p>{/if}
          </div>
          {#if e.action}
            <Button
              variant={e.action.primary ? "outline" : "ghost"}
              size="sm"
              href={e.action.href}
              onclick={e.action.onclick}
              data-testid={e.action.testid}
            >
              {#if e.action.label === "Resume"}<RotateCcw />{/if}{e.action.label}
            </Button>
          {/if}
        </li>
      {/each}
    {/each}
  </ol>
  {#if sorted.length > visible.length}
    <button type="button" class="more cursor-pointer text-xs text-link hover:underline" onclick={() => (all = true)} data-testid="timeline-earlier">
      {sorted.length - visible.length} earlier…
    </button>
  {/if}
{:else}
  <p class="rounded-lg border border-dashed px-3 py-2 text-sm text-muted-foreground">{empty}</p>
{/if}

<style>
  .timeline {
    font-size: 0.875rem;
  }
  .day {
    margin: 0.75rem 0 0.25rem 4rem;
  }
  .day:first-child {
    margin-top: 0;
  }
  .entry {
    position: relative;
    display: grid;
    grid-template-columns: 3rem 0.75rem minmax(0, 1fr) auto;
    gap: 0 0.625rem;
    align-items: start;
    padding: 0.375rem 0;
  }
  /* the rail, through the dots */
  .entry::before {
    content: "";
    position: absolute;
    left: calc(3rem + 0.625rem + 0.375rem - 0.5px);
    top: 0;
    bottom: 0;
    width: 1px;
    background: var(--border);
  }
  .entry time {
    text-align: right;
    padding-top: 0.15rem;
  }
  .dot {
    position: relative;
    margin-top: 0.3rem;
    width: 0.75rem;
    height: 0.75rem;
    border-radius: 50%;
    border: 2px solid var(--muted-foreground);
    background: var(--background);
    box-shadow: 0 0 0 2px var(--background);
  }
  .dot.needs-you,
  .dot.warn {
    border-color: var(--warn);
    background: var(--warn);
  }
  .dot.working,
  .dot.ok {
    border-color: var(--ok);
    background: var(--ok);
  }
  .dot.danger {
    border-color: var(--danger);
    background: var(--danger);
  }
  .dot.idle {
    border-color: var(--ok);
  }
  .more {
    margin: 0.5rem 0 0 4.75rem;
  }
</style>
