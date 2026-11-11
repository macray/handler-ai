<script lang="ts">
  // A project's agents as one row of tabs that never wraps: names cut (whole in their tooltip),
  // the chosen one with its Edit pencil inside, then "+N more" (a menu, searched when long) for
  // those that do not fit, then + to add one. Kept in the row first: the chosen agent, then those
  // with a dot (waiting for you first), then the project's order; shown in the project's order.
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import Pencil from "@lucide/svelte/icons/pencil";
  import Plus from "@lucide/svelte/icons/plus";
  import Search from "@lucide/svelte/icons/search";
  import { Button } from "$lib/components/ui/button";
  import Popover from "./Popover.svelte";
  import SessionStatus from "./SessionStatus.svelte";
  import { USE_ICON } from "./UseChip.svelte";
  import type { Agent } from "../lib/contracts.gen";
  import { useOfAgent } from "../lib/interface";
  import { agentLabel } from "../lib/projects.svelte";
  import type { SessionStatus as Status } from "../lib/sessions.svelte";

  let {
    agents,
    chosen,
    dotOf,
    onchoose,
    edit,
    add,
  }: {
    agents: Agent[];
    chosen?: Agent;
    dotOf: (a: Agent) => Status | null;
    onchoose: (a: Agent) => void;
    edit: (a: Agent) => string; // its settings
    add: string; // a new agent's form
  } = $props();

  const GAP = 4; // the row's gap-1
  const ADD = 32; // the + button
  const MORE = 104; // "+N more" at its widest
  const SEARCH_FROM = 6; // more hidden than this: the menu has a search field

  let rowWidth = $state(0);
  let measure = $state<HTMLElement | null>(null);
  let widths = $state<Record<string, number>>({});
  let moreOpen = $state(false);
  let find = $state("");

  const dots = $derived(new Map(agents.map((a) => [a.id, dotOf(a)])));
  // every tab's width as drawn (the chosen one with its pencil), from a hidden copy of the row
  $effect(() => {
    void [agents.map((a) => `${a.id}:${agentLabel(a)}:${dots.get(a.id)}`).join(), chosen?.id];
    const next: Record<string, number> = {};
    for (const el of measure?.querySelectorAll<HTMLElement>("[data-id]") ?? []) next[el.dataset.id!] = el.offsetWidth;
    widths = next;
  });

  const rank = (a: Agent) => (a.id === chosen?.id ? 0 : dots.get(a.id) === "needs-you" ? 1 : dots.get(a.id) ? 2 : 3);
  const shown = $derived.by(() => {
    const all = agents.reduce((w, a) => w + (widths[a.id] ?? 0) + GAP, ADD);
    if (!rowWidth || all <= rowWidth) return new Set(agents.map((a) => a.id));
    const keep = new Set<string>();
    let used = ADD + MORE + GAP;
    for (const a of [...agents].sort((x, y) => rank(x) - rank(y))) {
      const w = (widths[a.id] ?? 0) + GAP;
      if (keep.size && used + w > rowWidth) continue; // a shorter one after it may still fit
      keep.add(a.id);
      used += w;
    }
    return keep;
  });
  const hidden = $derived(agents.filter((a) => !shown.has(a.id)));
  const hiddenDot = $derived(hidden.some((a) => dots.get(a.id) === "needs-you") ? "needs-you" : null);
  const found = $derived(find.trim() ? hidden.filter((a) => agentLabel(a).toLowerCase().includes(find.trim().toLowerCase())) : hidden);

  const titleOf = (a: Agent) => (a.description ? `${agentLabel(a)}: ${a.description}` : agentLabel(a));

  function pick(a: Agent, close: () => void): void {
    close();
    find = "";
    onchoose(a);
  }
</script>

{#snippet tab(a: Agent, live: boolean)}
  {@const Icon = USE_ICON[useOfAgent(a)]}
  {@const dot = dots.get(a.id)}
  {@const on = a.id === chosen?.id}
  <div class="agent-tab" class:on role="presentation" data-id={live ? undefined : a.id}>
    <button
      type="button"
      role={live ? "tab" : undefined}
      class="tab-main"
      aria-selected={live ? on : undefined}
      title={titleOf(a)}
      tabindex={live ? undefined : -1}
      onclick={() => onchoose(a)}
      data-testid={live ? "agent-row" : undefined}
    >
      <span class="grid size-6 shrink-0 place-items-center rounded-md bg-muted {on ? 'text-primary' : 'text-muted-foreground'}"><Icon class="size-3.5" /></span>
      <span class="name truncate" data-testid={live ? "agent-name" : undefined}>{agentLabel(a)}</span>
      {#if dot}<SessionStatus status={dot} />{/if}
    </button>
    {#if on}
      <a
        class="tab-edit"
        href={edit(a)}
        title="Edit {agentLabel(a)}"
        aria-label="Edit {agentLabel(a)}"
        tabindex={live ? undefined : -1}
        data-testid={live ? "agent-edit" : undefined}><Pencil class="size-3.5" /></a
      >
    {/if}
  </div>
{/snippet}

<div class="relative min-w-0">
  <div class="flex items-center gap-1" role="tablist" aria-label="agents" bind:clientWidth={rowWidth} data-testid="project-agents">
    {#each agents as a (a.id)}
      {#if shown.has(a.id)}{@render tab(a, true)}{/if}
    {/each}
    {#if hidden.length}
      <Popover bind:open={moreOpen} label="More agents" width="20rem" testid="agents-more-menu">
        {#snippet trigger(props)}
          <Button variant="outline" size="sm" class="shrink-0 gap-1.5 text-muted-foreground" {...props} title="The other agents" data-testid="agents-more">
            +{hidden.length} more
            {#if hiddenDot}<SessionStatus status={hiddenDot} title="One of them needs you" />{/if}
            <ChevronDown />
          </Button>
        {/snippet}
        {#snippet children(close)}
          {#if hidden.length > SEARCH_FROM}
            <label class="mb-1 flex items-center gap-2 border-b px-2.5 pb-1.5 text-muted-foreground">
              <Search class="size-3.5 shrink-0" />
              <!-- svelte-ignore a11y_autofocus -->
              <input bind:value={find} autofocus class="h-7 min-w-0 flex-1 bg-transparent text-sm text-foreground outline-none" placeholder="Find an agent…" aria-label="Find an agent" data-testid="agents-more-find" />
            </label>
          {/if}
          {#each found as a (a.id)}
            {@const Icon = USE_ICON[useOfAgent(a)]}
            {@const dot = dots.get(a.id)}
            <button type="button" class="menu-item" title={titleOf(a)} onclick={() => pick(a, close)} data-testid="agents-more-item">
              <Icon />
              <span class="min-w-0 flex-1 truncate">{agentLabel(a)}</span>
              {#if dot}<SessionStatus status={dot} />{/if}
            </button>
          {:else}
            <p class="px-2.5 py-1.5 text-xs text-muted-foreground">No agent by that name.</p>
          {/each}
        {/snippet}
      </Popover>
    {/if}
    <Button variant="ghost" size="icon" class="size-8 shrink-0 text-muted-foreground" href={add} title="Add an agent" aria-label="Add an agent" data-testid="add-agent"><Plus /></Button>
  </div>
  <!-- the same tabs, out of sight, to measure them -->
  <div bind:this={measure} class="pointer-events-none invisible absolute top-0 left-0 flex gap-1" aria-hidden="true" inert>
    {#each agents as a (a.id)}{@render tab(a, false)}{/each}
  </div>
</div>

<style>
  .agent-tab {
    display: inline-flex;
    flex: none;
    align-items: center;
    height: 38px;
    border-radius: 9px;
    color: var(--muted-foreground);
    font-size: 14px;
    white-space: nowrap;
  }
  .agent-tab:hover {
    color: var(--foreground);
  }
  .agent-tab.on {
    background: var(--card);
    color: var(--foreground);
    font-weight: 600;
    box-shadow:
      0 0 0 1px var(--border),
      0 1px 2px rgb(0 0 0 / 0.04);
  }
  .tab-main {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    height: 100%;
    min-width: 0;
    padding: 0 12px 0 6px;
    border-radius: inherit;
    cursor: pointer;
  }
  .agent-tab.on .tab-main {
    padding-right: 4px;
  }
  .name {
    max-width: 10rem;
  }
  .agent-tab.on .name {
    max-width: 15rem;
  }
  .tab-edit {
    display: grid;
    place-items: center;
    width: 26px;
    height: 26px;
    margin-right: 6px;
    border-radius: 6px;
    color: var(--muted-foreground);
  }
  .tab-edit:hover {
    background: var(--accent);
    color: var(--foreground);
  }
</style>
