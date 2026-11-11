<script lang="ts">
  // The set-up card of one of Handler's helpers (D.18), the same at each feature that needs one
  // (a project's Plans, Chat's Ask, Improve, Make your own apps, a skill's writing and review, and
  // the helper's page in Settings → Helpers): a veiled picture of the feature (`preview`), its
  // name, Who works (the program and the account or key with its model, or the model alone's one
  // chip, what cannot run it greyed with why), Works with (its skills and tools) and Can do (what
  // its feature fixes, locked, then its own settings), then Turn on: the agent is set up from the need's definition, outside
  // projects with no folder (each session works on what its feature gives it), and given to the
  // need; `onready` then (the feature goes on). Another agent of yours that fits may be given
  // instead. Turning it on confirms what it may do (D.8).
  import type { Snippet } from "svelte";
  import Lock from "@lucide/svelte/icons/lock";
  import { Button } from "$lib/components/ui/button";
  import { accessOf } from "../lib/access";
  import { api, toolboxChanges, type ToolboxChanges } from "../lib/api";
  import type { AddonInfo, Agent, HandlerNeed } from "../lib/contracts.gen";
  import { factsOf, featureOf, usesOf } from "../lib/helpers";
  import { firstChoice, missing, needOrigin, outsideAgentBody, type Choice } from "../lib/setup";
  import { freeName } from "../lib/text";
  import { agentLabel } from "../lib/projects.svelte";
  import { sessions } from "../lib/sessions.svelte";
  import HelperIcon from "./HelperIcon.svelte";
  import ModelChoice from "./ModelChoice.svelte";
  import NetworkMeter from "./NetworkMeter.svelte";
  import ToolboxConfirm from "./ToolboxConfirm.svelte";

  let {
    need: name,
    title,
    preview,
    onready,
  }: {
    need: string;
    title?: string; // the feature's name here ("Plans for shop-theme"); its own by default
    preview?: Snippet; // the feature, veiled: what it will do
    onready: (agent: Agent) => void;
  } = $props();

  let need = $state<HandlerNeed | null>(null);
  let agents = $state<Agent[]>([]);
  let choice = $state<Choice | null>(null);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let toolbox = $state<ToolboxChanges | null>(null);
  let tools = $state<AddonInfo[]>([]);

  const feature = $derived(featureOf(name));
  const facts = $derived(need ? factsOf(name, need.definition) : []);
  const uses = $derived(need ? usesOf(name, need.definition, tools) : []);
  const todo = $derived(need && choice ? missing(need.definition, choice, tools) : []);
  const fits = $derived((need?.fits ?? []).map((id) => agents.find((a) => a.id === id)).filter((a) => a !== undefined));

  $effect(() => {
    Promise.all([api.handlerNeeds(), api.agents(), api.addons()]).then(
      ([all, list, installed]) => {
        agents = list;
        tools = installed;
        need = all.find((n) => n.name === name) ?? null;
        if (need) choice = firstChoice(need.definition, [], installed, []);
        else error = `${name}: no such helper`;
      },
      (e: Error) => (error = e.message),
    );
  });

  async function turnOn(toolboxAdds: string[] = []): Promise<void> {
    if (!need || !choice) return;
    busy = true;
    error = null;
    toolbox = null;
    try {
      const d = need.definition;
      const taken = agents.filter((a) => !a.projectId && !a.scope).map((a) => a.name ?? "");
      const made = await api.createAgent({ ...outsideAgentBody(needOrigin(need), d, choice, null), name: freeName(d.agentName, taken, " "), toolboxAdds });
      sessions.updateAgent(made);
      await api.giveHandlerNeedAgent(need.name, made.id);
      onready(made);
    } catch (e) {
      if (!(toolbox = toolboxChanges(e))) error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  async function give(id: string): Promise<void> {
    if (!need || !id) return;
    busy = true;
    error = null;
    try {
      await api.giveHandlerNeedAgent(need.name, id);
      onready(agents.find((a) => a.id === id)!);
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

<div class="overflow-hidden rounded-xl border bg-card shadow-panel" data-testid="helper-card" data-need={name}>
  {#if preview}
    <div class="pointer-events-none border-b bg-muted/50 px-5 pt-4 pb-3 opacity-55 select-none" aria-hidden="true" inert>{@render preview()}</div>
  {/if}
  <div class="space-y-4 px-5 py-4">
    <p class="flex items-center gap-3 font-semibold"><HelperIcon icon={feature.icon} />{title ?? feature.feature}</p>
    {#if need && choice}
      {@const c = choice}
      <div class="grid items-start gap-x-4 gap-y-3 text-sm sm:grid-cols-[6rem_1fr]">
        <span class="pt-1 text-muted-foreground">Who works</span>
        <ModelChoice
          agent={{ id: "", name: need.definition.agentName, model: c.model, area: null, modelAlone: need.definition.modelAlone ?? false }}
          own
          onchange={(m) => (c.model = accessOf(m))}
        />
        {#if uses.length}
          <span class="pt-1 text-muted-foreground">Works with</span>
          <ul class="flex flex-wrap gap-1.5" data-testid="helper-works-with">
            {#each uses as u (u.key)}
              <li class="inline-flex items-center rounded-md bg-muted px-2 py-1 text-xs text-foreground/80" data-testid="helper-{u.key}">{u.label}: {u.text}</li>
            {/each}
          </ul>
        {/if}
        <span class="pt-1 text-muted-foreground">Can do</span>
        <ul class="flex flex-wrap gap-1.5" data-testid="helper-can-do">
          {#each facts as f (f.key)}
            <li
              class="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs {f.warn ? 'bg-warn/10 text-warn' : 'bg-muted text-foreground/80'}"
              title={f.locked ? `set by ${feature.feature}` : undefined}
            >
              {#if f.network}<NetworkMeter network={f.network} />{/if}{f.chip ?? f.text}{#if f.locked}<Lock class="size-3 opacity-60" />{/if}
            </li>
          {/each}
        </ul>
      </div>
      {#if toolbox}
        {@const t = toolbox}
        <ToolboxConfirm changes={t} {busy} action="Add and turn on" onconfirm={() => void turnOn(t.adds)} onback={() => (toolbox = null)} />
      {/if}
      {#if error}<p class="text-sm text-danger" data-testid="helper-error">{error}</p>{/if}
      <div class="flex flex-wrap items-center justify-end gap-3">
        {#if fits.length}
          <select
            class="mr-auto h-8 rounded-lg border bg-background px-2 text-sm text-muted-foreground"
            aria-label="or give it one of yours"
            value=""
            disabled={busy}
            onchange={(e) => give(e.currentTarget.value)}
            data-testid="helper-give"
          >
            <option value="" disabled>or one of yours…</option>
            {#each fits as a (a.id)}<option value={a.id}>{agentLabel(a)}</option>{/each}
          </select>
        {/if}
        <Button size="sm" disabled={busy || todo.length > 0} onclick={() => turnOn()} data-testid="helper-turn-on">Turn on</Button>
      </div>
    {:else if error}
      <p class="text-sm text-danger" data-testid="helper-error">{error}</p>
    {/if}
  </div>
</div>
