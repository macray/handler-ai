<script lang="ts">
  // What an agent can do (D.8), in the agent form: one row per setting, nothing folded. The
  // network first, its three modes each with its meter; "Only these sites" lists them in place:
  // those needed by what it uses (its model, its tools), locked with why, then yours (allowed or
  // kept blocked, removable), Add a site, and Learn the sites it needs (log only). Then the
  // switches: Asks before acting, Runs containers, Windows on my screen, Privileged. A switch that
  // weakens the sandbox turns its row amber when on; a save that widens is still confirmed
  // (save.widening-is-confirmed). No named preset.
  import Box from "@lucide/svelte/icons/box";
  import Eye from "@lucide/svelte/icons/eye";
  import Globe from "@lucide/svelte/icons/globe";
  import Lock from "@lucide/svelte/icons/lock";
  import MessageSquare from "@lucide/svelte/icons/message-square";
  import Monitor from "@lucide/svelte/icons/monitor";
  import Plus from "@lucide/svelte/icons/plus";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import X from "@lucide/svelte/icons/x";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import type { RuntimeSupports } from "../lib/contracts.gen";
  import { SEGMENT, SEGMENT_OFF, SEGMENT_ON } from "../lib/form";
  import { isEgressEntry, normalizeEntry, withList } from "../lib/hosts";
  import type { AgentSpec } from "../lib/projects.svelte";
  import { NETWORK_MODES, type NeededSite } from "../lib/safety";
  import NetworkMeter from "./NetworkMeter.svelte";
  import Switch from "./Switch.svelte";

  let {
    spec = $bindable(),
    job,
    offered,
    program,
    needed,
    gives,
    displayAvailable,
  }: {
    spec: AgentSpec;
    job: boolean; // it runs alone: it never asks
    offered?: string[]; // the permission modes its program has (all while unknown)
    program: string; // its program, as named: "pi"
    needed: NeededSite[]; // the sites what it uses needs
    gives: RuntimeSupports | null; // what this computer's sandboxes give (unknown: nothing greyed)
    displayAvailable: boolean; // the daemon found a display
  } = $props();

  const given = (level: RuntimeSupports["abilities"][number]) => gives === null || gives.abilities.includes(level);
  const noDisplay = $derived(gives !== null && !gives.abilities.includes("display"));

  // a site typed: allowed, or kept blocked
  let adding = $state(false);
  let typed = $state("");
  let typedError = $state<string | null>(null);
  const entry = $derived(normalizeEntry(typed));
  function addSite(list: "allow" | "blocked"): void {
    if (!isEgressEntry(entry)) {
      typedError = "a site is HOST:PORT, the port written out: example.com:443, *.example.com:443 for its subdomains";
      return;
    }
    Object.assign(spec, withList(spec, list, [...spec[list], entry]));
    [typed, typedError, adding] = ["", null, false];
  }
  function remove(list: "allow" | "blocked", host: string): void {
    Object.assign(spec, withList(spec, list, spec[list].filter((h) => h !== host)));
  }

  // asks before acting: on, before anything or all but file edits; off, never (bypass)
  const canAsk = $derived(!job && (offered === undefined || offered.includes("ask")));
  const asks = $derived(spec.permissions !== "bypass");
  const editsToo = $derived(offered === undefined || offered.includes("accept-edits"));

  // runs containers, unless privileged (which runs them too: turning it off goes back to them)
  let containersBefore = $state(false);
  function setPrivileged(on: boolean): void {
    if (on) containersBefore = spec.confinement === "nested";
    spec.confinement = on ? "privileged" : containersBefore ? "nested" : "strict";
  }

  const ROW = "flex items-center gap-3 px-4 py-3";
  const LABEL = "w-48 shrink-0 text-sm font-medium";
  const HINT = "min-w-0 flex-1 text-xs text-muted-foreground";
</script>

<section class="space-y-2" aria-labelledby="group-can" data-testid="agent-can-do">
  <h2 id="group-can" class="text-sm font-semibold">Can do</h2>
  <div class="divide-y overflow-hidden rounded-[10px] border bg-card shadow-panel">
    <div data-testid="agent-network">
      <div class="{ROW} flex-wrap">
        <Globe class="size-4 text-muted-foreground" />
        <span class="text-sm font-medium">Network</span>
        <div class="ml-auto inline-flex rounded-lg border bg-muted p-0.5" role="radiogroup" aria-label="network">
          {#each NETWORK_MODES as m (m.mode)}
            {@const on = spec.network === m.mode}
            <button
              type="button"
              role="radio"
              aria-checked={on}
              class="{SEGMENT} inline-flex items-center gap-2 {on ? SEGMENT_ON : SEGMENT_OFF}"
              onclick={() => (spec.network = m.mode)}
              data-testid="network-{m.mode}"
            >
              <NetworkMeter network={m.mode} />{m.label}
            </button>
          {/each}
        </div>
      </div>
      {#if spec.network === "none"}
        <p class="px-4 pb-3 pl-11 text-xs text-muted-foreground">Nothing, not even its model's API: for a model on this computer.</p>
      {:else if spec.network === "open"}
        <p class="px-4 pb-3 pl-11 text-xs text-warn" data-testid="agent-any-site">Anything on the internet and your network.</p>
      {:else}
        <div class="space-y-3 border-t border-dashed px-4 py-3 pl-11 text-sm" data-testid="agent-sites">
          <div class="space-y-1.5" data-testid="agent-required-hosts">
            <p class="text-xs font-medium text-muted-foreground">Needed by what it uses</p>
            {#each needed as s (s.host)}
              <p class="flex items-center gap-2" data-testid="needed-site">
                <Lock class="size-3.5 text-muted-foreground" /><span class="font-mono text-xs">{s.host}</span><span class="text-xs text-muted-foreground">{s.why}</span>
              </p>
            {:else}
              <p class="text-xs text-muted-foreground">None{spec.model.account || spec.model.provider ? "" : " yet: choose what it runs on"}.</p>
            {/each}
          </div>
          {#if spec.allow.length || spec.blocked.length}
            <div class="space-y-1" data-testid="agent-hosts">
              <p class="text-xs font-medium text-muted-foreground">Yours</p>
              {#each spec.allow as h (h)}
                <p class="flex items-center gap-2" data-testid="allow-entry">
                  <span class="font-mono text-xs">{h}</span>
                  <button type="button" class="ml-auto cursor-pointer rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground" aria-label="remove {h}" onclick={() => remove("allow", h)}><X class="size-3.5" /></button>
                </p>
              {/each}
              {#each spec.blocked as h (h)}
                <p class="flex items-center gap-2" data-testid="blocked-entry">
                  <span class="font-mono text-xs text-muted-foreground line-through">{h}</span><span class="text-xs text-muted-foreground">kept blocked</span>
                  <button type="button" class="ml-auto cursor-pointer rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground" aria-label="remove {h}" onclick={() => remove("blocked", h)}><X class="size-3.5" /></button>
                </p>
              {/each}
            </div>
          {/if}
          {#if adding}
            <div class="flex max-w-xl flex-wrap items-center gap-2">
              <Input
                bind:value={typed}
                class="h-8 w-64 font-mono text-xs"
                placeholder="example.com:443"
                aria-label="site"
                onkeydown={(e: KeyboardEvent) => e.key === "Enter" && (e.preventDefault(), addSite("allow"))}
                data-testid="agent-site-input"
              />
              <Button type="button" size="sm" variant="outline" disabled={!entry} onclick={() => addSite("allow")} data-testid="agent-site-allow">Allow</Button>
              <Button type="button" size="sm" variant="ghost" disabled={!entry} onclick={() => addSite("blocked")} data-testid="agent-site-block">Keep blocked</Button>
              <Button type="button" size="sm" variant="ghost" onclick={() => ([adding, typed, typedError] = [false, "", null])}>Cancel</Button>
            </div>
            {#if typedError}<p class="text-xs text-danger">{typedError}</p>{/if}
          {:else}
            <p class="flex items-center gap-3">
              <Button type="button" size="sm" variant="outline" onclick={() => (adding = true)} data-testid="agent-add-site"><Plus />Add a site</Button>
              <span class="text-xs text-muted-foreground">or let it ask when it needs one</span>
            </p>
          {/if}
          <div class="flex items-center gap-3 border-t pt-3 {spec.egress === 'log-only' ? 'text-warn' : ''}">
            <Eye class="size-3.5 {spec.egress === 'log-only' ? '' : 'text-muted-foreground'}" />
            <span class="text-sm font-medium">Learn the sites it needs</span>
            <span class={HINT}>let every site through for now and list the new ones, then choose</span>
            <Switch
              checked={spec.egress === "log-only"}
              onchange={(on) => (spec.egress = on ? "log-only" : "enforce")}
              warn
              label="Learn the sites it needs"
              testid="agent-log-only"
            />
          </div>
        </div>
      {/if}
    </div>

    <div class="{ROW} flex-wrap" data-testid="agent-permissions">
      <MessageSquare class="size-4 text-muted-foreground" />
      <span class={LABEL}>Asks before acting</span>
      <span class={HINT}>
        {#if job}A job never asks: it works alone.{:else if !canAsk}{program} never asks.{:else if asks}you answer its requests{:else}or acts, and you follow{/if}
      </span>
      {#if asks && canAsk && editsToo}
        <div class="inline-flex rounded-lg border bg-muted p-0.5" role="radiogroup" aria-label="what it asks">
          {#each [{ mode: "ask", label: "Before anything" }, { mode: "accept-edits", label: "Not for file edits" }] as m (m.mode)}
            <button
              type="button"
              role="radio"
              aria-checked={spec.permissions === m.mode}
              class="{SEGMENT} text-xs {spec.permissions === m.mode ? SEGMENT_ON : SEGMENT_OFF}"
              onclick={() => (spec.permissions = m.mode as AgentSpec["permissions"])}
              data-testid="permissions-{m.mode}">{m.label}</button
            >
          {/each}
        </div>
      {/if}
      <Switch checked={asks} disabled={!canAsk && !asks} onchange={(on) => (spec.permissions = on ? "ask" : "bypass")} label="Asks before acting" testid="agent-asks" />
    </div>
    {#if asks && !canAsk && !job}
      <p class="px-4 py-2 text-xs text-danger">{program} does not ask: turn it off.</p>
    {/if}

    <div class="{ROW} {spec.confinement !== 'strict' ? 'bg-warn/5 text-warn' : ''}" data-testid="agent-containers">
      <Box class="size-4 {spec.confinement !== 'strict' ? '' : 'text-muted-foreground'}" />
      <span class={LABEL}>Runs containers</span>
      <span class={HINT}>
        {spec.confinement === "privileged" ? "a privileged sandbox runs them too" : given("nested") ? "podman inside its sandbox" : "not on this computer (Settings → Sandboxes)"}
      </span>
      <Switch
        checked={spec.confinement !== "strict"}
        disabled={spec.confinement === "privileged" || (!given("nested") && spec.confinement === "strict")}
        onchange={(on) => (spec.confinement = on ? "nested" : "strict")}
        warn
        label="Runs containers"
        testid="confinement-nested"
      />
    </div>

    <div class="{ROW} {spec.display ? 'bg-warn/5 text-warn' : ''}" data-testid="agent-display">
      <Monitor class="size-4 {spec.display ? '' : 'text-muted-foreground'}" />
      <span class={LABEL}>Windows on my screen</span>
      <span class={HINT}>
        {noDisplay ? "sandboxes cannot show windows on this computer" : displayAvailable ? "can read what you copy" : "no display found"}
      </span>
      <Switch checked={spec.display} disabled={(!displayAvailable || noDisplay) && !spec.display} onchange={(on) => (spec.display = on)} warn label="Windows on my screen" testid="agent-display-switch" />
    </div>

    <div class="{ROW} {spec.confinement === 'privileged' ? 'bg-warn/5 text-warn' : ''}" data-testid="agent-privileged">
      <TriangleAlert class="size-4 {spec.confinement === 'privileged' ? '' : 'text-muted-foreground'}" />
      <span class={LABEL}>Privileged</span>
      <span class={HINT}>{given("privileged") ? "last resort: about as safe as no sandbox" : "not on this computer (Settings → Sandboxes)"}</span>
      <Switch
        checked={spec.confinement === "privileged"}
        disabled={!given("privileged") && spec.confinement !== "privileged"}
        onchange={setPrivileged}
        warn
        label="Privileged"
        testid="confinement-privileged"
      />
    </div>
  </div>
  {#if gives}<p class="text-xs text-muted-foreground">On this computer, each sandbox is {gives.isolation}.</p>{/if}
</section>
