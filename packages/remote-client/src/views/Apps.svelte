<script lang="ts">
  // Apps: those shared with this device's person, a launcher (a plain icon each, no colour per
  // app), each opened in its frame (from this phone's copy when the computer does not answer).
  import { app } from "../lib/app.svelte";
  import Docked from "./Docked.svelte";
  import ListHeader from "./ListHeader.svelte";
  import Offline from "./Offline.svelte";

  const owner = $derived(app.scope === "all");
  const waiting = $derived(app.homeAt === null);
  const idle = $derived(Boolean(app.mailbox?.reachable && !app.mailbox.unauthorized && !app.mailbox.hostOnline));
  const nothing = $derived(!app.apps.length);
</script>

<ListHeader title="Apps" />

<main class="list">
  <Offline />
  {#if waiting}
    {#if idle}
      <div class="empty fade" data-testid="host-idle">
        <p><strong>Your computer is not listening right now.</strong></p>
        <p>Handler there reaches this phone only while {owner ? "a session or an app" : "an app"} is shared with you.</p>
      </div>
    {:else if app.listError}
      <p class="error fade">{app.listError}</p>
    {/if}
  {:else if nothing}
    {#if app.listError}
      <p class="error">{app.listError}</p>
    {:else if owner}
      <div class="empty fade" data-testid="apps-empty">
        <p><strong>No apps on this phone yet.</strong></p>
        <p>On your computer, an app's page says who opens it: choose “you, on your phone”.</p>
      </div>
    {:else}
      <div class="empty fade" data-testid="apps-empty">
        <p><strong>Nothing is shared with you yet.</strong></p>
        <p>Ask the owner of the computer to share an app with you.</p>
      </div>
    {/if}
  {:else}
    <!-- a launcher: a plain icon (its initial, the same colour for all) and its name -->
    <section class="grid fade">
      {#each app.apps as a (a.name)}
        <button type="button" class="app" onclick={() => app.openApp(a)} title={a.description ?? a.name} data-testid="shared-app">
          <span class="icon" aria-hidden="true">{a.name.slice(0, 1).toUpperCase()}</span>
          <span class="name">{a.name}</span>
        </button>
      {/each}
    </section>
  {/if}
  <Docked quiet={waiting || nothing} />
</main>

<style>
  .fade {
    animation: fade var(--dur-2) var(--ease) backwards;
  }
  @keyframes fade {
    from {
      opacity: 0;
    }
  }
  .list {
    flex: 1;
    overflow-y: auto;
    padding: 0.75rem;
    display: flex;
    flex-direction: column;
    gap: 1.1rem;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 1.1rem 0.5rem;
    padding: 0.4rem 0.1rem;
  }
  .app {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.4rem;
    min-width: 0;
    padding: 0.25rem 0;
    font-size: 1em;
  }
  .icon {
    display: grid;
    place-items: center;
    width: 3.6rem;
    height: 3.6rem;
    border: 1px solid var(--border);
    border-radius: 16px;
    background: var(--card);
    color: var(--foreground);
    font: 600 1.35em var(--mono);
  }
  .app:active .icon {
    background: var(--accent);
  }
  .name {
    max-width: 100%;
    font-size: 0.8em;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .empty {
    color: var(--muted-foreground);
    padding: 1rem 0.25rem;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }
  .empty strong {
    color: var(--foreground);
  }
  .error {
    color: var(--danger);
  }
</style>
