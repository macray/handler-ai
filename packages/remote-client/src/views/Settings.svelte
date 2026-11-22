<script lang="ts">
  // The Settings tab: this phone in a card (its name, the computer it is paired with, what it can
  // do), then a row per page: Appearance, Notifications, Voice (the owner's), Connection (the chain
  // and the ids); Forget this phone set apart at the bottom.
  import { app } from "../lib/app.svelte";
  import { computerName } from "../lib/pairing";
  import { theme } from "../lib/theme.svelte";
  import Appearance from "./Appearance.svelte";
  import Connection from "./Connection.svelte";
  import { status } from "./Lights.svelte";
  import ListHeader from "./ListHeader.svelte";
  import PageHeader from "./PageHeader.svelte";
  import Slide from "./Slide.svelte";

  type Page = "appearance" | "notifications" | "voice" | "connection";
  let page = $state<Page | null>(null);
  const back = (): void => void (page = null);
  const THEME_WORDS = { system: "System", light: "Light", dark: "Dark" } as const;

  const device = $derived(app.device);
  const link = $derived(status(app.mailbox));
  // the computer's name, given when paired (its host id for a phone paired before it had one)
  const computer = $derived(device ? computerName(device) : "");
  const owner = $derived(app.scope === "all");
  const pushed = $derived(app.pushOn && app.pushChoices.some((k) => app.pushWants(k)));
  const aloud = $derived(
    app.voice.readAloudSpoken && app.voice.readAloudTyped
      ? "always"
      : app.voice.readAloudSpoken
        ? "spoken"
        : app.voice.readAloudTyped
          ? "typed"
          : "never",
  );

  const PUSH_WORDS = {
    "needs-you": {
      label: "When a session needs you",
      hint: "A shared session asks you something.",
      aria: "Notify this phone when a session needs you",
    },
    "app-news": {
      label: "When an app has news",
      hint: "A message from an app, or a call you left for your computer has run.",
      aria: "Notify this phone when an app has news",
    },
  } as const;

  // Forget this phone cannot be undone: a sheet asks, a slide confirms
  let forgetting = $state(false);
</script>

<svelte:window onkeydown={(e) => e.key === "Escape" && (forgetting = false)} />

{#snippet icon(name: Page)}
  <span class="icon" aria-hidden="true">
    <svg viewBox="0 0 24 24">
      {#if name === "appearance"}<circle cx="12" cy="12" r="9" /><path d="M12 3v18a9 9 0 0 0 0-18Z" fill="currentColor" />
      {:else if name === "notifications"}<path d="M10.27 21a2 2 0 0 0 3.46 0M3.26 15.33A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.67C19.41 13.96 18 12.5 18 8A6 6 0 0 0 6 8c0 4.5-1.41 5.96-2.74 7.33" />
      {:else if name === "voice"}<path d="M12 19v3M19 10v2a7 7 0 0 1-14 0v-2" /><rect x="9" y="2" width="6" height="13" rx="3" />
      {:else}<rect x="4" y="4" width="16" height="12" rx="2" /><path d="M2 20h20" />{/if}
    </svg>
  </span>
{/snippet}

{#if page === "appearance"}
<Appearance onback={back} />
{:else if page === "connection"}
<Connection onback={back} />
{:else if page === "notifications"}
<PageHeader title="Notifications" back="Settings" onback={back} />
<main class="page" data-testid="notifications">
  <ul class="card">
    {#each app.pushChoices as kind (kind)}
      <li class="row">
        <span class="text">
          <span>{PUSH_WORDS[kind].label}</span>
          <span class="hint">{PUSH_WORDS[kind].hint}</span>
        </span>
        <button
          type="button"
          role="switch"
          class="switch"
          aria-checked={app.pushWants(kind)}
          aria-label={PUSH_WORDS[kind].aria}
          onclick={() => app.togglePush(kind)}
          data-testid="push-toggle-{kind}"
        ><span></span></button>
      </li>
    {/each}
  </ul>
  <p class="hint note">
    A short push that says only which of the two: you see the rest when you open Handler. On
    iPhone: add Handler to the home screen first.
  </p>
  {#if app.pushOn}
    <div class="card row">
      <span class="text">
        <span>Send a test notification</span>
        {#if app.pushTest === "sent"}
          <span class="hint" data-testid="push-test-sent">
            Two notifications: "Test 1 of 2: shown by this phone", then "Something new for you" from
            your computer within a few seconds. Only the first? The push is lost on its way to this
            phone. Neither? This phone's settings block notifications (its own, or the browser's).
          </span>
        {:else}
          <span class="hint">Checks that this phone shows notifications, then that your computer's reach it.</span>
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
</main>
{:else if page === "voice"}
<PageHeader title="Voice" back="Settings" onback={back} />
<main class="page" data-testid="voice">
  <ul class="card">
    <li class="row">
      <span class="text">
        <span>Speak to Ask</span>
        <span class="hint">{app.voice.listens ? "Hold the microphone on Ask and say it." : "Off: your computer has no model that writes down what you say."}</span>
      </span>
      <span class="value">{app.voice.listens ? "on" : "off"}</span>
    </li>
    <li class="row">
      <span class="text"><span>Answers read aloud when you spoke</span></span>
      <span class="value" data-testid="voice-read-spoken">{app.voice.readAloudSpoken ? "yes" : "no"}</span>
    </li>
    <li class="row">
      <span class="text"><span>Answers read aloud when you typed</span></span>
      <span class="value" data-testid="voice-read-typed">{app.voice.readAloudTyped ? "yes" : "no"}</span>
    </li>
  </ul>
  <p class="hint note">
    Read in this phone's own voice: nothing is sent anywhere. These are chosen on {computer}, in
    Settings → Voice.
  </p>
</main>
{:else}
<ListHeader title="Settings" />

<main class="page">
  <!-- this phone -->
  <div class="card me">
    <span class="icon big" aria-hidden="true">
      <svg viewBox="0 0 24 24"><rect x="6" y="2" width="12" height="20" rx="2" /><path d="M12 18h.01" /></svg>
    </span>
    <span class="text">
      <span class="name" data-testid="this-device">{device?.name}</span>
      <span class="hint">
        paired with <span data-testid="paired-with">{computer}</span> ·
        <span data-testid="this-device-can">{owner ? "answers your sessions, opens your apps" : `opens the apps shared with ${app.person}`}</span>
      </span>
    </span>
  </div>

  <ul class="card">
    <li>
      <button type="button" class="row link" onclick={() => (page = "appearance")} data-testid="open-appearance">
        {@render icon("appearance")}<span class="text">Appearance</span>
        <span class="value">{THEME_WORDS[theme.choice]}</span><span class="chev" aria-hidden="true">›</span>
      </button>
    </li>
    <li>
      <button type="button" class="row link" onclick={() => (page = "notifications")} data-testid="open-notifications">
        {@render icon("notifications")}<span class="text">Notifications</span>
        <span class="value">{pushed ? "on" : "off"}</span><span class="chev" aria-hidden="true">›</span>
      </button>
    </li>
    {#if owner}
      <li>
        <button type="button" class="row link" onclick={() => (page = "voice")} data-testid="open-voice">
          {@render icon("voice")}<span class="text">Voice</span>
          <span class="value">read aloud: {aloud}</span><span class="chev" aria-hidden="true">›</span>
        </button>
      </li>
    {/if}
    <li>
      <button type="button" class="row link" onclick={() => (page = "connection")} title={link.title} data-testid="open-connection">
        {@render icon("connection")}<span class="text">Connection</span>
        <span class="value" data-testid="connected-to"><span class="light {link.light}" aria-hidden="true"></span>{link.words.toLowerCase()}</span>
        <span class="chev" aria-hidden="true">›</span>
      </button>
    </li>
  </ul>

  <div class="apart">
    <button type="button" class="danger" onclick={() => (forgetting = true)} data-testid="forget">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m18.84 12.25 1.72-1.71a5 5 0 0 0-7.07-7.07l-1.72 1.71M5.17 11.75l-1.71 1.71a5 5 0 0 0 7.07 7.07l1.71-1.71M8 2v3M2 8h3M16 22v-3M22 16h-3" /></svg>
      Forget this phone
    </button>
    <p class="hint">Removes its keys from this browser. Pairing again needs a new QR code from {computer || "your computer"}.</p>
  </div>
</main>
{#if forgetting}
  <button type="button" class="scrim" aria-hidden="true" tabindex="-1" onclick={() => (forgetting = false)}></button>
  <div class="sheet" role="dialog" aria-modal="true" aria-labelledby="forget-title" data-testid="forget-sheet">
    <span class="grab" aria-hidden="true"></span>
    <h4 id="forget-title">Forget this phone?</h4>
    <p>
      Its keys are erased from this browser, with what it kept (the last Home, your drafts).
      {computer || "Your computer"} no longer reaches it. To use it again: a new QR code from {computer || "your computer"}.
    </p>
    <Slide label="slide to forget" question="Forget this phone?" tone="danger" onconfirm={() => void app.forget()} testid="forget-slide" />
    <button type="button" class="cancel" onclick={() => (forgetting = false)} data-testid="forget-cancel">Cancel</button>
  </div>
{/if}
{/if}

<style>
  .page {
    flex: 1;
    overflow-y: auto;
    padding: 0.75rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }
  .card {
    border: 1px solid var(--border);
    border-radius: 12px;
    background: var(--card);
    overflow: hidden;
  }
  ul.card > li + li {
    border-top: 1px solid var(--border);
  }
  .me {
    display: flex;
    align-items: center;
    gap: 0.85rem;
    padding: 0.85rem 0.9rem;
  }
  .name {
    font: 600 1.02em/1.3 var(--mono);
    letter-spacing: -0.01em;
    overflow-wrap: anywhere; /* a long name wraps: it is read here, in full */
  }
  .icon {
    flex: none;
    display: grid;
    place-items: center;
    width: 2rem;
    height: 2rem;
    border-radius: 9px;
    background: var(--muted);
    color: var(--muted-foreground);
  }
  .icon.big {
    width: 2.75rem;
    height: 2.75rem;
    border: 1px solid var(--border);
    border-radius: 12px;
  }
  svg {
    width: 1.05rem;
    height: 1.05rem;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .row {
    width: 100%;
    min-height: 3.25rem;
    padding: 0.6rem 0.9rem;
    display: flex;
    align-items: center;
    gap: 0.8rem;
  }
  .link {
    font-size: 1em;
    text-align: left;
    color: inherit;
    border-radius: 0;
  }
  .link:active {
    background: var(--accent);
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
  .note {
    padding: 0 0.25rem;
  }
  .value {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    font: 0.78em var(--mono);
    color: var(--muted-foreground);
    white-space: nowrap;
  }
  .chev {
    font-size: 1.3em;
    line-height: 1;
    color: var(--muted-foreground);
  }
  .light {
    flex: none;
    width: 0.5rem;
    height: 0.5rem;
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
  /* set apart, at the bottom: it cannot be undone */
  .apart {
    margin-top: auto;
    padding-top: 1.5rem;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }
  .apart .hint {
    padding: 0 0.25rem;
    text-align: center;
  }
  .danger {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    min-height: 3rem;
    padding: 0.5rem 0.9rem;
    border: 1px solid color-mix(in srgb, var(--danger) 35%, var(--border));
    border-radius: 12px;
    background: var(--card);
    color: var(--danger);
    font-size: 1em;
    font-weight: 600;
  }
  /* Forget this phone's sheet, over a dimmed page */
  .scrim {
    position: fixed;
    inset: 0;
    z-index: 20;
    background: rgb(0 0 0 / 0.35);
    border: 0;
    border-radius: 0;
    animation: fade var(--dur-2) var(--ease) backwards;
  }
  .sheet {
    position: fixed;
    inset: auto 0 0 0;
    z-index: 21;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    padding: 1.4rem 1.1rem max(1.1rem, env(safe-area-inset-bottom));
    border-top: 1px solid var(--border);
    border-radius: 24px 24px 0 0;
    background: var(--card);
    box-shadow: 0 -20px 40px rgb(0 0 0 / 0.18);
    animation: rise var(--dur-3) var(--ease) backwards;
  }
  .grab {
    position: absolute;
    top: 0.5rem;
    left: 50%;
    translate: -50% 0;
    width: 2.5rem;
    height: 4px;
    border-radius: 999px;
    background: var(--border);
  }
  .sheet h4 {
    margin: 0;
    font: 700 20px/1.2 var(--mono);
    letter-spacing: -0.03em;
  }
  .sheet p {
    margin: 0;
    font-size: 0.9em;
    color: var(--muted-foreground);
  }
  .cancel {
    min-height: 2.75rem;
    font-size: 1em;
    font-weight: 600;
    color: var(--muted-foreground);
  }
  @keyframes fade {
    from {
      opacity: 0;
    }
  }
  @keyframes rise {
    from {
      transform: translateY(100%);
    }
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
