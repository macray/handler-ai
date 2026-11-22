<script lang="ts">
  // Beside a disabled main action (E1): why, in a short neutral sentence, then its fix one click
  // away (`Blocked`, lib/blocked): a link to where the fix is, a Connect dialog over the page, or a
  // control on this page brought into view and focused (opened when it is a picker).
  import Info from "@lucide/svelte/icons/info";
  import type { Blocked } from "../lib/blocked";
  import { connect } from "../lib/connect.svelte";

  let { blocked, testid }: { blocked: Blocked; testid?: string } = $props();

  const CONTROL = "input, select, textarea, button, a[href], [tabindex]";

  /** The fix's control on this page; none there, its page (`href`) when it has one. */
  function go(event: MouseEvent): void {
    const { focus, open, connect: kind } = blocked.fix ?? {};
    if (kind) return connect.open(kind);
    const at = focus ? document.querySelector<HTMLElement>(focus) : null;
    const control = at && (at.matches(CONTROL) ? at : at.querySelector<HTMLElement>(CONTROL));
    if (!control) return; // the link's href, if any, is followed
    event.preventDefault();
    control.scrollIntoView({ block: "center", behavior: "smooth" });
    control.focus({ preventScroll: true });
    if (open) control.click();
  }
</script>

<span class="inline-flex flex-wrap items-center gap-x-1.5 text-sm text-muted-foreground" data-testid={testid ?? "disabled-reason"}>
  <Info class="size-3.5 shrink-0" aria-hidden="true" />
  <span>{blocked.reason}{#if blocked.what}{" "}<b class="font-medium text-foreground">{blocked.what}</b>{/if}</span>
  {#if blocked.fix}
    <span aria-hidden="true">·</span>
    {#if blocked.fix.href}
      <a class="text-link hover:underline" href={blocked.fix.href} onclick={go} data-testid="disabled-fix">{blocked.fix.label}</a>
    {:else}
      <button type="button" class="text-link hover:underline" onclick={go} data-testid="disabled-fix">{blocked.fix.label}</button>
    {/if}
  {/if}
</span>
