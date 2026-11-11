<script lang="ts">
  // An on/off switch (a setting's row): amber when on and `warn` (it weakens the sandbox).
  let {
    checked,
    onchange,
    disabled = false,
    warn = false,
    label,
    testid,
  }: { checked: boolean; onchange: (on: boolean) => void; disabled?: boolean; warn?: boolean; label: string; testid?: string } = $props();
</script>

<button
  type="button"
  role="switch"
  aria-checked={checked}
  aria-label={label}
  {disabled}
  class="switch"
  class:on={checked}
  class:warn
  onclick={() => onchange(!checked)}
  data-testid={testid}
>
  <span></span>
</button>

<style>
  .switch {
    position: relative;
    flex: none;
    width: 34px;
    height: 20px;
    border-radius: 999px;
    background: color-mix(in oklab, var(--foreground) 16%, transparent);
    cursor: pointer;
    transition: background var(--dur-1) var(--ease);
  }
  .switch span {
    position: absolute;
    top: 2px;
    left: 2px;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: var(--background);
    box-shadow: 0 1px 2px rgb(0 0 0 / 0.2);
    transition: transform var(--dur-1) var(--ease);
  }
  .switch.on {
    background: var(--primary);
  }
  .switch.on.warn {
    background: var(--warn-bar);
  }
  .switch.on span {
    transform: translateX(14px);
  }
  .switch:disabled {
    cursor: not-allowed;
    opacity: 0.5;
  }
  .switch:focus-visible {
    outline: 2px solid var(--ring);
    outline-offset: 2px;
  }
</style>
