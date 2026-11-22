<script lang="ts">
  // The pair offer (a QR code's link): the computer and this phone named, what pairing lets it do,
  // the ids in a quiet Details line. The computer by its name (Settings → Your phone, on it).
  // Not paired and no offer: a state, said big, and the three steps to pair; the camera apps read
  // the QR code and open its link (a page cannot open them in that mode: no camera button).
  import { app } from "../lib/app.svelte";
  import { computerName } from "../lib/pairing";
  import BigState from "./BigState.svelte";
</script>

{#if app.offer}
  <header class="bar"><span class="t">Handler</span></header>

  <main class="page">
    <h1>Pair this phone with <span class="computer" data-testid="pair-computer">{computerName(app.offer)}</span>?</h1>
    <dl class="card">
      <div>
        <dt>Computer</dt>
        <dd>{computerName(app.offer)} · Handler, through your gateway</dd>
      </div>
      <div>
        <dt>This phone will be called</dt>
        <dd data-testid="pair-phone-name">{app.offer.name}</dd>
      </div>
    </dl>
    <p class="note">
      It will see the sessions you share from your computer (the <i>On your phone</i> icon in their header) and your apps,
      and answer them. Its key stays in this browser (it cannot be read back, only used). Remove it any time: on your
      computer, Settings → Your phone.
    </p>
    {#if app.device}<p class="note">It replaces this phone's current pairing ({app.device.name}).</p>{/if}
    <div class="actions">
      <button type="button" onclick={() => app.decline()}>Cancel</button>
      <button type="button" class="primary" onclick={() => app.pair()} data-testid="pair">Pair</button>
    </div>
    <p class="details" data-testid="pair-details">
      Details: host <code>{app.offer.hostId}</code> · this phone <code>{app.offer.deviceId}</code> · gateway
      <code>{app.offer.gateway}</code>
    </p>
    {#if app.pairError}<p class="error" data-testid="pair-error">✗ {app.pairError}</p>{/if}
  </main>
{:else}
  <div class="unpaired" data-testid="not-paired">
    <BigState title="Pair this phone" host="not paired" sub="with the computer running Handler">
      <main class="steps-page">
        <ol class="card steps">
          <li><span class="n" aria-hidden="true">1</span><span>On the computer, open Handler: <b class="mono">Settings → Your phone</b></span></li>
          <li><span class="n" aria-hidden="true">2</span><span><b class="mono">Pair a device</b>: a QR code shows</span></li>
          <li><span class="n" aria-hidden="true">3</span><span>Point this phone's camera at it: the link opens Handler here</span></li>
        </ol>
        {#if app.pairError}<p class="error" data-testid="pair-error">✗ {app.pairError}</p>{/if}
        <p class="key">The key stays in this browser, never sent anywhere.</p>
      </main>
    </BigState>
  </div>
{/if}

<style>
  .bar {
    display: flex;
    align-items: center;
    padding: 0.6rem 0.9rem;
    padding-top: max(0.6rem, env(safe-area-inset-top));
    border-bottom: 1px solid var(--border);
    background: var(--card);
  }
  .bar .t {
    font-weight: 600;
  }
  .page {
    padding: 1.4rem 1.1rem;
    display: flex;
    flex-direction: column;
    gap: 0.9rem;
    max-width: 32rem;
  }
  h1 {
    font-size: 1.3em;
    font-weight: 650;
    line-height: 1.3;
    overflow-wrap: anywhere;
  }
  .computer {
    color: var(--primary);
  }
  code {
    font-family: var(--mono);
    font-size: 0.9em;
  }
  .card {
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--card);
  }
  .card > div {
    padding: 0.6rem 0.9rem;
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
  }
  .card > div + div {
    border-top: 1px solid var(--border);
  }
  dt {
    font-size: 0.8em;
    color: var(--muted-foreground);
  }
  dd {
    overflow-wrap: anywhere;
  }
  .note {
    color: var(--muted-foreground);
    font-size: 0.9em;
  }
  .actions {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.75rem;
  }
  button {
    min-height: 2.75rem;
    padding: 0.5rem 1.1rem;
    border: 1px solid var(--border);
    border-radius: 10px;
    font-size: 1em;
    font-weight: 600;
  }
  button.primary {
    color: var(--primary-foreground);
    background: var(--primary);
    border-color: var(--primary);
  }
  .details {
    color: var(--muted-foreground);
    font-size: 0.78em;
    overflow-wrap: anywhere;
  }
  .error {
    color: var(--danger);
  }
  .unpaired {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .steps-page {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 0.9rem;
    padding: 0 0.75rem max(1rem, env(safe-area-inset-bottom));
    overflow-y: auto;
  }
  .steps li {
    display: flex;
    align-items: flex-start;
    gap: 0.8rem;
    padding: 0.85rem 0.9rem;
    line-height: 1.45;
  }
  .steps li + li {
    border-top: 1px solid var(--border);
  }
  .n {
    flex: none;
    display: grid;
    place-items: center;
    width: 1.6rem;
    height: 1.6rem;
    border-radius: 50%;
    background: var(--foreground);
    color: var(--page);
    font: 700 0.8em var(--mono);
  }
  .mono {
    font: 600 0.92em var(--mono);
    letter-spacing: -0.02em;
  }
  .key {
    margin-top: auto;
    text-align: center;
    font-size: 0.8em;
    color: var(--muted-foreground);
  }
</style>
