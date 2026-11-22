<script lang="ts">
  // A place of the menu empty for want of a model (E1, lib/menu emptyFor): it asks that one thing,
  // its Connect a dialog over the page (lib/connect). While shown, the model is read again (a
  // subscription's login ends in its terminal), so the page turns into its own empty state.
  import { Button } from "$lib/components/ui/button";
  import { connect } from "../lib/connect.svelte";
  import { menuUse } from "../lib/menuuse.svelte";

  let { testid = "connect-first", center = false }: { testid?: string; center?: boolean } = $props();

  $effect(() => {
    void connect.changes; // one connected: read at once
    menuUse.loadModel();
    const timer = setInterval(() => menuUse.loadModel(), 5000);
    return () => clearInterval(timer);
  });
</script>

<div class="flex flex-col gap-3 {center ? 'items-center text-center' : 'items-start'}" data-testid={testid}>
  <p class="text-sm"><b class="font-semibold">Connect a model first</b> <span class="text-muted-foreground">· a subscription you have, an API key, or a local model.</span></p>
  <Button size="sm" onclick={() => connect.open("both")} data-testid="{testid}-button">Connect…</Button>
</div>
