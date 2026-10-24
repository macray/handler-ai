<script lang="ts">
  import { app } from "./lib/app.svelte";
  import Pair from "./views/Pair.svelte";
  import AppScreen from "./views/AppScreen.svelte";
  import AskScreen from "./views/AskScreen.svelte";
  import NewSession from "./views/NewSession.svelte";
  import SessionList from "./views/SessionList.svelte";
  import SessionScreen from "./views/SessionScreen.svelte";
  import Settings from "./views/Settings.svelte";
</script>

<div class="app term-surface">
  {#if !app.ready}
    <p class="p-6 text-muted-foreground">Loading…</p>
  {:else if app.offer || !app.device}
    <Pair />
  {:else if app.currentApp}
    <AppScreen />
  {:else if app.current}
    <SessionScreen />
  {:else if app.settings}
    <Settings />
  {:else if app.composing}
    <NewSession />
  {:else}
    {#if app.tab === "ask" && app.askOptions.length}<AskScreen />{:else}<SessionList />{/if}
    {#if app.askOptions.length}
      <!-- Ask first, on the owner's phone (D.24); the rest of what is shared on Home -->
      <nav class="tabs" aria-label="screens">
        <button type="button" class:on={app.tab === "ask"} onclick={() => (app.tab = "ask")} data-testid="tab-ask">Ask</button>
        <button type="button" class:on={app.tab === "home"} onclick={() => (app.tab = "home")} data-testid="tab-home">Home</button>
      </nav>
    {/if}
  {/if}
</div>

<style>
  .tabs {
    display: grid;
    grid-template-columns: 1fr 1fr;
    border-top: 1px solid var(--border);
    padding-bottom: env(safe-area-inset-bottom);
  }
  .tabs button {
    padding: 0.8rem 0;
    font-size: 0.85em;
    color: var(--muted-foreground);
  }
  .tabs button.on {
    color: var(--primary);
    font-weight: 600;
  }
  .app {
    height: 100%;
    display: flex;
    flex-direction: column;
    font-family: "Inter Variable", "Inter", system-ui, sans-serif;
    font-size: 15px;
  }
</style>
