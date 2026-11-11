<script lang="ts">
  // The hosts Handler's network filter refused to a run (a plan's step, an automation's run) or to
  // a session while nobody was there (F.9), each with how many times: what the agent said of them,
  // and your answer, *Allow* (and run again, for a run) or *Keep blocked*, for those not answered.
  // A run that completed did without them: its result may differ.
  import Ban from "@lucide/svelte/icons/ban";
  import Check from "@lucide/svelte/icons/check";
  import RotateCcw from "@lucide/svelte/icons/rotate-ccw";
  import { Button } from "$lib/components/ui/button";
  import type { RefusedHost } from "../lib/contracts.gen";

  let {
    hosts,
    said = null,
    completed = false,
    busy = false,
    again = null,
    onallow,
    onkeep,
  }: {
    hosts: RefusedHost[];
    said?: string | null;
    completed?: boolean;
    busy?: boolean;
    /** a run's: what *Allow* runs again ("Allow and run again from step 2"); null: Allow alone */
    again?: string | null;
    onallow: (hosts: string[]) => void;
    onkeep: (hosts: string[]) => void;
  } = $props();

  const open = $derived(hosts.filter((h) => !h.decision).map((h) => h.host));
  const times = (n: number) => (n === 1 ? "once" : `${n} times`);
</script>

<div class="space-y-2 rounded-[10px] border border-warn/30 bg-warn/5 px-4 py-3 text-sm" data-testid="refused-hosts">
  <p class="font-medium">
    {#if completed}Completed, with {hosts.length} host{hosts.length === 1 ? "" : "s"} refused{:else}Blocked by Handler's network filter{/if}
  </p>
  <ul class="space-y-0.5">
    {#each hosts as h (h.host)}
      <li data-testid="refused-host" data-host={h.host} data-state={h.decision ?? "refused"}>
        <span class="font-mono">{h.host}</span> <span class="text-muted-foreground">· refused {times(h.count)}</span>
        {#if h.decision}<span class="text-muted-foreground"> · {h.decision === "allowed" ? "allowed" : "kept blocked"}</span>{/if}
      </li>
    {/each}
  </ul>
  {#if said}<p class="text-muted-foreground" data-testid="refused-said">The agent said: “{said}”</p>{/if}
  {#if completed}<p class="text-muted-foreground">The result may differ from what you'd get with these hosts.</p>{/if}
  {#if open.length}
    <div class="flex flex-wrap gap-2 pt-1">
      <Button size="sm" disabled={busy} onclick={() => onallow(open)} data-testid="refused-allow">
        {#if again}<RotateCcw />{again}{:else}<Check />Allow{/if}
      </Button>
      <Button size="sm" variant="outline" disabled={busy} onclick={() => onkeep(open)} data-testid="refused-keep-blocked"><Ban />Keep blocked</Button>
    </div>
  {/if}
</div>
