<script lang="ts">
  // One app, full screen: its page in the sandboxed frame (public/appframe.html), its
  // backend calls carried to handler by this client.
  import { carry, type FrameFetch } from "../lib/apps";
  import { app } from "../lib/app.svelte";
  import Lights from "./Lights.svelte";

  let frame: HTMLIFrameElement | undefined = $state();
  let loads = 0;
  let leftFrame = $state(false); // the page navigated away: its frame is no longer the app

  // /appframe.html loads once; the app replaces its content without navigating. Another load
  // means the page sent the frame elsewhere: that document must not get the app's backend.
  function loaded(): void {
    loads += 1;
    if (loads > 1) {
      leftFrame = true;
      frame?.remove();
    }
  }

  const shared = $derived(app.currentApp);
  const page = $derived(app.page);

  // Only the frame's own messages, and only for this app: its code cannot reach anything else.
  $effect(() => {
    const name = shared?.name;
    const html = page?.html;
    if (!frame || !name || !shared || html === undefined) return;
    const target = frame;
    const onMessage = (event: MessageEvent): void => {
      if (event.source !== target.contentWindow || !app.mailbox || leftFrame) return;
      const m = event.data as { type?: string } | null;
      if (m?.type === "handler-frame-ready") {
        target.contentWindow?.postMessage({ type: "handler-app-load", html }, "*");
      } else if (m?.type === "handler-app-fetch") {
        void carry(app.mailbox, shared, m as FrameFetch).then((answer) =>
          // the frame is an opaque origin: "*" is the only target that reaches it
          target.contentWindow?.postMessage(answer, "*", answer.body ? [answer.body.buffer] : []),
        );
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  });
</script>

<header class="bar">
  <button type="button" class="back" onclick={() => app.closeApp()} aria-label="back to the list">‹</button>
  <div class="head">
    <span class="title">{shared?.name}</span>
    <span class="sub">
      {#if page?.cached}offline copy{#if shared?.queued?.length} — some actions wait for your computer{/if}
      {:else}{shared?.description ?? ""}{/if}
    </span>
  </div>
  {#if app.mailbox}<Lights mailbox={app.mailbox} />{/if}
</header>

{#if app.appLoading}
  <p class="note">Loading {shared?.name}…</p>
{:else if app.appError}
  <p class="note error">{app.appError}</p>
{:else if leftFrame}
  <p class="note error" data-testid="app-left">This app tried to open another page: it was closed.</p>
{:else if page}
  {#key page.version}
    <iframe
      bind:this={frame}
      onload={loaded}
      src="/appframe.html"
      title={shared?.name}
      sandbox="allow-scripts allow-forms allow-modals"
      data-testid="app-frame"
    ></iframe>
  {/key}
{/if}

<style>
  .bar {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.6rem 0.75rem;
    padding-top: max(0.6rem, env(safe-area-inset-top));
    border-bottom: 1px solid var(--border);
    background: var(--card);
  }
  .back {
    font-size: 1.6em;
    line-height: 1;
    padding: 0 0.4rem;
  }
  .head {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
  }
  .title {
    font-weight: 600;
  }
  .sub {
    font-size: 0.8em;
    color: var(--muted-foreground);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  iframe {
    flex: 1;
    width: 100%;
    border: 0;
    /* The app's own page background: when the app and this client use the same color scheme
       (a dark phone, an app with `color-scheme: light dark`), the frame is transparent and
       this shows through; a fixed white put light text on white. */
    background: Canvas;
  }
  .note {
    padding: 1.5rem 1rem;
    color: var(--muted-foreground);
  }
  .error {
    color: var(--danger);
  }
</style>
