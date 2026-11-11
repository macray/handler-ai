<script lang="ts">
  // A command the person runs themselves, in a terminal look, ready to copy.
  import Check from "@lucide/svelte/icons/check";
  import Copy from "@lucide/svelte/icons/copy";

  let { command }: { command: string } = $props();
  let copied = $state(false);

  async function copy(): Promise<void> {
    await navigator.clipboard.writeText(command);
    copied = true;
    setTimeout(() => (copied = false), 1500);
  }
</script>

<!-- the session's terminal colours (.term-surface), whatever the theme -->
<div class="term-surface flex items-center gap-3 rounded-lg py-2.5 pr-2 pl-4 text-sm!" data-testid="command-line">
  <span class="select-none text-(--prompt)" aria-hidden="true">$</span>
  <span class="min-w-0 flex-1 break-all">{command}</span>
  <button
    type="button"
    class="inline-flex shrink-0 items-center gap-1.5 rounded-md px-2 py-1 font-sans text-xs text-muted-foreground hover:bg-secondary hover:text-foreground"
    onclick={copy}
    data-testid="copy-command"
  >
    {#if copied}<Check class="size-3.5" /> Copied{:else}<Copy class="size-3.5" /> Copy{/if}
  </button>
</div>
