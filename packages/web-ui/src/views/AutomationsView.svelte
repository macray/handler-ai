<script lang="ts">
  // The Library's Automations shelf (contract I): every automation, whatever it runs, each a
  // folder of ~/.config/handler-ai/automations. Yours: filtered by what they run (one of your
  // agents, an app's route, your script), a row each (AutomationRow: when → what it runs → where
  // → its last result, its switch), Pause all (each one off; on again from its page, the
  // approval) and New automation. Get more: the examples Handler ships, a script copied to your
  // folder, off, from a dialog.
  import FileCode from "@lucide/svelte/icons/file-code";
  import Plus from "@lucide/svelte/icons/plus";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import AutomationRow from "../components/AutomationRow.svelte";
  import Dialog from "../components/Dialog.svelte";
  import LoadingCards from "../components/LoadingCards.svelte";
  import ShelfBar from "../components/ShelfBar.svelte";
  import { api } from "../lib/api";
  import { runsKind, type RunsKind } from "../lib/automations";
  import type { Agent, AutomationExample, AutomationView } from "../lib/contracts.gen";
  import { SEGMENT, SEGMENT_OFF, SEGMENT_ON } from "../lib/form";
  import { LIBRARY_WIDTH } from "../lib/library";
  import { agentLabel, projects } from "../lib/projects.svelte";
  import { href, navigate } from "../lib/router.svelte";

  let { more = false }: { more?: boolean } = $props();

  let automations = $state<AutomationView[] | null>(null);
  let examples = $state<AutomationExample[]>([]);
  let agents = $state<Agent[]>([]);
  let error = $state<string | null>(null);
  let only = $state<RunsKind | "all">("all");
  let pausing = $state(false);
  let example = $state<AutomationExample | null>(null); // the example being copied
  let name = $state("");

  async function load(): Promise<void> {
    try {
      [automations, examples, agents] = await Promise.all([api.automations(), api.automationExamples(), api.agents()]);
      error = null;
    } catch (e) {
      error = (e as Error).message;
    }
  }

  $effect(() => {
    void load();
    const timer = setInterval(load, 5000); // runs start when sessions stop, at their times
    return () => clearInterval(timer);
  });

  const shown = $derived((automations ?? []).filter((a) => only === "all" || runsKind(a.definition) === only));
  const on = $derived((automations ?? []).filter((a) => a.enabled));
  const agentOf = (a: AutomationView) => agents.find((g) => g.id === a.agentId);

  /** Where it runs: its agent's project (or Chat, or outside projects), its app, or for a script
   *  read when a session stops, the projects it reads (every project when none is named). */
  function where(a: AutomationView): string {
    const kind = runsKind(a.definition);
    const run = a.definition?.run;
    if (kind === "agent") {
      const agent = agentOf(a);
      return agent?.projectId ? (projects.get(agent.projectId)?.name ?? "") : agent?.chat ? "Chat" : "outside projects";
    }
    if (kind === "app" && run && typeof run !== "string" && "app" in run) return run.app;
    if (kind === "script" && typeof a.definition?.when === "string") {
      return a.onlyProjects?.length ? a.onlyProjects.map((id) => projects.get(id)?.name ?? id).join(", ") : "every project";
    }
    return "";
  }

  async function pauseAll(): Promise<void> {
    if (!confirm(`Turn off ${on.length === 1 ? "the automation that is on" : `the ${on.length} automations that are on`}? Each one is turned on again from its page.`)) return;
    pausing = true;
    error = null;
    try {
      for (const a of on) await api.disableAutomation(a.name);
    } catch (e) {
      error = (e as Error).message;
    } finally {
      pausing = false;
      await load();
    }
  }

  function copy(ex: AutomationExample): void {
    example = ex;
    name = ex.name;
    error = null;
  }

  async function create(): Promise<void> {
    if (!example) return;
    error = null;
    try {
      const made = await api.createAutomation(name.trim(), { from: example.name });
      navigate({ view: "automation", name: made.name });
    } catch (e) {
      error = (e as Error).message;
    }
  }

  const FILTERS: { v: RunsKind | "all"; label: string }[] = [
    { v: "all", label: "All" },
    { v: "agent", label: "Agents" },
    { v: "app", label: "Apps" },
    { v: "script", label: "Scripts" },
  ];
</script>

<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full {LIBRARY_WIDTH} space-y-5 px-8 py-6">
    <ShelfBar>
      {#snippet filters()}
        {#if !more && automations?.length}
          <div class="inline-flex rounded-lg bg-muted p-0.5" role="radiogroup" aria-label="what they run">
            {#each FILTERS as f (f.v)}
              <button type="button" role="radio" aria-checked={only === f.v} class="{SEGMENT} {only === f.v ? SEGMENT_ON : SEGMENT_OFF}" onclick={() => (only = f.v)} data-testid="automations-only-{f.v}"
                >{f.label}</button
              >
            {/each}
          </div>
        {/if}
      {/snippet}
      {#snippet actions()}
        {#if !more}
          {#if on.length}<Button variant="outline" size="sm" disabled={pausing} onclick={pauseAll} data-testid="automations-pause-all">Pause all</Button>{/if}
          <Button size="sm" href={href({ view: "edit-automation" })} data-testid="new-automation"><Plus />New automation</Button>
        {/if}
      {/snippet}
    </ShelfBar>
    {#if error && !example}<p class="text-sm text-danger" data-testid="automations-error">{error}</p>{/if}

    {#if more}
      {#if examples.length}
        <ul class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" data-testid="automation-examples">
          {#each examples as ex (ex.name)}
            <li class="flex flex-col gap-3 rounded-xl border bg-card p-4 shadow-panel" data-testid="automation-example">
              <span class="flex items-center gap-3">
                <span class="flex size-11 shrink-0 items-center justify-center rounded-xl bg-muted text-muted-foreground"><FileCode class="size-5" /></span>
                <span class="min-w-0"><span class="block truncate font-semibold">{ex.name}</span><span class="fact block">a script · from Handler</span></span>
              </span>
              {#if ex.description}<p class="text-sm text-muted-foreground">{ex.description}</p>{/if}
              <div class="mt-auto flex justify-end">
                <Button size="sm" variant="outline" onclick={() => copy(ex)} data-testid="automation-from-example">Use it</Button>
              </div>
            </li>
          {/each}
        </ul>
      {:else}
        <p class="rounded-[10px] border border-dashed px-4 py-4 text-center text-sm text-muted-foreground">No example to get.</p>
      {/if}
    {:else if !automations}
      <div class="space-y-3"><LoadingCards count={2} height="h-16" /></div>
    {:else if automations.length}
      <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel" data-testid="automations">
        {#each shown as a (a.name)}
          {@const agent = agentOf(a)}
          <AutomationRow automation={a} agentName={agent ? agentLabel(agent) : undefined} where={where(a)} onchanged={load} />
        {/each}
      </ul>
      {#if !shown.length}<p class="text-sm text-muted-foreground">None runs that.</p>{/if}
    {:else}
      <div class="rounded-[10px] border border-dashed px-6 py-10 text-center text-sm text-muted-foreground" data-testid="no-automation">
        No automation yet: run one of your agents every morning, call one of your apps at a time, or a script of yours when a session stops.
      </div>
    {/if}
  </div>
</div>

<Dialog
  bind:open={() => example !== null, (v) => (v ? null : (example = null))}
  title={example ? `A script, from ${example.name}` : ""}
  description="It runs in a sandbox without network, may ask one of your models and adds to a note. It is copied to your automations folder, off, for you to edit in your editor."
  testid="automation-example-dialog"
>
  <form class="space-y-5" onsubmit={(e) => (e.preventDefault(), void create())}>
    <div class="space-y-1.5">
      <Label for="automation-name">Its name</Label>
      <Input id="automation-name" class="font-mono text-sm" placeholder="my-env-issues" bind:value={name} data-testid="automation-name" />
      <p class="text-xs text-muted-foreground">
        Lowercase letters, digits and dashes. Its files go to <span class="font-mono">~/.config/handler-ai/automations/{name.trim() || "<name>"}/</span>
      </p>
    </div>
    {#if error}<p class="text-danger" data-testid="automations-error">{error}</p>{/if}
    <div class="flex justify-end gap-2 border-t pt-4">
      <Button type="button" variant="ghost" size="sm" onclick={() => (example = null)}>Cancel</Button>
      <Button type="submit" size="sm" disabled={!/^[a-z0-9][a-z0-9-]{0,63}$/.test(name.trim())} data-testid="automation-create">Create</Button>
    </div>
  </form>
</Dialog>
