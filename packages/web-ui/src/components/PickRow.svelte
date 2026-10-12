<script lang="ts">
  // One choice of a picker list (skills, addons, knowledge folders): a checkbox on the line of its
  // name, a badge, a note (where else it is used), and its description below, cut to two lines (all of it on hover); `depth`
  // indents it in a tree. The whole row toggles it.
  import { Checkbox } from "$lib/components/ui/checkbox";

  let {
    name,
    description = "",
    badge = "",
    note = "",
    checked,
    disabled = false,
    onchange,
    testid,
    depth = 0,
  }: {
    name: string;
    description?: string;
    badge?: string;
    note?: string;
    checked: boolean;
    disabled?: boolean;
    onchange?: (checked: boolean) => void;
    testid?: string;
    depth?: number;
  } = $props();
</script>

<label
  style={depth ? `padding-left: ${0.75 + depth * 1.25}rem` : undefined}
  class="flex items-start gap-3 px-3 py-2 text-sm transition-colors {disabled ? 'cursor-default' : 'cursor-pointer hover:bg-muted/60'} {checked && !disabled
    ? 'bg-accent-soft/40'
    : ''}"
>
  <Checkbox class="mt-0.5" {checked} {disabled} onCheckedChange={(c) => onchange?.(c === true)} data-testid={testid} />
  <span class="min-w-0 flex-1">
    <span class="flex items-center gap-2">
      <span class="truncate font-medium" title={name}>{name}</span>
      {#if badge}<span class="shrink-0 rounded bg-accent-soft px-1.5 py-px text-xs font-medium text-accent-soft-foreground">{badge}</span>{/if}
      {#if note}<span class="ml-auto shrink-0 text-xs text-muted-foreground" data-testid="pick-note">{note}</span>{/if}
    </span>
    {#if description}<span class="line-clamp-2 text-xs text-muted-foreground" title={description}>{description}</span>{/if}
  </span>
</label>
