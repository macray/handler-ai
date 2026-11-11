<script lang="ts">
  import { app } from "../lib/app.svelte";
</script>

<main class="page">
  <h1>Handler remote</h1>
  {#if app.offer}
    <p>Pair this browser with your computer?</p>
    <dl>
      <dt>this device</dt>
      <dd>{app.offer.name}</dd>
      <dt>host</dt>
      <dd><code>{app.offer.hostId}</code></dd>
    </dl>
    <p class="note">
      Once paired, this browser can read and drive the sessions you share from Handler. Its key stays in this browser
      (it cannot be read back, only used). Revoke it any time from Handler: Settings → Your phone.
    </p>
    {#if app.device}<p class="note">It replaces this browser's current pairing ({app.device.name}).</p>{/if}
    <div class="actions">
      <button type="button" class="primary" onclick={() => app.pair()} data-testid="pair">Pair</button>
      <button type="button" onclick={() => app.decline()}>Cancel</button>
    </div>
  {:else}
    <p>This browser is not paired with a computer.</p>
    <p class="note">
      On the computer running Handler: <strong>Settings → Your phone → Pair a device</strong>, then scan the QR code with this
      device (or open its link here).
    </p>
  {/if}
  {#if app.pairError}<p class="error" data-testid="pair-error">✗ {app.pairError}</p>{/if}
</main>

<style>
  .page {
    padding: 1.5rem 1.25rem;
    display: flex;
    flex-direction: column;
    gap: 0.9rem;
    max-width: 32rem;
  }
  h1 {
    font-size: 1.2em;
    font-weight: 600;
  }
  dl {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 0.25rem 1rem;
  }
  dt {
    color: var(--muted-foreground);
  }
  .note {
    color: var(--muted-foreground);
    font-size: 0.9em;
  }
  .actions {
    display: flex;
    gap: 0.75rem;
  }
  button {
    padding: 0.5rem 1.1rem;
    border: 1px solid var(--border);
    border-radius: 6px;
    font-size: 1em;
  }
  button.primary {
    color: var(--prompt);
    border-color: var(--prompt);
  }
  .error {
    color: var(--danger);
  }
</style>
