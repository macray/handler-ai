<script lang="ts">
  // An agent in the list of its place (a project, or outside projects), to choose it: the icon of
  // how it is used, its name, one line (how it is used, then what it is for), and a dot when one of
  // its sessions waits for you, works or is open.
  import SessionStatus from "./SessionStatus.svelte";
  import { USE_ICON } from "./UseChip.svelte";
  import type { Agent } from "../lib/contracts.gen";
  import { USE_LABEL, useOfAgent } from "../lib/interface";
  import { agentLabel } from "../lib/projects.svelte";
  import type { SessionStatus as Status } from "../lib/sessions.svelte";

  let {
    agent,
    chosen,
    dot,
    about,
    onclick,
  }: { agent: Agent; chosen: boolean; dot: Status | null; about: string; onclick: () => void } = $props();

  const use = $derived(useOfAgent(agent));
  const Icon = $derived(USE_ICON[use]);
</script>

<li data-testid="agent-row">
  <button
    type="button"
    class="flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-left hover:bg-accent/60 {chosen ? 'bg-card shadow-panel hover:bg-card' : ''}"
    aria-current={chosen ? "true" : undefined}
    {onclick}
  >
    <span class="grid size-8 shrink-0 place-items-center rounded-md border bg-muted {chosen ? 'text-primary' : 'text-muted-foreground'}">
      <Icon class="size-4" />
    </span>
    <span class="min-w-0 flex-1 leading-tight">
      <span class="flex items-center gap-1.5">
        <span class="truncate text-sm font-medium" data-testid="agent-name">{agentLabel(agent)}</span>
      </span>
      <span class="block truncate text-xs text-muted-foreground">{USE_LABEL[use]} · {about}</span>
    </span>
    {#if dot}<SessionStatus status={dot} />{/if}
  </button>
</li>
