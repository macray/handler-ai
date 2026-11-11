<script lang="ts">
  // Settings → Secrets (D.14, E3): the keys and tokens of accounts, providers, tools'
  // connections and apps, kept by handler or where the person keeps them. By state: what needs
  // you first (a value missing; one an agent reads: that agent named,
  // and why, since what an agent reads it can send anywhere its network allows), each with the
  // page it is fixed on; then those in use, one line each by what they belong to (sealed: agents
  // hold a stand-in, Handler puts the value in their requests to its sites only), opened for the
  // rest; then those nothing uses, forgotten here. The counts filter the page.
  import AppWindow from "@lucide/svelte/icons/app-window";
  import ArrowRight from "@lucide/svelte/icons/arrow-right";
  import Check from "@lucide/svelte/icons/check";
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import Cpu from "@lucide/svelte/icons/cpu";
  import Eye from "@lucide/svelte/icons/eye";
  import KeyRound from "@lucide/svelte/icons/key-round";
  import Lock from "@lucide/svelte/icons/lock";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import User from "@lucide/svelte/icons/user";
  import Wrench from "@lucide/svelte/icons/wrench";
  import { Button } from "$lib/components/ui/button";
  import Dialog from "./Dialog.svelte";
  import { api } from "../lib/api";
  import { ago } from "../lib/agents";
  import type { SecretInfo } from "../lib/contracts.gen";
  import { href } from "../lib/router.svelte";
  import { GROUPS, agent, group, host, names, needsYou, owner, removable, source, stateOf, why } from "../lib/secrets";

  let secrets = $state<SecretInfo[] | null>(null);
  let tools = $state<Record<string, string>>({}); // each connection's tool, for its page
  let error = $state<string | null>(null);
  let busy = $state(false);
  let filter = $state<"all" | "needs" | "used" | "unused">("all");
  let opened = $state<string | null>(null);
  let forgetting = $state<SecretInfo | null>(null); // the one Forget asks about
  let asking = $state(false);

  const load = () =>
    api.secrets().then(
      (list) => (secrets = list),
      (e: Error) => (error = e.message),
    );
  void load();
  api.bindings().then(
    (list) => (tools = Object.fromEntries(list.filter((b) => b.addon).map((b) => [b.name, b.addon!]))),
    () => {},
  );

  async function forget(s: SecretInfo): Promise<void> {
    busy = true;
    error = null;
    try {
      await api.deleteSecret(s.path);
      asking = false;
      await load();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  const needs = $derived((secrets ?? []).filter(needsYou).sort((x, y) => Number(stateOf(y) === "missing") - Number(stateOf(x) === "missing")));
  const used = $derived((secrets ?? []).filter((s) => ["sealed", "readable"].includes(stateOf(s))));
  const unused = $derived((secrets ?? []).filter((s) => stateOf(s) === "unused"));
  const byGroup = $derived(GROUPS.map((g) => ({ ...g, rows: used.filter((s) => group(s) === g.id) })).filter((g) => g.rows.length));
  const filters = $derived(
    [
      { id: "all", label: "All", n: secrets?.length ?? 0 },
      { id: "needs", label: "Needs you", n: needs.length },
      { id: "used", label: "In use", n: used.length },
      { id: "unused", label: "Not used", n: unused.length },
    ].filter((f) => f.id === "all" || f.n) as { id: typeof filter; label: string; n: number }[],
  );
  // the filter chosen, or All once it lists nothing (its last secret forgotten)
  const shown = $derived(filters.some((f) => f.id === filter) ? filter : "all");
  const shows = (id: typeof filter) => shown === "all" || shown === id;
  const ICONS: Record<string, typeof User> = { accounts: User, providers: Cpu, connections: Wrench, apps: AppWindow };
  const GRID = "grid grid-cols-[1rem_minmax(0,1.3fr)_minmax(0,1.5fr)_minmax(0,1fr)_6.5rem_1rem] items-center gap-x-4 px-4";
</script>

{#snippet name(s: SecretInfo)}
  {@const n = names(s)}
  <span class="truncate font-medium" data-testid="secret-title">{n.owner} <span class="font-normal text-muted-foreground">{n.slot}</span></span>
{/snippet}

{#snippet link(s: SecretInfo)}
  {@const o = owner(s.usedBy![0]!, tools)}
  <Button variant="outline" size="sm" href={o.href} data-testid="secret-change">{o.page} <span class="text-muted-foreground">›</span> {o.name}<ArrowRight /></Button>
{/snippet}

<!-- the agents, each a chip; more than `max`: their number only (the line opened lists them) -->
{#snippet chips(labels: string[] | undefined, tone = "", max = Infinity)}
  {#if labels && labels.length > max}
    <span class="text-muted-foreground" data-testid="secret-agents-count">{labels.length} agents</span>
  {:else if labels?.length}
    <span class="flex min-w-0 flex-wrap items-center gap-1.5">
      {#each labels as label (label)}
        {@const a = agent(label)}
        <span class="rounded-md px-1.5 py-0.5 text-xs font-medium whitespace-nowrap {tone || 'bg-muted'}">{a.name}{#if a.project}<span class="ml-1 font-normal opacity-70">{a.project}</span>{/if}</span>
      {/each}
    </span>
  {:else}
    <span class="text-muted-foreground">no agent</span>
  {/if}
{/snippet}

{#snippet heading(label: string, n: number, legend = false)}
  <h2 class="flex items-center gap-2 text-sm font-medium">
    {label} <span class="font-normal text-muted-foreground">{n}</span>
    {#if legend}
      <span class="ml-auto flex items-center gap-4 text-xs font-normal text-muted-foreground">
        <span class="flex items-center gap-1"><Lock class="size-3 text-ok" />sealed: agents hold a stand-in</span>
        {#if used.some((s) => s.visible)}<span class="flex items-center gap-1"><Eye class="size-3" />readable</span>{/if}
      </span>
    {/if}
  </h2>
{/snippet}

<section class="space-y-8" data-testid="secrets">
  {#if secrets && !secrets.length}
    <div class="rounded-[10px] border border-dashed px-6 py-10 text-center text-sm">
      <span class="mx-auto mb-3 flex size-10 items-center justify-center rounded-lg bg-muted text-muted-foreground"><KeyRound class="size-5" /></span>
      <p class="font-medium">They come with what you connect</p>
      <div class="mt-4 flex justify-center gap-2">
        <Button variant="outline" size="sm" href={href({ view: "settings", section: "models" })}><KeyRound />Model access</Button>
        <Button variant="outline" size="sm" href={href({ view: "library", shelf: "tools" })}><Wrench />Library <span class="text-muted-foreground">›</span> Tools</Button>
      </div>
    </div>
  {:else if secrets}
    {#if filters.length > 2}
      <div class="inline-flex rounded-lg bg-muted p-0.5 text-sm" role="group" aria-label="show" data-testid="secrets-counts">
        {#each filters as f (f.id)}
          <button
            type="button"
            aria-pressed={shown === f.id}
            class="rounded-md px-3 py-1 {shown === f.id ? 'bg-background font-medium shadow-sm' : 'text-muted-foreground hover:text-foreground'}"
            onclick={() => (filter = f.id)}
            data-testid="secrets-filter-{f.id}"
            >{f.label} <span class="ml-0.5 {f.id === 'needs' ? 'font-semibold text-warn' : 'opacity-70'}">{f.n}</span></button>
        {/each}
      </div>
    {/if}

    {#if needs.length && shows("needs")}
      <div class="space-y-2" data-testid="secrets-needs">
        <h2 class="flex items-center gap-2 text-sm font-medium text-warn"><span class="size-2 rounded-full bg-warn"></span>Needs you</h2>
        <ul class="divide-y overflow-hidden rounded-[10px] border border-warn/40 bg-card text-sm shadow-panel">
          {#each needs as s (s.path)}
            <li class="flex items-center gap-4 px-4 py-3" data-testid="secret">
              {#if stateOf(s) === "missing"}
                <TriangleAlert class="size-4 shrink-0 text-warn" aria-label="not set" data-testid="secret-missing" />
              {:else}
                <Eye class="size-4 shrink-0 text-warn" aria-label="an agent can read it" data-testid="secret-visible" />
              {/if}
              <div class="min-w-0 flex-1 space-y-1">
                <p class="flex">{@render name(s)}</p>
                <p class="flex flex-wrap items-center gap-2 text-xs text-muted-foreground" data-testid="secret-why">
                  {#if stateOf(s) === "missing"}
                    <span class="rounded bg-warn/15 px-1.5 py-0.5 font-medium text-warn">Not set</span>{source(s)}
                  {:else}
                    {@render chips(s.agents, "bg-warn/15 text-warn")}<span>{s.agents!.length > 1 ? "read" : "reads"} it: {why(s.visible!)}</span>
                  {/if}
                </p>
              </div>
              {@render link(s)}
            </li>
          {/each}
        </ul>
      </div>
    {/if}

    {#if !needs.length && used.length && shows("used")}
      <p class="flex items-center gap-3 rounded-[10px] border bg-card px-4 py-3 text-sm font-medium shadow-panel" data-testid="secrets-fine">
        <span class="flex size-7 items-center justify-center rounded-md bg-ok/15 text-ok"><Check class="size-4" /></span>Every secret an agent gets is sealed
      </p>
    {/if}

    {#if used.length && shows("used")}
      <div class="space-y-2" data-testid="secrets-used">
        {@render heading("In use", used.length, true)}
        <div class="overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
          <div class="{GRID} border-b py-2 text-xs text-muted-foreground"><span></span><span>Secret</span><span>Agents</span><span>Sent only to</span><span>Last sent</span><span></span></div>
          {#each byGroup as g (g.id)}
            {@const Icon = ICONS[g.id]!}
            {#if byGroup.length > 1}
              <p class="flex items-center gap-1.5 border-b bg-muted/40 px-4 py-1.5 text-xs font-medium text-muted-foreground"><Icon class="size-3.5" />{g.label}</p>
            {/if}
            {#each g.rows as s (s.path)}
              {@const open = opened === s.path}
              <div class="border-b last:border-b-0" data-testid="secret">
                <button type="button" class="{GRID} w-full py-2.5 text-left hover:bg-muted/40" aria-expanded={open} onclick={() => (opened = open ? null : s.path)} data-testid="secret-open">
                  {#if s.visible}
                    <Eye class="size-4 text-muted-foreground" aria-label="readable, no agent gets it" data-testid="secret-visible" />
                  {:else}
                    <Lock class="size-4 text-ok" aria-label="sealed" data-testid="secret-hidden" />
                  {/if}
                  <span class="flex min-w-0">{@render name(s)}</span>
                  {@render chips(s.agents, "", 2)}
                  {#if s.visible}
                    <span class="truncate text-muted-foreground">{why(s.visible)}</span>
                  {:else if s.hosts?.length}
                    <span class="truncate font-mono text-xs">{host(s.hosts[0]!)}{#if s.hosts.length > 1}<span class="ml-1 font-sans text-muted-foreground">+{s.hosts.length - 1}</span>{/if}</span>
                  {:else}
                    <span class="text-muted-foreground">no site yet</span>
                  {/if}
                  <span class="text-muted-foreground">{s.lastSent ? ago(s.lastSent.t) : "–"}</span>
                  <ChevronDown class="size-4 text-muted-foreground transition-transform {open ? 'rotate-180' : ''}" />
                </button>
                {#if open}
                  <div class="flex items-end gap-6 border-t bg-muted/20 py-3 pr-4 pl-12 text-sm" data-testid="secret-details">
                    <dl class="grid flex-1 grid-cols-[7rem_1fr] gap-x-4 gap-y-1.5">
                      {#if s.visible}
                        <dt class="text-muted-foreground">Readable</dt><dd>{s.visible}</dd>
                      {:else}
                        <dt class="text-muted-foreground">Sealed</dt><dd>its agents hold a stand-in; Handler adds the value only to requests to its sites</dd>
                      {/if}
                      {#if s.agents?.length}<dt class="text-muted-foreground">Agents</dt><dd>{@render chips(s.agents)}</dd>{/if}
                      {#if !s.visible && s.hosts?.length}<dt class="text-muted-foreground">Sent only to</dt><dd class="font-mono text-xs">{s.hosts.map(host).join(", ")}</dd>{/if}
                      {#if s.lastSent}<dt class="text-muted-foreground">Last sent</dt><dd>{ago(s.lastSent.t)}, to <span class="font-mono text-xs">{host(s.lastSent.host)}</span></dd>{/if}
                      <dt class="text-muted-foreground">Value</dt><dd>{source(s)}{#if s.updatedAt}{" · "}changed {ago(s.updatedAt)}{/if}</dd>
                      <dt class="text-muted-foreground">Path</dt><dd class="font-mono text-xs">{s.path}</dd>
                    </dl>
                    {@render link(s)}
                  </div>
                {/if}
              </div>
            {/each}
          {/each}
        </div>
      </div>
    {/if}

    {#if unused.length && shows("unused")}
      <div class="space-y-2" data-testid="secrets-unused">
        {@render heading("Not used", unused.length)}
        <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
          {#each unused as s (s.path)}
            <li class="flex items-center gap-4 px-4 py-2.5" data-testid="secret">
              <KeyRound class="size-4 shrink-0 text-muted-foreground" />
              <p class="min-w-0 flex-1 truncate">
                <span class="font-medium" data-testid="secret-title">{s.description ?? s.path}</span>
                <span class="text-xs text-muted-foreground">{#if s.description}{" · "}<span class="font-mono">{s.path}</span>{/if}{#if s.createdAt}{" · "}added {ago(s.createdAt)}{/if}</span>
              </p>
              {#if removable(s)}
                <Button variant="ghost" size="sm" onclick={() => ((forgetting = s), (asking = true))} disabled={busy} data-testid="secret-remove">Forget</Button>
              {:else}
                <span class="text-xs text-muted-foreground">{source(s)}</span>
              {/if}
            </li>
          {/each}
        </ul>
      </div>
    {/if}
  {/if}
  {#if error}<p class="text-sm text-danger">{error}</p>{/if}
</section>

<Dialog bind:open={asking} title={`Forget “${forgetting?.description ?? forgetting?.path}”?`} testid="secret-forget">
  <p class="text-muted-foreground">Nothing uses it. Its value is deleted for good.</p>
  {#if forgetting?.description}<p class="mt-2 font-mono text-xs text-muted-foreground">{forgetting.path}</p>{/if}
  <div class="mt-6 flex justify-end gap-2">
    <Button variant="outline" onclick={() => (asking = false)}>Keep it</Button>
    <Button variant="destructive" onclick={() => forgetting && forget(forgetting)} disabled={busy} data-testid="secret-forget-confirm">Forget</Button>
  </div>
</Dialog>
