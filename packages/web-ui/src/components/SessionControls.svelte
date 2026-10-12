<script lang="ts">
  // Mode (session/set_mode) and select config options such as the model (session/set_config_option).
  // The harness's modes that are handler's permission modes are named as in the agent's settings; its
  // others (e.g. a plan mode) keep the harness's name.
  import type { SessionConfigOption } from "@agentclientprotocol/sdk";
  import type { AcpConnection } from "@handler/acp-view/lib/connection.svelte";
  import { modeLabels } from "../lib/agents";

  let { conn, harness }: { conn: AcpConnection; harness: string } = $props();

  let labels = $state<Record<string, string>>({});
  $effect(() => {
    modeLabels(harness).then((l) => (labels = l));
  });

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

<div class="controls flex flex-wrap items-center gap-4">
  {#if conn.session.modes.length}
    <label class="inline">
      mode
      <select
        value={conn.session.currentMode}
        onchange={(e) => guard(() => conn.setMode(e.currentTarget.value))}
        data-testid="mode-select"
      >
        {#each conn.session.modes as mode (mode.id)}<option value={mode.id}>{labels[mode.id] ?? mode.name}</option>{/each}
      </select>
    </label>
  {/if}
  {#each conn.session.configOptions.filter((o) => o.type === "select" && o.category !== "mode") as option (option.id)}
    <label class="inline">
      {option.name || option.id}
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
  .inline {
    display: flex;
    gap: 0.35rem;
    align-items: center;
    margin: 0;
  }
  .controls {
    gap: 1rem;
  }
</style>
