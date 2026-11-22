<script lang="ts">
  // A page under a tab (Settings → Appearance, Connection…): the one-line header (ListHeader's
  // mono title) with a way back to the tab.
  let { title, back, onback }: { title: string; back: string; onback: () => void } = $props();
</script>

<header class="bar">
  <button type="button" class="back" onclick={onback} aria-label="back to {back}">‹</button>
  <h1>{title}</h1>
</header>

<style>
  .bar {
    flex: none;
    display: flex;
    align-items: center;
    gap: 0.25rem;
    min-height: 2rem;
    padding: max(0.6rem, env(safe-area-inset-top)) 1rem 0.5rem 0.4rem;
  }
  .back {
    font-size: 1.6em;
    line-height: 1;
    padding: 0 0.4rem 0.15rem;
    color: var(--muted-foreground);
  }
  h1 {
    font: 700 19px/1.2 var(--mono);
    letter-spacing: -0.03em;
  }
</style>
