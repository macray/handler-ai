<script lang="ts">
  import { app } from "./lib/app.svelte";
  import Pair from "./views/Pair.svelte";
  import AppScreen from "./views/AppScreen.svelte";
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
    <SessionList />
  {/if}
</div>

<style>
  .app {
    height: 100%;
    display: flex;
    flex-direction: column;
    font-family: "Inter Variable", "Inter", system-ui, sans-serif;
    font-size: 15px;
  }
</style>
