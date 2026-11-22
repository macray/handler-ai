<script lang="ts">
  // Mode (session/set_mode) and select config options such as the model (session/set_config_option),
  // as chips. The harness's modes that are handler's permission modes are named as in the agent's
  // settings; its other modes keep the harness's name. The mode's chip is neutral unless the mode
  // is wider than the agent's own setting (`own`: switched for this session to ask less): amber
  // then, marked ⚠ (it weakens what the sandbox asks). The model alone (no harness) has neither.
  // Then how full the agent's context is, when its harness says.
  import type { SessionConfigOption } from "@agentclientprotocol/sdk";
  import type { AcpConnection } from "@handler/acp-view/lib/connection.svelte";
  import ContextMeter from "@handler/acp-view/components/ContextMeter.svelte";
  import { PERMISSION_LABEL, modeTone, modeWider, permissionModes, type PermissionMode } from "../lib/agents";

  let {
    conn,
    harness,
    own,
  }: { conn: AcpConnection; harness: string | null; own?: PermissionMode } = $props();

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
  const wider = (id: string) => modeWider(kinds?.[id], own);
  const options = $derived(conn.session.configOptions.filter((o) => o.type === "select" && o.category !== "mode"));
  // modes that only repeat a select option's values (pi's thinking levels, also its
  // `thought_level` option): shown once, as the option
  const modes = $derived.by(() => {
    const values = (o: SessionConfigOption) => (o.type === "select" ? o.options.flatMap((c) => ("options" in c ? c.options : [c])).map((c) => c.value) : []);
    const repeated = options.some((o) => conn.session.modes.length > 0 && conn.session.modes.every((m) => values(o).includes(m.id)));
    return repeated ? [] : conn.session.modes;
  });

  let error = $state<string | null>(null);

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

  /** A mode's glyph, as Claude Code marks them: plan ‖, edits ▸▸; ⚠ only when wider than the
   *  agent's own. */
  function glyph(id: string): string {
    if (wider(id)) return "⚠";
    return { plan: "‖", edits: "▸▸", bypass: "", ask: "" }[modeTone(id, kinds?.[id])];
  }

  async function guard(action: () => Promise<void>): Promise<void> {
    error = null;
    try {
      await action();
    } catch (e) {
      error = (e as Error).message;
    }
  }
</script>

<div class="controls">
  {#if modes.length && kinds}
    <label
      class="chip"
      class:wider={wider(current)}
      title={wider(current)
        ? "Wider than this agent's own setting, for this session: it asks you less (Shift+Tab: the next mode)"
        : "What the agent may do without asking you (Shift+Tab: the next mode)"}
      data-wider={wider(current)}
    >
      <span class="name">mode</span>
      {#if glyph(current)}<span aria-hidden="true">{glyph(current)}</span>{/if}
      <select value={conn.session.currentMode} onchange={(e) => guard(() => conn.setMode(e.currentTarget.value))} data-testid="mode-select">
        {#each modes as mode (mode.id)}<option value={mode.id}>{modeName(mode.id)}</option>{/each}
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
  /* a mode wider than the agent's own: amber (a risk), else neutral */
  .wider {
    --tone: var(--warn);
  }
  .chip.wider {
    border-color: color-mix(in srgb, var(--tone) 60%, transparent);
    background: color-mix(in srgb, var(--tone) 10%, transparent);
    color: var(--tone);
  }
  .chip.wider select {
    color: var(--tone);
    font-weight: 600;
  }
</style>
