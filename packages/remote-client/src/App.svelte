<script lang="ts">
  import { app } from "./lib/app.svelte";
  import { appScreen, sessionScreen } from "./lib/lazy";
  import Pair from "./views/Pair.svelte";
  import Apps from "./views/Apps.svelte";
  import AskScreen from "./views/AskScreen.svelte";
  import Inbox from "./views/Inbox.svelte";
  import NewSession from "./views/NewSession.svelte";
  import Sessions from "./views/Sessions.svelte";
  import Settings from "./views/Settings.svelte";
  import Starting from "./views/Starting.svelte";
  import TabBar from "./views/TabBar.svelte";
  import { theme } from "./lib/theme.svelte";

  // nothing to show yet, and nothing to say but the link's state: no tab's shape
  const starting = $derived.by(() => {
    const m = app.mailbox;
    const idle = Boolean(m?.reachable && !m.unauthorized && !m.hostOnline); // the tab says why
    // unreachable, refused, idle, failed: the tabs, their words (and Settings)
    return app.homeAt === null && m?.reachable !== false && !idle && !m?.unauthorized && !app.listError;
  });

  // a session's screen: the browser's bar dark like it
  const pairing = $derived(Boolean(app.offer || (app.ready && !app.device)));
  $effect(() => theme.setTerm(!pairing && !app.currentApp && Boolean(app.current)));

  // back on the page (the phone slept, another app was in front): asked again if not fresh,
  // what is shown stays meanwhile
  $effect(() => {
    const again = () => {
      if (document.visibilityState === "visible") app.refreshIfStale();
    };
    document.addEventListener("visibilitychange", again);
    return () => document.removeEventListener("visibilitychange", again);
  });
</script>

<!-- Until the screen to show is known, index.html's neutral screen, the same: a paired phone sees
     it turn into its tab, nothing on screen moving. -->
<div class="app">
  {#if pairing}
    <Pair />
  {:else if app.currentApp}
    {#await appScreen() then { default: AppScreen }}<AppScreen />{/await}
  {:else if app.current}
    <!-- a session stays dark, like a terminal, in every theme (as on the desktop) -->
    <div class="session term-surface">
      {#await sessionScreen() then { default: SessionScreen }}<SessionScreen />{/await}
    </div>
  {:else if app.composing}
    <NewSession />
  {:else}
    {#if starting}<Starting />
    {:else if app.screen === "ask"}<AskScreen />
    {:else if app.screen === "sessions"}<Sessions />
    {:else if app.screen === "apps"}<Apps />
    {:else if app.screen === "inbox"}<Inbox />
    {:else}<Settings />{/if}
    {#if starting}
      <!-- the tabs' place, kept until it is known which tabs there are: nothing moves when they come -->
      <div class="tabs" aria-hidden="true"></div>
    {:else}
      <TabBar />
    {/if}
  {/if}
</div>

<style>
  /* TabBar's height: index.html's `.s-tabs` */
  .tabs {
    flex: none;
    box-sizing: content-box;
    height: 57px;
    border-top: 1px solid transparent;
    padding-bottom: env(safe-area-inset-bottom);
  }
  .app,
  .session {
    display: flex;
    flex-direction: column;
    font-family: "Inter Variable", "Inter", system-ui, sans-serif;
  }
  .app {
    height: 100%;
    font-size: 15px;
    background: var(--page);
    color: var(--foreground);
  }
  .session {
    flex: 1;
    min-height: 0;
  }
</style>
