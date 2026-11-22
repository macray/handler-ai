<script lang="ts">
  // Slide to confirm what cannot be undone (a risky permission, Forget this phone): the knob is
  // dragged to the end of its track, or it springs back. The track is also a button, for a
  // keyboard and a screen reader: pressed, it asks again ("Allow once?") and a second press
  // confirms; the question goes away after a few seconds.
  let {
    label,
    question,
    tone = "ok",
    disabled = false,
    onconfirm,
    testid,
  }: {
    label: string; // "slide to allow once"
    question: string; // "Allow once?"
    tone?: "ok" | "danger";
    disabled?: boolean;
    onconfirm: () => void;
    testid?: string;
  } = $props();

  let track = $state<HTMLButtonElement>();
  let knob = $state<HTMLSpanElement>();
  let x = $state(0);
  let dragging = $state(false);
  let asking = $state(false);
  let moved = false; // a drag ends with a click on the track: not a press
  let timer: ReturnType<typeof setTimeout> | undefined;
  const PAD = 4;
  $effect(() => () => clearTimeout(timer));

  const end = (): number => (track && knob ? track.clientWidth - knob.offsetWidth - 2 * PAD - 2 : 0);

  function down(start: PointerEvent): void {
    if (disabled || !knob) return;
    knob.setPointerCapture(start.pointerId);
    dragging = true;
    moved = false;
    const move = (e: PointerEvent): void => {
      const dx = e.clientX - start.clientX;
      if (Math.abs(dx) > 4) moved = true;
      x = Math.min(Math.max(dx, 0), end());
    };
    const up = (): void => {
      knob?.removeEventListener("pointermove", move);
      dragging = false;
      if (moved && x >= end() * 0.9) {
        x = end();
        onconfirm();
      } else x = 0;
      setTimeout(() => (moved = false)); // after the click this pointer makes
    };
    knob.addEventListener("pointermove", move);
    knob.addEventListener("pointerup", up, { once: true });
    knob.addEventListener("pointercancel", up, { once: true });
  }

  function press(): void {
    if (moved || disabled) return;
    clearTimeout(timer);
    if (!asking) {
      asking = true;
      timer = setTimeout(() => (asking = false), 5000);
      return;
    }
    asking = false;
    onconfirm();
  }
</script>

<button
  bind:this={track}
  type="button"
  class="slide {tone}"
  class:asking
  class:dragging
  {disabled}
  onclick={press}
  aria-label={asking ? `${question} Press again to confirm.` : `${label}. Or press it twice.`}
  data-testid={testid}
>
  <span bind:this={knob} class="knob" style:translate="{x}px 0" onpointerdown={down} aria-hidden="true">
    <svg viewBox="0 0 24 24"><path d="m6 17 5-5-5-5" /><path d="m13 17 5-5-5-5" /></svg>
  </span>
  <span class="words" aria-hidden="true">{#if asking}{question} <small>press again</small>{:else}{label}{/if}</span>
</button>
<span class="sr-only" aria-live="assertive">{asking ? `${question} Press again to confirm.` : ""}</span>

<style>
  /* a track with the knob at its start: the words sit in the room left of it */
  .slide {
    position: relative;
    display: flex;
    align-items: center;
    width: 100%;
    height: 3.4rem;
    padding: 0 1rem 0 calc(46px + 1.25rem);
    border: 1px solid var(--slide-border) !important;
    border-radius: 999px !important;
    background: var(--slide-bg);
    color: var(--slide-fg);
    font: 600 13.5px var(--mono) !important;
    text-align: center;
    -webkit-tap-highlight-color: transparent;
  }
  .ok {
    --slide-bg: var(--muted);
    --slide-border: var(--border);
    --slide-fg: var(--muted-foreground);
    --knob: var(--slide-knob, var(--ok));
  }
  .danger {
    --slide-bg: color-mix(in srgb, var(--danger) 10%, var(--card));
    --slide-border: color-mix(in srgb, var(--danger) 30%, var(--border));
    --slide-fg: var(--danger);
    --knob: var(--danger);
  }
  .slide:focus-visible {
    outline: 2px solid var(--ring);
    outline-offset: 2px;
  }
  .asking {
    color: var(--foreground);
  }
  .words {
    flex: 1;
    min-width: 0;
  }
  small {
    font-size: 0.85em;
    font-weight: 400;
    color: var(--muted-foreground);
  }
  .knob {
    position: absolute;
    left: 4px;
    top: 50%;
    margin-top: -23px;
    display: grid;
    place-items: center;
    width: 46px;
    height: 46px;
    border-radius: 50%;
    background: var(--knob);
    color: var(--slide-on-knob, #fff);
    touch-action: none;
    cursor: grab;
    transition: translate var(--dur-2) var(--ease);
  }
  .dragging .knob {
    transition: none;
    cursor: grabbing;
  }
  svg {
    width: 1.15rem;
    height: 1.15rem;
    fill: none;
    stroke: currentColor;
    stroke-width: 2.2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
</style>
