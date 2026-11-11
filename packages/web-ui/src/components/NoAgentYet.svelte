<script lang="ts">
  // A project with no agent yet (made alone, or its last agent deleted): a ready suggestion,
  // described not named ("An agent to work with you here", to talk with, on what you used last
  // or the one model ready, with what a new agent starts with), added in one click as
  // "Assistant"; then Set up an agent (the agent form) and Get agents… (Library → Agents → Get more
  // for this project: a source's, or an agents file). With no model
  // to suggest (none ready, or two or more and none used yet), only those two.
  import MessageSquare from "@lucide/svelte/icons/message-square";
  import Store from "@lucide/svelte/icons/store";
  import Plus from "@lucide/svelte/icons/plus";
  import { Button } from "$lib/components/ui/button";
  import type { AccountInfo, AddonInfo, Agent, Project, ProviderInfo } from "../lib/contracts.gen";
  import { api } from "../lib/api";
  import { productName } from "../lib/harnesses.svelte";
  import { agentBody, emptyAgent, projects, suggestedAccess } from "../lib/projects.svelte";
  import { href } from "../lib/router.svelte";
  import { neededSites, networkWords } from "../lib/safety";
  import NetworkMeter from "./NetworkMeter.svelte";

  let {
    project,
    onadded,
  }: {
    project: Project;
    onadded: (agent: Agent) => void;
  } = $props();

  let infos = $state<{ accounts: AccountInfo[]; providers: ProviderInfo[]; addons: AddonInfo[] } | null>(null);
  Promise.all([api.accounts(), api.providers(), api.addons(), projects.refresh()]).then(
    ([accounts, providers, addons]) => (infos = { accounts, providers, addons }),
    () => (infos = { accounts: [], providers: [], addons: [] }),
  );
  const model = $derived(infos ? suggestedAccess(projects.list, infos.accounts, infos.providers, project.area) : null);
  const sites = $derived(model && infos ? neededSites(model, project.addons ?? [], infos).length : 0);

  let busy = $state(false);
  let error = $state<string | null>(null);
  async function add(): Promise<void> {
    if (!model) return;
    busy = true;
    error = null;
    try {
      const spec = { ...emptyAgent(model), name: "Assistant" };
      onadded(await api.createAgent(agentBody(spec, { projectId: project.id })));
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

<section class="space-y-4 rounded-[14px] border border-dashed p-7" data-testid="no-agent">
  <h2 class="text-base font-semibold">No agent yet</h2>
  {#if model}
    <div class="flex items-center gap-3.5 rounded-[10px] border bg-card px-4 py-3 shadow-panel" data-testid="no-agent-suggestion">
      <span class="grid size-9 shrink-0 place-items-center rounded-lg bg-accent-soft text-primary"><MessageSquare class="size-4" /></span>
      <div class="min-w-0 flex-1">
        <p class="text-sm"><b class="font-semibold">An agent to work with you here</b> <span class="text-muted-foreground">· Talk</span></p>
        <p class="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
          <span>{productName(model.harness ?? "")}</span>·<span class="fact">{model.account ?? model.provider}</span>{#if model.model}·<span>{model.model}</span>{/if}·
          <NetworkMeter network="filtered" /><span>{networkWords("filtered", sites)}</span>
        </p>
      </div>
      <Button disabled={busy} onclick={add} data-testid="no-agent-add">Add it</Button>
    </div>
  {/if}
  <div class="flex flex-wrap items-center gap-2">
    <Button variant="outline" href={href({ view: "edit-agent", project: project.id })} data-testid="no-agent-set-up"><Plus />Set up an agent</Button>
    <Button variant="ghost" class="text-muted-foreground" href={href({ view: "library", shelf: "agents", more: true, project: project.id })} data-testid="no-agent-get"><Store />Get agents…</Button>
  </div>
  {#if error}<p class="text-sm text-danger">{error}</p>{/if}
</section>
