<script lang="ts">
  // Shown when this browser is not signed in (no cookie of `handler ui`, or one of an older token):
  // the one command that signs it in, in a terminal look, ready to copy.
  import * as Card from "$lib/components/ui/card";
  import CommandLine from "./CommandLine.svelte";
</script>

<main class="grid min-h-svh place-items-center bg-background p-4">
  <Card.Root class="w-full max-w-md" data-testid="not-connected">
    <Card.Header>
      <Card.Title class="text-base">Open Handler from your terminal</Card.Title>
      <Card.Description>
        This browser is not signed in to Handler. Run this command on this computer: it opens Handler
        signed in, and this browser stays signed in, so a bookmark opens it from then on.
      </Card.Description>
    </Card.Header>
    <Card.Content>
      <CommandLine command="handler ui" />
      <p class="mt-3 text-xs text-muted-foreground">You can close this tab afterwards.</p>
    </Card.Content>
  </Card.Root>
</main>
