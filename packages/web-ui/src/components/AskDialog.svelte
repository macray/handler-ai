<script lang="ts">
  // The one dialog `ask()` asks in (lib/ask.svelte.ts): its question, what follows from it, then
  // Cancel and the action. Closing it any way (Esc, the ×, Cancel) answers no.
  import { Button } from "$lib/components/ui/button";
  import { asking } from "../lib/ask.svelte";
  import Dialog from "./Dialog.svelte";

  const q = $derived(asking.current);
</script>

<Dialog bind:open={() => q !== null, (open) => !open && q?.answer(false)} title={q?.title ?? ""} testid="ask">
  {#if q}
    <div class="space-y-4">
      {#if q.detail}<p class="whitespace-pre-line text-muted-foreground" data-testid="ask-detail">{q.detail}</p>{/if}
      <div class="flex justify-end gap-2 border-t pt-4">
        <Button variant="ghost" size="sm" onclick={() => q.answer(false)} data-testid="ask-no">Cancel</Button>
        <Button variant={q.danger ? "destructive" : "default"} size="sm" onclick={() => q.answer(true)} data-testid="ask-yes">{q.yes}</Button>
      </div>
    </div>
  {/if}
</Dialog>
