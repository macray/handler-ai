<script lang="ts">
  // One automation in a list (I): what it is (its description, else its name) and when it runs,
  // what it runs ("Reviewer", "Planner's route", "your script"), where (its project, its app, or
  // every project for a script read when a session stops), its last result, what is to fix, then
  // its switch: off at once, on from its page (where turning it on is your approval, I.7). The
  // Library's Automations shelf and a project's Automations tab list it the same way.
  import AppWindow from "@lucide/svelte/icons/app-window";
  import Bot from "@lucide/svelte/icons/bot";
  import Check from "@lucide/svelte/icons/check";
  import Repeat from "@lucide/svelte/icons/repeat";
  import SquareTerminal from "@lucide/svelte/icons/square-terminal";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import X from "@lucide/svelte/icons/x";
  import { api } from "../lib/api";
  import { RUN_STATE, runsKind, runsWords, whenSentence } from "../lib/automations";
  import type { AutomationView } from "../lib/contracts.gen";
  import { href, navigate } from "../lib/router.svelte";
  import Switch from "./Switch.svelte";
  import When from "./When.svelte";

  let {
    automation: a,
    agentName,
    where,
    onchanged,
    testid = "automation-card",
  }: { automation: AutomationView; agentName?: string; where?: string; onchanged: () => void; testid?: string } = $props();

  let busy = $state(false);
  let error = $state<string | null>(null);
  const ICON = { agent: Bot, app: AppWindow, script: SquareTerminal };
  const kind = $derived(runsKind(a.definition));
  const RunIcon = $derived(kind ? ICON[kind] : Repeat);
  const run = $derived(a.lastRun);

  async function turnOff(): Promise<void> {
    busy = true;
    error = null;
    try {
      await api.disableAutomation(a.name);
      onchanged();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

<li class="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3" data-testid={testid}>
  <Repeat class="size-4 shrink-0 text-muted-foreground" />
  <a class="min-w-0 flex-1 basis-56 text-foreground no-underline" href={href({ view: "automation", name: a.name })} data-testid="automation-open">
    <span class="block font-medium hover:underline">{a.description || a.name}</span>
    <span class="block text-xs text-muted-foreground">{whenSentence(a.definition)}</span>
  </a>
  <span class="inline-flex w-36 items-center gap-1.5 truncate text-xs text-muted-foreground" data-testid="automation-runs"><RunIcon class="size-3.5 shrink-0" />{runsWords(a.definition, agentName)}</span>
  <span class="hidden w-28 truncate text-xs text-muted-foreground md:block" title={where}>{where ?? ""}</span>
  <span class="inline-flex w-32 items-center justify-end gap-1 text-xs" data-testid="automation-last">
    {#if a.problems?.length}
      <span class="inline-flex items-center gap-1 text-warn" title={a.problems.join("\n")}><TriangleAlert class="size-3" />{a.problems.length} to fix</span>
    {:else if a.warnings?.length}
      <span class="inline-flex items-center gap-1 text-warn" title={a.warnings.join("\n")}><TriangleAlert class="size-3" />API key recommended</span>
    {:else if run?.state === "failed"}
      <span class="inline-flex items-center gap-1 text-danger"><X class="size-3" />failed <When at={run.createdAt} /></span>
    {:else if run?.state === "succeeded"}
      <span class="inline-flex items-center gap-1 text-ok"><Check class="size-3" /><When at={run.createdAt} /></span>
    {:else if run}
      <span class="text-muted-foreground">{RUN_STATE[run.state]} <When at={run.createdAt} /></span>
    {:else}
      <span class="text-muted-foreground">not run yet</span>
    {/if}
  </span>
  <span title={a.enabled ? "Turn it off" : "Turn it on, on its page: what it does first"}>
    <Switch checked={!!a.enabled} disabled={busy} label="{a.name} on" onchange={(on) => (on ? navigate({ view: "automation", name: a.name }) : turnOff())} testid="automation-switch" />
  </span>
  {#if error}<p class="w-full text-xs text-danger">{error}</p>{/if}
</li>
