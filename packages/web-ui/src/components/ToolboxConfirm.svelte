<script lang="ts">
  // What a save adds to the toolbox (B.6), to confirm: the system every agent works in gets it,
  // then it is rebuilt. Shown when handlerd refused the save for it ("toolbox changes not confirmed").
  import { Button } from "$lib/components/ui/button";
  import type { ToolboxChanges } from "$lib/api";

  let {
    changes,
    busy = false,
    action = "Add and save",
    onconfirm,
    onback,
  }: { changes: ToolboxChanges; busy?: boolean; action?: string; onconfirm: () => void; onback: () => void } = $props();
</script>

<div class="w-full space-y-2 rounded-md border border-warn/40 bg-warn/5 p-3 text-sm" data-testid="toolbox-changes">
  <p>The toolbox, the system every agent works in, lacks what this needs. {changes.detail[0]?.toUpperCase()}{changes.detail.slice(1)}.</p>
  <p class="text-xs text-muted-foreground">A system package runs as root while the toolbox is built; every agent gets what it installs. Agents keep working on the current toolbox until the new one is ready.</p>
  <div class="flex gap-2">
    <Button type="button" size="sm" disabled={busy} onclick={onconfirm} data-testid="toolbox-confirm">{action}</Button>
    <Button type="button" size="sm" variant="ghost" onclick={onback}>Back</Button>
  </div>
</div>
