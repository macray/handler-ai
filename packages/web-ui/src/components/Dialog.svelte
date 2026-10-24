<script lang="ts">
  // A modal dialog (the browser's <dialog>: focus kept inside, Esc closes, the page behind dimmed)
  // for what is made or changed in a few steps (pairing a device, a new account, a provider): the
  // page keeps its list, the dialog holds the form. `open` opens and closes it; closing it any way
  // (Esc, the ×, a Cancel) sets `open` back to false. Its body scrolls when taller than the window.
  import type { Snippet } from "svelte";
  import X from "@lucide/svelte/icons/x";
  import { Button } from "$lib/components/ui/button";

  let {
    open = $bindable(false),
    title,
    description,
    wide = false,
    testid,
    children,
  }: {
    open: boolean;
    title: string;
    description?: string;
    wide?: boolean; // a long form (a provider's models)
    testid?: string;
    children: Snippet;
  } = $props();

  let dialog = $state<HTMLDialogElement>();
  const id = `dialog-${Math.random().toString(36).slice(2, 8)}`;

  $effect(() => {
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    else if (!open && dialog.open) dialog.close();
  });
</script>

<dialog
  bind:this={dialog}
  class="m-auto max-h-[min(52rem,calc(100dvh-2rem))] {wide
    ? 'w-[min(44rem,calc(100vw-2rem))]'
    : 'w-[min(32rem,calc(100vw-2rem))]'} flex-col rounded-[14px] border bg-background p-0 text-sm text-foreground shadow-panel backdrop:bg-black/40 open:flex open:animate-[rise_var(--dur-3)_var(--ease)]"
  aria-labelledby={id}
  onclose={() => (open = false)}
  data-testid={testid}
>
  {#if open}
    <header class="flex items-start justify-between gap-4 px-6 pt-6 pb-4">
      <div class="min-w-0 space-y-1">
        <h2 {id} class="text-base font-semibold">{title}</h2>
        {#if description}<p class="text-muted-foreground">{description}</p>{/if}
      </div>
      <Button variant="ghost" size="icon-sm" class="-mt-1 -mr-2 text-muted-foreground" aria-label="Close" onclick={() => (open = false)}><X /></Button>
    </header>
    <div class="min-h-0 overflow-y-auto px-6 pb-6">{@render children()}</div>
  {/if}
</dialog>
