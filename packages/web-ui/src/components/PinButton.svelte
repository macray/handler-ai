<script lang="ts">
  // A project's or an app's pin: in the menu's Pinned or not (D.28). Taken off, the page's toast
  // may offer Undo (`onunpin`).
  import Pin from "@lucide/svelte/icons/pin";
  import { Button } from "$lib/components/ui/button";
  import type { Pin as PinItem } from "../lib/contracts.gen";
  import { pins } from "../lib/pins.svelte";

  let {
    kind,
    id,
    label,
    withText = false,
    onunpin,
  }: { kind: PinItem["kind"]; id: string; label: string; withText?: boolean; onunpin?: () => void } = $props();

  const pinned = $derived(pins.has(kind, id));

  async function toggle(e: MouseEvent): Promise<void> {
    e.preventDefault(); // inside a row's link: the pin alone
    e.stopPropagation();
    const was = pinned;
    try {
      await pins.toggle(kind, id);
    } catch {
      return; // pins.error says why
    }
    if (was) onunpin?.();
  }
</script>

<Button
  variant="ghost"
  size={withText ? "sm" : "icon"}
  class="relative z-10 shrink-0 {withText ? '' : 'size-8'} {pinned ? 'text-primary hover:text-primary' : 'text-muted-foreground'}"
  title={pinned ? "In the menu: unpin" : "Pin to the menu"}
  aria-label={pinned ? `unpin ${label} from the menu` : `pin ${label} to the menu`}
  aria-pressed={pinned}
  onclick={toggle}
  data-testid="{kind}-pin"
>
  <Pin class="size-4 {pinned ? 'fill-current' : ''}" />{#if withText}{pinned ? "Unpin" : "Pin"}{/if}
</Button>
