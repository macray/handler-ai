<script lang="ts">
  // Shown when the page was opened without `handler ui` (no token in this tab): the one command
  // that opens it the right way, in a terminal look, ready to copy.
  import Check from "@lucide/svelte/icons/check";
  import Copy from "@lucide/svelte/icons/copy";
  import * as Card from "$lib/components/ui/card";

  const command = "handler ui";
  let copied = $state(false);

  async function copy(): Promise<void> {
    await navigator.clipboard.writeText(command);
    copied = true;
    setTimeout(() => (copied = false), 1500);
  }
</script>

<main class="grid min-h-svh place-items-center bg-background p-4">
  <Card.Root class="w-full max-w-md" data-testid="not-connected">
    <Card.Header>
      <Card.Title class="text-base">Open Handler from your terminal</Card.Title>
      <Card.Description>
        This tab has no access to Handler yet. Run this command on this computer: it opens Handler in
        a new tab, signed in.
      </Card.Description>
    </Card.Header>
    <Card.Content>
      <div class="flex items-center gap-3 rounded-lg bg-zinc-900 py-2.5 pr-2 pl-4 font-mono text-sm text-zinc-100">
        <span class="select-none text-orange-400" aria-hidden="true">$</span>
        <span class="flex-1">{command}</span>
        <button
          type="button"
          class="inline-flex items-center gap-1.5 rounded-md px-2 py-1 font-sans text-xs text-zinc-300 hover:bg-zinc-800 hover:text-zinc-100 focus-visible:ring-2 focus-visible:ring-orange-400 focus-visible:outline-none"
          onclick={copy}
          data-testid="copy-command"
        >
          {#if copied}<Check class="size-3.5" /> Copied{:else}<Copy class="size-3.5" /> Copy{/if}
        </button>
      </div>
      <p class="mt-3 text-xs text-muted-foreground">You can close this tab afterwards.</p>
    </Card.Content>
  </Card.Root>
</main>
