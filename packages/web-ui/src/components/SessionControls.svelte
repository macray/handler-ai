<script lang="ts">
  // Mode (session/set_mode) and select config options such as the model (session/set_config_option),
  // as chips. The harness's modes that are handler's permission modes are named as in the agent's
  // settings; each mode's chip takes the colour of what it lets the agent do (plan teal, edits
  // without asking violet, acting without asking amber: it weakens what the sandbox asks); its
  // other modes keep the harness's name. The model alone (no harness) has neither. Then how full
  // the agent's context is, when its harness says.
  // `compact` (a phone): one pill (the mode, the model) that opens a sheet with all of them, each
  // mode said with what it lets the agent do, and the context in numbers.
  import type { SessionConfigOption } from "@agentclientprotocol/sdk";
  import type { AcpConnection } from "@handler/acp-view/lib/connection.svelte";
  import ContextMeter from "@handler/acp-view/components/ContextMeter.svelte";
  import { contextFill } from "@handler/acp-view/lib/session.svelte";
  import { dragSheet, flungDown } from "@handler/acp-view/lib/sheet";
  import { PERMISSION_LABEL, modeTone, permissionModes, type PermissionMode } from "../lib/agents";

  let { conn, harness, compact = false }: { conn: AcpConnection; harness: string | null; compact?: boolean } = $props();

  let kinds = $state<Record<string, PermissionMode> | null>(null); // null: not known yet, not shown
  $effect(() => {
    if (harness === null) {
      kinds = {};
      return;
    }
    permissionModes(harness).then(
      (k) => (kinds = k),
      () => (kinds = {}),
    );
  });
  const current = $derived(conn.session.currentMode ?? "");
  const tone = $derived(modeTone(current, kinds?.[current]));
  const bypass = $derived(tone === "bypass");
  const options = $derived(conn.session.configOptions.filter((o) => o.type === "select" && o.category !== "mode"));
  const fill = $derived(conn.session.usage ? contextFill(conn.session.usage) : null);

  let error = $state<string | null>(null);
  let open = $state(false); // the sheet (compact)

  type Choice = { value: string; name: string; description?: string | null };
  function choices(option: SessionConfigOption): Choice[] {
    if (option.type !== "select") return [];
    const list: Choice[] = option.options
      .flatMap((o) => ("options" in o ? o.options : [o]))
      .map((o) => ({ value: o.value, name: o.name, description: o.description }));
    // Always show the current value, even if the agent does not list it among the choices.
    if (!list.some((c) => c.value === option.currentValue)) {
      list.unshift({ value: option.currentValue, name: option.currentValue });
    }
    return list;
  }

  function modeName(id: string): string {
    const kind = kinds?.[id];
    return kind ? PERMISSION_LABEL[kind] : (conn.session.modes.find((m) => m.id === id)?.name ?? id);
  }

  /** A mode's glyph, as Claude Code marks them: plan ‖, edits ▸▸, acting without asking ⚠. */
  function glyph(id: string): string {
    return { plan: "‖", edits: "▸▸", bypass: "⚠", ask: "" }[modeTone(id, kinds?.[id])];
  }

  async function guard(action: () => Promise<void>): Promise<void> {
    error = null;
    try {
      await action();
    } catch (e) {
      error = (e as Error).message;
    }
  }

  function released(dy: number, velocity: number): boolean {
    if (!flungDown(dy, velocity)) return false;
    open = false;
    return true;
  }
</script>

{#if !compact}
  <div class="controls">
    {#if conn.session.modes.length && kinds}
      <label class="chip tone-{tone}" title={bypass ? "The agent acts without asking you first" : "What the agent may do without asking you (Shift+Tab: the next mode)"}>
        <span class="name">mode</span>
        {#if glyph(current)}<span aria-hidden="true">{glyph(current)}</span>{/if}
        <select value={conn.session.currentMode} onchange={(e) => guard(() => conn.setMode(e.currentTarget.value))} data-testid="mode-select">
          {#each conn.session.modes as mode (mode.id)}<option value={mode.id}>{modeName(mode.id)}</option>{/each}
        </select>
      </label>
    {/if}
    {#each options as option (option.id)}
      <label class="chip">
        <span class="name">{option.name || option.id}</span>
        <select value={option.type === "select" ? option.currentValue : ""} onchange={(e) => guard(() => conn.setOption(option.id, e.currentTarget.value))}>
          {#each choices(option) as c (c.value)}<option value={c.value}>{c.name}</option>{/each}
        </select>
      </label>
    {/each}
    <ContextMeter usage={conn.session.usage} />
    {#if error}<span class="text-danger">{error}</span>{/if}
  </div>
{:else}
  {@const model = options[0]}
  <button type="button" class="pill" onclick={() => (open = true)} aria-haspopup="dialog" title="Its mode, model and context" data-testid="session-settings">
    {#if conn.session.modes.length && kinds}<span class="mode tone-{tone}">{glyph(current)} {modeName(current)}</span>{/if}
    {#if model?.type === "select"}<span class="sep" aria-hidden="true">·</span><span class="model">{choices(model).find((c) => c.value === model.currentValue)?.name}</span>{/if}
    {#if error}<span class="text-danger">!</span>{/if}
    <span class="chev" aria-hidden="true">⌄</span>
  </button>
  {#if open}
    <button type="button" class="scrim" aria-label="close" onclick={() => (open = false)}></button>
    <div class="sheet" role="dialog" aria-label="session settings" data-sheet>
      <div class="handle" aria-hidden="true" {@attach dragSheet(released)}></div>
      <div class="sheet-head"><b>Session</b><button type="button" class="done" onclick={() => (open = false)}>Done</button></div>
      {#if error}<p class="text-danger px">{error}</p>{/if}
      {#if conn.session.modes.length && kinds}
        <fieldset>
          <legend>mode</legend>
          {#each conn.session.modes as mode (mode.id)}
            <label class="opt tone-{modeTone(mode.id, kinds[mode.id])}" class:on={mode.id === current}>
              <input type="radio" name="mode" value={mode.id} checked={mode.id === current} onchange={() => guard(() => conn.setMode(mode.id))} />
              <span class="what"><span class="nm">{glyph(mode.id)} {modeName(mode.id)}</span>{#if mode.description}<span class="ds">{mode.description}</span>{/if}</span>
            </label>
          {/each}
        </fieldset>
      {/if}
      {#each options as option (option.id)}
        <fieldset>
          <legend>{(option.name || option.id).toLowerCase()}</legend>
          {#each choices(option) as c (c.value)}
            <label class="opt" class:on={option.type === "select" && c.value === option.currentValue}>
              <input
                type="radio"
                name={option.id}
                value={c.value}
                checked={option.type === "select" && c.value === option.currentValue}
                onchange={() => guard(() => conn.setOption(option.id, c.value))}
              />
              <span class="what"><span class="nm">{c.name}</span>{#if c.description}<span class="ds">{c.description}</span>{/if}</span>
            </label>
          {/each}
        </fieldset>
      {/each}
      {#if fill}
        <fieldset>
          <legend>context</legend>
          <div class="ctx" title={fill.full}>
            {#if fill.percent !== null}<span class="bar" aria-hidden="true"><span style:width="{fill.percent}%"></span></span>{/if}
            <span>{fill.short}</span>
          </div>
        </fieldset>
      {/if}
    </div>
  {/if}
{/if}

<style>
  .controls {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.4rem;
  }
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    margin: 0;
    padding: 0 0.15rem 0 0.6rem;
    border: 1px solid var(--border);
    border-radius: 999px;
    color: var(--muted-foreground);
  }
  .chip select {
    border: none;
    background: transparent;
    color: var(--foreground);
    padding: 0.15rem 0.3rem;
    cursor: pointer;
  }
  .chip:focus-within {
    border-color: var(--primary);
  }
  /* a mode's colour: what it lets the agent do */
  .tone-plan {
    --tone: var(--mode-plan);
  }
  .tone-edits {
    --tone: var(--mode-edits);
  }
  .tone-bypass {
    --tone: var(--warn);
  }
  .chip:is(.tone-plan, .tone-edits, .tone-bypass) {
    border-color: color-mix(in srgb, var(--tone) 60%, transparent);
    background: color-mix(in srgb, var(--tone) 10%, transparent);
    color: var(--tone);
  }
  .chip:is(.tone-plan, .tone-edits, .tone-bypass) select {
    color: var(--tone);
    font-weight: 600;
  }
  @media (pointer: coarse) {
    .chip select {
      min-height: 2.5rem;
    }
  }
  /* a phone: one pill, a sheet */
  .pill {
    flex: 1;
    min-width: 0;
    height: 2.5rem;
    display: flex;
    align-items: center;
    gap: 0.8ch;
    padding: 0 0.9rem;
    border: 1px solid var(--border);
    border-radius: 999px;
    color: var(--muted-foreground);
    white-space: nowrap;
    overflow: hidden;
    font-size: 0.95em;
  }
  .pill .mode {
    color: var(--tone, var(--foreground));
  }
  .pill .model {
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .chev {
    margin-left: auto;
  }
  .scrim {
    position: fixed;
    inset: 0;
    z-index: 49;
    background: rgb(0 0 0 / 0.5);
    border: 0;
    cursor: default;
  }
  .sheet {
    position: fixed;
    inset: auto 0 0 0;
    z-index: 50;
    max-height: 88svh;
    overflow-y: auto;
    padding: 1.4rem 0 1.2rem;
    border-radius: 18px 18px 0 0;
    border-top: 1px solid var(--border);
    background: var(--popover);
    box-shadow: 0 -20px 40px -10px rgb(0 0 0 / 0.6);
    transition: transform var(--dur-3) var(--ease);
    animation: sheet-in var(--dur-3) var(--ease) backwards;
  }
  @keyframes sheet-in {
    from {
      transform: translateY(100%);
    }
  }
  .handle {
    position: absolute;
    inset: 0 0 auto 0;
    height: 1.5rem;
    touch-action: none;
    cursor: grab;
  }
  .handle::after {
    content: "";
    position: absolute;
    top: 0.5rem;
    left: 50%;
    translate: -50% 0;
    width: 2.5rem;
    height: 4px;
    border-radius: 999px;
    background: var(--border);
  }
  .sheet-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0 1.1rem 0.3rem;
  }
  .done {
    min-height: 2.5rem;
    padding: 0 0.6rem;
    color: var(--muted-foreground);
  }
  .px {
    padding: 0 1.1rem;
  }
  fieldset {
    border: 0;
    margin: 0;
    padding: 0.4rem 0 0;
  }
  legend {
    padding: 0.4rem 1.1rem 0.2rem;
    color: var(--muted-foreground);
    font-size: 0.85em;
  }
  .opt {
    display: flex;
    align-items: center;
    gap: 0.9rem;
    min-height: 2.9rem;
    padding: 0.25rem 1.1rem;
  }
  .opt.on {
    background: var(--muted);
  }
  .opt input {
    accent-color: var(--primary);
    width: 1.1rem;
    height: 1.1rem;
    flex: none;
  }
  .what {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .nm {
    color: var(--tone, var(--foreground));
  }
  .ds {
    color: var(--muted-foreground);
    font-size: 0.85em;
  }
  .ctx {
    display: flex;
    align-items: center;
    gap: 1ch;
    padding: 0.3rem 1.1rem;
    color: var(--muted-foreground);
  }
  .ctx .bar {
    flex: 1;
    height: 6px;
    border-radius: 3px;
    background: var(--border);
    overflow: hidden;
  }
  .ctx .bar > span {
    display: block;
    height: 100%;
    background: var(--muted-foreground);
  }
</style>
