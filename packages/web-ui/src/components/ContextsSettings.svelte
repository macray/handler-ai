<script lang="ts">
  // Project contexts (D.19): Work, Personal, a client. A project may have one; then only the
  // accounts and providers made for it (Model access) run its agents: a work account never on a
  // personal project. Nothing else is split by context (knowledge, addons, skills are shared).
  // Each has a colour, shown on its projects and tags; kept while a project, an account or a
  // provider names it.
  import X from "@lucide/svelte/icons/x";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { api } from "../lib/api";
  import { COLORS, contexts } from "../lib/contexts.svelte";
  import type { ContextInfo, ContextRequest } from "../lib/contracts.gen";
  import ContextTag from "./ContextTag.svelte";

  let name = $state("");
  let color = $state<ContextRequest["color"]>(COLORS[0]!);
  let busy = $state(false);
  let error = $state<string | null>(null);

  void contexts.load();

  async function run(action: () => Promise<unknown>): Promise<boolean> {
    busy = true;
    error = null;
    try {
      await action();
      await contexts.load();
      return true;
    } catch (e) {
      error = (e as Error).message;
      return false;
    } finally {
      busy = false;
    }
  }

  async function add(): Promise<void> {
    if (await run(() => api.createContext({ name: name.trim(), color }))) name = "";
  }

  function users(c: ContextInfo): string[] {
    return [...(c.projects ?? []), ...(c.accounts ?? []), ...(c.providers ?? [])];
  }
</script>

{#snippet swatches(selected: string, pick: (c: ContextRequest["color"]) => void, label: string)}
  <div class="flex gap-1" role="radiogroup" aria-label={label}>
    {#each COLORS as c (c)}
      <button
        type="button"
        role="radio"
        aria-checked={selected === c}
        aria-label={c}
        title={c}
        class="ctx-{c} size-5 rounded-full border-2 {selected === c ? 'border-foreground' : 'border-transparent'}"
        style="background: var(--ctx)"
        disabled={busy}
        onclick={() => pick(c)}
        data-testid="context-color-{c}"
      ></button>
    {/each}
  </div>
{/snippet}

<section class="space-y-4" data-testid="contexts">
  <p class="max-w-2xl text-sm text-muted-foreground">
    A project can belong to a context: Work, Personal, a client. Then only the accounts and providers made for that context (set in Model access) run its agents, so a work account
    never works on a personal project. Knowledge, addons and skills stay shared by every context.
  </p>
  <div class="max-w-2xl space-y-3">
    {#if contexts.list.length}
      <ul class="divide-y rounded-lg border bg-card text-sm">
        {#each contexts.list as c (c.name)}
          <li class="flex items-center justify-between gap-3 px-3.5 py-2.5" data-testid="context-row">
            <div class="min-w-0 space-y-1">
              <ContextTag name={c.name} />
              <div class="truncate text-xs text-muted-foreground">
                {#if users(c).length}
                  {#if c.projects?.length}Projects: {c.projects.join(", ")}.{/if}
                  {#if c.accounts?.length || c.providers?.length}Made for it: {[...(c.accounts ?? []), ...(c.providers ?? [])].join(", ")}.{/if}
                {:else}Nothing in it yet{/if}
              </div>
            </div>
            <div class="flex items-center gap-3">
              {@render swatches(c.color, (picked) => void run(() => api.updateContext({ name: c.name, color: picked })), `Colour of ${c.name}`)}
              <Button
                variant="ghost"
                size="icon-sm"
                disabled={busy || users(c).length > 0}
                title={users(c).length ? `Used by ${users(c).join(", ")}` : undefined}
                aria-label={`Delete ${c.name}`}
                onclick={() => void run(() => api.deleteContext(c.name))}><X /></Button
              >
            </div>
          </li>
        {/each}
      </ul>
    {/if}
    <form class="flex items-center gap-3" onsubmit={(e) => (e.preventDefault(), void add())}>
      <Input class="h-8 w-56" placeholder="Work, Personal, a client…" maxlength={32} bind:value={name} data-testid="context-name" />
      {@render swatches(color, (picked) => (color = picked), "Colour of the new context")}
      <Button type="submit" variant="outline" size="sm" disabled={busy || !name.trim()} data-testid="context-add">Add</Button>
    </form>
    {#if error ?? contexts.error}<p class="text-sm text-danger" data-testid="context-error">{error ?? contexts.error}</p>{/if}
  </div>
</section>
