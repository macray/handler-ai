<script lang="ts">
  // A schedule's fields (I.2), as an automation's and a nudge's `when` take it: at a time of day
  // on some days, or every N minutes, hours or days. Both kinds keep their values while the
  // other is shown; the caller makes the Schedule (`scheduleOf`) and says what is wrong.
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import * as NativeSelect from "$lib/components/ui/native-select";
  import { DAYS, WEEKDAYS, type Day } from "../lib/automations";
  import { SEGMENT, SEGMENT_OFF, SEGMENT_ON } from "../lib/form";

  let {
    timeKind = $bindable(),
    every = $bindable(),
    at = $bindable(),
    everyHint,
  }: {
    timeKind: "every" | "at";
    every: { n: number; unit: "m" | "h" | "d" };
    at: { at: string; days: Day[] };
    everyHint: string; // where `every` counts from
  } = $props();
  const uid = $props.id(); // its own ids: a page may show several

  function toggleDay(d: Day): void {
    at.days = at.days.includes(d) ? at.days.filter((x) => x !== d) : DAYS.filter((x) => x === d || at.days.includes(x));
  }

  const DAY_LABEL: Record<Day, string> = { mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun" };
  const CHIP = "cursor-pointer rounded-md border px-2.5 py-1 text-sm transition-colors";
  const CHIP_ON = "border-primary bg-primary text-primary-foreground";
  const CHIP_OFF = "bg-card text-muted-foreground hover:text-foreground";
</script>

<div class="inline-flex rounded-lg border bg-muted p-0.5" role="radiogroup" aria-label="schedule">
  {#each [{ v: "at", label: "At a time of day" }, { v: "every", label: "Every…" }] as o (o.v)}
    <button type="button" role="radio" aria-checked={timeKind === o.v} class="{SEGMENT} {timeKind === o.v ? SEGMENT_ON : SEGMENT_OFF}" onclick={() => (timeKind = o.v as "at" | "every")} data-testid={`schedule-${o.v}`}>
      {o.label}
    </button>
  {/each}
</div>
{#if timeKind === "every"}
  <div class="flex items-center gap-2">
    <Label for="{uid}-every-n" class="font-normal">Every</Label>
    <Input id="{uid}-every-n" type="number" min="1" class="h-9 w-24" bind:value={every.n} data-testid="schedule-every-n" />
    <NativeSelect.Root bind:value={every.unit} class="w-32" aria-label="unit" data-testid="schedule-every-unit">
      <NativeSelect.Option value="m">minutes</NativeSelect.Option>
      <NativeSelect.Option value="h">hours</NativeSelect.Option>
      <NativeSelect.Option value="d">days</NativeSelect.Option>
    </NativeSelect.Root>
  </div>
  <p class="text-xs text-muted-foreground">{everyHint}</p>
{:else}
  <div class="flex flex-wrap items-center gap-2">
    <Label for="{uid}-at-time" class="font-normal">At</Label>
    <Input id="{uid}-at-time" type="time" class="h-9 w-32" bind:value={at.at} data-testid="schedule-at" />
    <span class="text-sm text-muted-foreground">your local time, on</span>
  </div>
  <div class="flex flex-wrap items-center gap-1.5" role="group" aria-label="days" data-testid="schedule-days">
    {#each DAYS as d (d)}
      <button type="button" aria-pressed={at.days.includes(d)} class="{CHIP} {at.days.includes(d) ? CHIP_ON : CHIP_OFF}" onclick={() => toggleDay(d)}>{DAY_LABEL[d]}</button>
    {/each}
    <Button type="button" variant="ghost" size="sm" onclick={() => (at.days = [...WEEKDAYS])}>Weekdays</Button>
    <Button type="button" variant="ghost" size="sm" onclick={() => (at.days = [...DAYS])}>Every day</Button>
  </div>
{/if}
