<script lang="ts">
  // Export agents (D.23), from a project: some or all of its agents as one file, to set them up
  // in another project or to share. Each ticked agent says what of yours it leaves out and what
  // it becomes (handlerd's dry run), then what is kept; Export downloads the file.
  import Download from "@lucide/svelte/icons/download";
  import Info from "@lucide/svelte/icons/info";
  import { Button } from "$lib/components/ui/button";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import { api } from "../lib/api";
  import { slug } from "../lib/setup";
  import type { Agent, AgentsExport, ExportAgentsRequest } from "../lib/contracts.gen";
  import { useOfAgent } from "../lib/interface";
  import { agentLabel } from "../lib/projects.svelte";
  import Dialog from "./Dialog.svelte";
  import UseChip from "./UseChip.svelte";

  let {
    open = $bindable(false),
    projectId,
    place,
    agents,
  }: {
    open: boolean;
    projectId: string;
    place: string; // the project's name
    agents: Agent[];
  } = $props();

  let ticked = $state<string[]>([]);
  let draft = $state<AgentsExport | null>(null);
  let error = $state<string | null>(null);
  let busy = $state(false);

  // opened: every agent ticked
  $effect(() => {
    if (open) ticked = agents.map((a) => a.id);
  });

  const body = $derived<ExportAgentsRequest>({ name: slug(place), projectId, agentIds: [...ticked] as ExportAgentsRequest["agentIds"] });

  // what it would hold: handlerd's dry run, again when the agents change
  $effect(() => {
    const asked = body;
    if (!open || !asked.agentIds.length) {
      draft = null;
      return;
    }
    const timer = setTimeout(() => {
      api.exportAgentsDraft(asked).then(
        (d) => ((draft = d), (error = null)),
        (e: Error) => ((draft = null), (error = e.message)),
      );
    }, 150);
    return () => clearTimeout(timer);
  });

  /** What of yours one agent leaves out, from the dry run: "runs on … → …". */
  function replacedOf(a: Agent): { from: string; to: string }[] {
    const prefix = `${a.name ?? agentLabel(a)}: `;
    return (draft?.replaced ?? [])
      .filter((line) => line.startsWith(prefix))
      .map((line) => {
        const [from = "", to = ""] = line.slice(prefix.length).split(" → ");
        return { from, to };
      });
  }

  function keptOf(a: Agent): string {
    const part = draft?.file.agents.find((p) => p.part === slug(a.name ?? agentLabel(a)));
    const checks = part?.checks?.length ?? 0;
    return [
      a.instructions && "instructions",
      a.interface && (a.interface.result ? "its form and result" : "its form"),
      checks && `${checks} check${checks === 1 ? "" : "s"}, with their inputs and answers`,
      (part?.definition.skills?.length ?? 0) > 0 && `skills ${part?.definition.skills?.join(", ")}`,
    ]
      .filter(Boolean)
      .join(" · ");
  }

  function toggle(id: string, on: boolean): void {
    ticked = on ? [...ticked, id] : ticked.filter((x) => x !== id);
  }

  async function exportThem(): Promise<void> {
    busy = true;
    error = null;
    try {
      const { file, filename } = await api.exportAgents(body);
      const link = Object.assign(document.createElement("a"), { href: URL.createObjectURL(file), download: filename });
      link.click();
      URL.revokeObjectURL(link.href);
      open = false;
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

<Dialog
  bind:open
  title="Export agents"
  description="Some or all of the agents of {place}, as one file: to set them up in another project, here or on another computer. What is yours is left out: it is asked for when they are set up."
  wide
  testid="export-agents"
>
  <div class="space-y-4">
    <div>
      <h3 class="section-label mb-1">its agents</h3>
      <ul class="divide-y">
        {#each agents as a (a.id)}
          {@const on = ticked.includes(a.id)}
          <li class="grid grid-cols-[1.25rem_1fr] gap-x-2.5 py-2.5" data-testid="export-agents-agent">
            <Checkbox checked={on} onCheckedChange={(v) => toggle(a.id, v === true)} aria-label={agentLabel(a)} class="mt-0.5" />
            <div class="min-w-0 space-y-1 text-sm">
              <p class="flex items-center gap-2"><b class="font-semibold">{agentLabel(a)}</b><UseChip use={useOfAgent(a)} /></p>
              {#if on && draft}
                {#each replacedOf(a) as r (r.from)}
                  <p class="grid grid-cols-[1fr_1rem_1fr] items-baseline gap-2 text-xs">
                    <span class="fact text-muted-foreground line-through">{r.from}</span><span class="text-muted-foreground">→</span><span>{r.to}</span>
                  </p>
                {/each}
                {#if keptOf(a)}<p class="text-xs text-muted-foreground">kept: {keptOf(a)}</p>{/if}
              {/if}
            </div>
          </li>
        {/each}
      </ul>
    </div>

    <p class="flex gap-2 rounded-lg bg-muted/60 px-3 py-2 text-xs text-foreground/80">
      <Info class="mt-0.5 size-3.5 shrink-0" />Instructions and checks are written as you wrote them, names and examples included. Read them before you give the file to someone. Never in it: your folder, the models and keys they run on, their conversations.
    </p>
    {#if error}<p class="text-sm text-danger" data-testid="export-agents-error">{error}</p>{/if}
    <div class="flex items-center justify-end gap-2">
      <span class="mr-auto fact">{body.name}-agents.zip</span>
      <Button variant="ghost" onclick={() => (open = false)}>Cancel</Button>
      <Button disabled={busy || !draft} onclick={exportThem} data-testid="export-agents-go"><Download />Export {ticked.length === 1 ? "1 agent" : `${ticked.length} agents`}</Button>
    </div>
  </div>
</Dialog>
