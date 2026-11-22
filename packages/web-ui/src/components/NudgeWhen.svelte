<script lang="ts">
  // When Handler sends a nudge of an app (H.17): the app's time, or yours replacing it, in words,
  // with when it comes next; Change opens the schedule's fields, Back to the app's drops yours.
  // It holds for that nudge's next ones; the same on an open nudge in the inbox and on the app's
  // page.
  import CalendarClock from "@lucide/svelte/icons/calendar-clock";
  import Undo2 from "@lucide/svelte/icons/undo-2";
  import { Button } from "$lib/components/ui/button";
  import { DAYS, scheduleFormOf, scheduleOf, scheduleProblem, type Day, type ScheduleForm } from "../lib/automations";
  import type { Schedule } from "../lib/contracts.gen";
  import { whenWords } from "../lib/nudges";
  import ScheduleFields from "./ScheduleFields.svelte";
  import When from "./When.svelte";

  let {
    when,
    ownWhen = null,
    nextAt = null,
    disabled = false,
    onchange,
  }: {
    when: Schedule; // the app's
    ownWhen?: Schedule | null; // yours
    nextAt?: string | null;
    disabled?: boolean;
    onchange: (to: Schedule | null) => Promise<void> | void;
  } = $props();

  const now = $derived(ownWhen ?? when);
  let editing = $state(false);
  let timeKind = $state<"every" | "at">("at");
  let every = $state({ n: 1, unit: "d" as "m" | "h" | "d" });
  let at = $state({ at: "09:00", days: [...DAYS] as Day[] });
  const form = $derived<ScheduleForm>(timeKind === "every" ? { kind: "every", ...every } : { kind: "at", ...at });
  const wrong = $derived(scheduleProblem(form));

  function edit(): void {
    const f = scheduleFormOf(now);
    if (f?.kind === "every") every = { n: f.n, unit: f.unit };
    else if (f) at = { at: f.at, days: [...f.days] };
    if (f) timeKind = f.kind;
    editing = true;
  }

  async function save(): Promise<void> {
    await onchange(scheduleOf(form));
    editing = false;
  }
</script>

<div class="space-y-2 text-xs text-muted-foreground" data-testid="nudge-when">
  <div class="flex flex-wrap items-center gap-1">
    <span class="mr-1" data-testid="nudge-when-words">
      Comes <span class="text-foreground">{whenWords(now)}</span>{#if ownWhen}{" "}(yours; the app says {whenWords(when)}){/if}{#if nextAt}, next <When at={nextAt} />{/if}
    </span>
    {#if !editing}
      <Button size="xs" variant="ghost" {disabled} onclick={edit} data-testid="nudge-when-change"><CalendarClock />Change</Button>
      {#if ownWhen}
        <Button size="xs" variant="ghost" {disabled} onclick={() => onchange(null)} data-testid="nudge-when-app"><Undo2 />Back to the app's</Button>
      {/if}
    {/if}
  </div>
  {#if editing}
    <div class="space-y-3 rounded-lg border bg-card p-3 text-sm text-foreground" data-testid="nudge-when-edit">
      <ScheduleFields bind:timeKind bind:every bind:at everyHint="Counted from when you save it: at least every 5 minutes." />
      {#if wrong}<p class="text-xs text-danger">{wrong}</p>{/if}
      <p class="text-xs text-muted-foreground">It comes while Handler runs: after your computer was off, only the latest missed time comes.</p>
      <div class="flex gap-2">
        <Button size="sm" disabled={disabled || !!wrong} onclick={save} data-testid="nudge-when-save">Save</Button>
        <Button size="sm" variant="ghost" onclick={() => (editing = false)}>Cancel</Button>
      </div>
    </div>
  {/if}
</div>
