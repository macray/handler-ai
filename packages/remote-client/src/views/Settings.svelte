<script lang="ts">
  // This device: who it is on the host, its link to it, notifications — and forgetting the pairing.
  import { app } from "../lib/app.svelte";
  import { lights } from "./Lights.svelte";

  const device = $derived(app.device);
  const l = $derived(app.mailbox ? lights(app.mailbox) : null);

  function forget(): void {
    if (confirm("Forget this device's pairing? You will need a new QR code from Handler.")) void app.forget();
  }
</script>

<header class="bar">
  <button type="button" class="back" onclick={() => (app.settings = false)} aria-label="back to the list">‹</button>
  <h1>Settings</h1>
</header>

<main class="page">
  <section>
    <h2>This device</h2>
    <dl class="card">
      <div>
        <dt>Name</dt>
        <dd data-testid="this-device">{device?.name}</dd>
      </div>
      <div>
        <dt>For</dt>
        <dd>{app.person === "owner" ? "you (owner): sessions and apps" : `${app.person}: apps only`}</dd>
      </div>
      <div>
        <dt>Host</dt>
        <dd><code>{device?.hostId}</code></dd>
      </div>
      <div>
        <dt>Gateway</dt>
        <dd><code>{device?.gateway}</code></dd>
      </div>
    </dl>
  </section>

  {#if l}
    <section>
      <h2>Connection</h2>
      <ul class="card">
        <li><span class="light {l.gateway}"></span>{l.gatewayText}</li>
        <li><span class="light {l.host}"></span>{l.hostText}</li>
      </ul>
    </section>
  {/if}

  <section>
    <h2>Notifications</h2>
    <div class="card row">
      <span class="text">
        <span>Notify this device</span>
        <span class="hint">Content-free pushes when an app has news. On iPhone: add Handler to the home screen first.</span>
      </span>
      <button
        type="button"
        role="switch"
        class="switch"
        aria-checked={app.pushOn}
        aria-label="Notify this device"
        onclick={() => (app.pushOn ? app.disablePush() : app.enablePush())}
        data-testid="push-toggle"
      ><span></span></button>
    </div>
    {#if app.pushOn}
      <div class="card row">
        <span class="text">
          <span>Send a test notification</span>
          {#if app.pushTest === "sent"}
            <span class="hint" data-testid="push-test-sent">
              Two notifications: "Test 1 of 2: shown by this phone", then "Something new for you" from
              the host within a few seconds. Only the first? The push is lost on its way to this
              phone. Neither? This phone's settings block notifications (its own, or the browser's).
            </span>
          {:else}
            <span class="hint">Checks that this phone shows notifications, then that the host's reach it.</span>
          {/if}
        </span>
        <button
          type="button"
          class="secondary"
          disabled={app.pushTest === "sending"}
          onclick={() => app.testPush()}
          data-testid="push-test"
        >{app.pushTest === "sending" ? "Sending…" : "Send"}</button>
      </div>
    {/if}
    {#if app.pushError}<p class="error">{app.pushError}</p>{/if}
  </section>

  <section>
    <h2>Pairing</h2>
    <div class="card row">
      <span class="text">
        <span>Forget this device</span>
        <span class="hint">Removes its keys from this browser. Pairing again needs a new QR code from Handler.</span>
      </span>
      <button type="button" class="danger" onclick={forget}>Forget</button>
    </div>
  </section>
</main>

<style>
  .bar {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.6rem 0.75rem;
    padding-top: max(0.6rem, env(safe-area-inset-top));
    border-bottom: 1px solid var(--border);
    background: var(--card);
  }
  .back {
    font-size: 1.6em;
    line-height: 1;
    padding: 0 0.5rem 0.1rem;
  }
  h1 {
    font-size: 1.05em;
    font-weight: 600;
  }
  .page {
    flex: 1;
    overflow-y: auto;
    padding: 0.75rem 0.75rem max(1rem, env(safe-area-inset-bottom));
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
  }
  section {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  h2 {
    font-size: 0.75em;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--muted-foreground);
    padding: 0 0.25rem;
  }
  .card {
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--card);
  }
  .card:not(.row) > * {
    padding: 0.65rem 0.9rem;
  }
  .card:not(.row) > * + * {
    border-top: 1px solid var(--border);
  }
  dl div {
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
  }
  dt {
    font-size: 0.8em;
    color: var(--muted-foreground);
  }
  dd {
    overflow-wrap: anywhere; /* a long name wraps: it is read here, in full */
  }
  code {
    font-family: var(--mono);
    font-size: 0.85em;
  }
  li {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    font-size: 0.9em;
  }
  .light {
    flex: none;
    width: 0.6rem;
    height: 0.6rem;
    border-radius: 50%;
    background: var(--muted-foreground);
  }
  .light.ok {
    background: var(--ok);
  }
  .light.warn {
    background: var(--warn);
  }
  .light.danger {
    background: var(--danger);
  }
  .row {
    padding: 0.65rem 0.9rem;
    display: flex;
    align-items: center;
    gap: 0.9rem;
  }
  .text {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
  }
  .hint {
    font-size: 0.8em;
    color: var(--muted-foreground);
  }
  .switch {
    flex: none;
    position: relative;
    width: 2.75rem;
    height: 1.6rem;
    border-radius: 999px;
    background: var(--input);
    transition: background 0.15s;
  }
  .switch span {
    position: absolute;
    top: 0.2rem;
    left: 0.2rem;
    width: 1.2rem;
    height: 1.2rem;
    border-radius: 50%;
    background: white;
    box-shadow: 0 1px 2px rgb(0 0 0 / 0.25);
    transition: transform 0.15s;
  }
  .switch[aria-checked="true"] {
    background: var(--ok);
  }
  .switch[aria-checked="true"] span {
    transform: translateX(1.15rem);
  }
  .danger {
    flex: none;
    padding: 0.4rem 0.9rem;
    border: 1px solid var(--danger);
    border-radius: 8px;
    color: var(--danger);
    font-size: 0.9em;
  }
  .secondary {
    flex: none;
    padding: 0.4rem 0.9rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    font-size: 0.9em;
  }
  .secondary:disabled {
    opacity: 0.6;
  }
  .error {
    color: var(--danger);
    font-size: 0.85em;
    padding: 0 0.25rem;
  }
</style>
