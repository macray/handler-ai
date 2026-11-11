<script lang="ts">
  // One of Handler's helpers (D.18), built like an agent's settings: a tag for its feature and
  // where you meet it, Who works (its chips: a pick is saved to its agent), Works with (its skills,
  // those its tools bring, its tools; Change: its agent's page), Can do (what its feature fixes,
  // locked, "set by Plans"; its own settings with Change, its agent's page), its
  // instructions (editable; Back to Handler's: its definition's), and another agent of yours
  // that fits, given instead. Not set up yet: its set-up card.
  import Lock from "@lucide/svelte/icons/lock";
  import { Button } from "$lib/components/ui/button";
  import { Textarea } from "$lib/components/ui/textarea";
  import { accessOf, sameModel } from "../lib/access";
  import { api } from "../lib/api";
  import type { AddonInfo, Agent, HandlerNeed, ModelAccess } from "../lib/contracts.gen";
  import { factsOf, featureOf, settingsOf, usesOf } from "../lib/helpers";
  import { agentBody, agentLabel, agentSpec, homeOf } from "../lib/projects.svelte";
  import { href } from "../lib/router.svelte";
  import { sessions } from "../lib/sessions.svelte";
  import HelperCard from "./HelperCard.svelte";
  import HelperIcon from "./HelperIcon.svelte";
  import ModelChoice from "./ModelChoice.svelte";
  import NetworkMeter from "./NetworkMeter.svelte";

  let { need: name }: { need: string } = $props();

  let need = $state<HandlerNeed | null>(null);
  let agents = $state<Agent[]>([]);
  let agent = $state<Agent | null>(null);
  let tools = $state<AddonInfo[]>([]);
  let instructions = $state("");
  let busy = $state(false);
  let error = $state<string | null>(null);
  let loaded = $state(false);

  const feature = $derived(featureOf(name));
  const facts = $derived(agent ? factsOf(name, settingsOf(agent)) : []);
  const uses = $derived(agent ? usesOf(name, settingsOf(agent), tools) : []);
  const others = $derived((need?.fits ?? []).filter((id) => id !== agent?.id).map((id) => agents.find((a) => a.id === id)).filter((a) => a !== undefined));
  const shipped = $derived(need?.definition.instructions ?? "");

  async function load(): Promise<void> {
    try {
      const [all, list, installed] = await Promise.all([api.handlerNeeds(), api.agents(), api.addons()]);
      need = all.find((n) => n.name === name) ?? null;
      agents = list;
      tools = installed;
      agent = need?.agentId ? (list.find((a) => a.id === need!.agentId) ?? null) : null;
      instructions = agent?.instructions ?? "";
      if (!need) error = `${name}: no such helper`;
    } catch (e) {
      error = (e as Error).message;
    } finally {
      loaded = true;
    }
  }

  $effect(() => void load());

  /** Save a change to its agent: its model, or its instructions. A model save leaves the
   *  instructions being written as they are, and one that changes nothing is not sent (its chips
   *  give the agent's own model when they open). */
  async function save(change: { model?: ModelAccess; instructions?: string }): Promise<void> {
    if (!agent || (change.model && sameModel(change.model, agent.model))) return;
    busy = true;
    error = null;
    try {
      const spec = agentSpec(agent, { defaultAgent: null });
      agent = await api.updateAgent(
        agent.id,
        agentBody({ ...spec, ...(change.model ? { model: accessOf(change.model) } : {}), ...(change.instructions !== undefined ? { instructions: change.instructions } : {}) }, homeOf(agent)),
      );
      sessions.updateAgent(agent);
      if (change.instructions !== undefined) instructions = agent.instructions ?? "";
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  async function give(id: string): Promise<void> {
    if (!id) return;
    error = null;
    try {
      await api.giveHandlerNeedAgent(name, id);
      await load();
    } catch (e) {
      error = (e as Error).message;
    }
  }
</script>

<section class="space-y-8" data-testid="helper-page">
  <p class="flex flex-wrap items-center gap-2 text-sm">
    <span class="inline-flex items-center gap-1.5 rounded-md bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary"><HelperIcon icon={feature.icon} small />for {feature.feature}</span>
    <span class="text-muted-foreground">{feature.where}</span>
  </p>
  {#if error}<p class="text-sm text-danger" data-testid="helper-error">{error}</p>{/if}

  {#if need && agent}
    {@const a = agent}
    <div class="space-y-2">
      <h2 class="text-sm font-medium text-muted-foreground">Who works</h2>
      <div class="rounded-[10px] border bg-card px-4 py-3 shadow-panel" data-testid="helper-who-works">
        <ModelChoice agent={{ id: a.id, name: a.name, model: a.model, area: null, modelAlone: a.modelAlone ?? false }} own onchange={(m) => save({ model: m })} />
      </div>
    </div>

    {#if uses.length}
      <div class="space-y-2">
        <h2 class="text-sm font-medium text-muted-foreground">Works with</h2>
        <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel" data-testid="helper-works-with">
          {#each uses as u (u.key)}
            <li class="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3" data-testid="helper-{u.key}">
              <span class="w-36 shrink-0 font-medium">{u.label}</span>
              <span class="min-w-0 flex-1 text-muted-foreground">{u.text}</span>
              <a class="text-xs text-link hover:underline" href={href({ view: "edit-ad-hoc", id: a.id })}>Change</a>
            </li>
          {/each}
        </ul>
      </div>
    {/if}

    <div class="space-y-2">
      <h2 class="text-sm font-medium text-muted-foreground">Can do</h2>
      <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel" data-testid="helper-can-do">
        {#each facts as f (f.key)}
          <li class="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3">
            <span class="w-36 shrink-0 font-medium {f.warn ? 'text-warn' : ''}">{f.label}</span>
            <span class="flex min-w-0 flex-1 items-center gap-2 text-muted-foreground">{#if f.network}<NetworkMeter network={f.network} />{/if}{f.text}</span>
            {#if f.locked}
              <span class="flex items-center gap-1 text-xs text-muted-foreground" data-testid="helper-locked"><Lock class="size-3" />set by {feature.feature}</span>
            {:else}
              <a class="text-xs text-link hover:underline" href={href({ view: "edit-ad-hoc", id: a.id })}>Change</a>
            {/if}
          </li>
        {/each}
      </ul>
    </div>

    <div class="space-y-2">
      <div class="flex items-center justify-between">
        <h2 class="text-sm font-medium text-muted-foreground">Its instructions</h2>
        {#if shipped && instructions !== shipped}
          <button type="button" class="text-xs text-primary hover:underline" onclick={() => (instructions = shipped)} data-testid="helper-back-to-handlers">Back to Handler's</button>
        {/if}
      </div>
      <Textarea bind:value={instructions} rows={8} class="font-mono text-xs" data-testid="helper-instructions" />
      {#if instructions !== (a.instructions ?? "")}
        <div class="flex justify-end gap-2">
          <Button size="sm" variant="ghost" onclick={() => (instructions = a.instructions ?? "")}>Undo</Button>
          <Button size="sm" disabled={busy} onclick={() => save({ instructions })} data-testid="helper-save">Save</Button>
        </div>
      {/if}
    </div>

    {#if others.length}
      <p class="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
        <label for="helper-other">Use another of yours instead</label>
        <select id="helper-other" class="h-8 rounded-lg border bg-background px-2 text-sm" value="" onchange={(e) => give(e.currentTarget.value)} data-testid="helper-other">
          <option value="" disabled>Choose…</option>
          {#each others as o (o.id)}<option value={o.id}>{agentLabel(o)}</option>{/each}
        </select>
      </p>
    {/if}
  {:else if need && loaded}
    <div class="max-w-2xl">
      <HelperCard need={name} onready={() => void load()} />
    </div>
  {/if}
</section>
