<script lang="ts">
  // A small panel opened from a button (the page's ⋯, the box's chips): on the page's top layer,
  // under the button (above it when the window has no room under it; or right-aligned with it),
  // closed by a click elsewhere or Escape. `trigger` renders the button with the props it needs;
  // `children` the panel, given `close` (a menu's rows: buttons of class `menu-item`).
  import type { Snippet } from "svelte";

  type TriggerProps = { onclick: () => void; "aria-expanded": boolean; "aria-haspopup": "dialog" };

  let {
    open = $bindable(false),
    align = "start",
    label,
    width = "auto",
    testid,
    trigger,
    children,
  }: {
    open?: boolean;
    align?: "start" | "end";
    label: string; // the panel's name, for assistive technology
    width?: string; // a CSS width
    testid?: string;
    trigger: Snippet<[TriggerProps]>;
    children: Snippet<[() => void]>;
  } = $props();

  let anchor = $state<HTMLElement | null>(null);
  let panel = $state<HTMLElement | null>(null);
  let at = $state({ top: 0, left: 0, right: 0 });

  /** Under the button, or above it when the window has no room under it. */
  function place(): void {
    const r = anchor?.getBoundingClientRect();
    if (!r) return;
    const height = panel?.offsetHeight ?? 0;
    const under = r.bottom + 6 + height <= window.innerHeight - 8 || r.top - 6 - height < 8;
    at = { top: under ? r.bottom + 6 : r.top - 6 - height, left: r.left, right: window.innerWidth - r.right };
  }

  function toggle(): void {
    open = !open;
    if (open) place();
  }

  const close = () => (open = false);
  // opened by its owner too (the next menu of a choice)
  $effect(() => {
    if (open && panel) place();
  });

  /** Above the page: the page's scrolling column would clip it. In a modal dialog, inside it:
   *  what is outside a modal dialog cannot be clicked. */
  function onTop(node: HTMLElement) {
    (anchor?.closest("dialog") ?? document.body).appendChild(node);
    return { destroy: () => node.remove() };
  }

  function outside(e: PointerEvent): void {
    if (open && !panel?.contains(e.target as Node) && !anchor?.contains(e.target as Node)) open = false;
  }
</script>

<svelte:window onpointerdown={outside} onkeydown={(e) => open && e.key === "Escape" && close()} onresize={() => open && place()} />

<span bind:this={anchor} class="inline-flex">
  {@render trigger({ onclick: toggle, "aria-expanded": open, "aria-haspopup": "dialog" })}
</span>
{#if open}
  <div
    bind:this={panel}
    use:onTop
    class="popover"
    style="top:{at.top}px;{align === 'end' ? `right:${at.right}px` : `left:${at.left}px`};width:{width}"
    role="dialog"
    aria-label={label}
    data-testid={testid}
  >
    {@render children(close)}
  </div>
{/if}

<style>
  .popover {
    position: fixed;
    z-index: 50;
    max-width: calc(100vw - 16px);
    max-height: 70vh;
    overflow-y: auto;
    padding: 6px;
    border-radius: 12px;
    background: var(--popover);
    color: var(--popover-foreground);
    box-shadow: var(--float-shadow);
    font-size: 13px;
  }
  /* a menu's rows: an icon and what it does */
  .popover :global(.menu-item) {
    display: flex;
    width: 100%;
    align-items: center;
    gap: 9px;
    padding: 7px 10px;
    border-radius: 7px;
    color: inherit;
    font-size: 13px;
    text-align: left;
    cursor: pointer;
  }
  .popover :global(.menu-item:hover) {
    background: var(--muted);
  }
  .popover :global(.menu-item svg) {
    width: 15px;
    height: 15px;
    color: var(--muted-foreground);
  }
</style>
