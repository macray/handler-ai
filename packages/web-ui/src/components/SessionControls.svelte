<script lang="ts">
  // Mode (session/set_mode) and select config options such as the model (session/set_config_option),
  // as chips. The harness's modes that are handler's permission modes are named as in the agent's
  // settings, the one acting without asking in amber (it weakens what the sandbox asks); its others
  // (e.g. a plan mode) keep the harness's name. The model alone (no harness) has neither.
  import type { SessionConfigOption } from "@agentclientprotocol/sdk";
  import type { AcpConnection } from "@handler/acp-view/lib/connection.svelte";
  import { PERMISSION_LABEL, permissionModes, type PermissionMode } from "../lib/agents";

  let { conn, harness }: { conn: AcpConnection; harness: string | null } = $props();

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
  const bypass = $derived(kinds?.[conn.session.currentMode ?? ""] === "bypass");

  let error = $state<string | null>(null);

  type Choice = { value: string; name: string };
  function choices(option: SessionConfigOption): Choice[] {
    if (option.type !== "select") return [];
    const list = option.options
      .flatMap((o) => ("options" in o ? o.options : [o]))
      .map((o) => ({ value: o.value, name: o.name }));
    // Always show the current value, even if the agent does not list it among the choices.
    if (!list.some((c) => c.value === option.currentValue)) {
      list.unshift({ value: option.currentValue, name: option.currentValue });
    }
    return list;
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
  {#if conn.session.modes.length && kinds}
    <label class="chip" class:bypass title={bypass ? "The agent acts without asking you first" : "When the agent asks you first"}>
      <span class="name">mode</span>
      {#if bypass}<span aria-hidden="true">⚠</span>{/if}
      <select
        value={conn.session.currentMode}
        onchange={(e) => guard(() => conn.setMode(e.currentTarget.value))}
        data-testid="mode-select"
      >
        {#each conn.session.modes as mode (mode.id)}<option value={mode.id}>{kinds[mode.id] ? PERMISSION_LABEL[kinds[mode.id]!] : mode.name}</option>{/each}
      </select>
    </label>
  {/if}
  {#each conn.session.configOptions.filter((o) => o.type === "select" && o.category !== "mode") as option (option.id)}
    <label class="chip">
      <span class="name">{option.name || option.id}</span>
      <select
        value={option.type === "select" ? option.currentValue : ""}
        onchange={(e) => guard(() => conn.setOption(option.id, e.currentTarget.value))}
      >
        {#each choices(option) as c (c.value)}<option value={c.value}>{c.name}</option>{/each}
      </select>
    </label>
  {/each}
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
  .chip.bypass {
    border-color: color-mix(in srgb, var(--warn) 60%, transparent);
    background: color-mix(in srgb, var(--warn) 10%, transparent);
    color: var(--warn);
  }
  .chip.bypass select {
    color: var(--warn);
    font-weight: 600;
  }
  @media (pointer: coarse) {
    .chip select {
      min-height: 2.5rem;
    }
  }
</style>
