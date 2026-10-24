<script lang="ts">
  // Automations (contract I): each is a folder of ~/.config/handler-ai/automations; here they are listed,
  // made (from the form: an agent or an app's route; a script from an example), and opened (what
  // it does, files, runs, on and off). Listed as rows, each opening its page; a script from an
  // example is made in a dialog.
  import AppWindow from "@lucide/svelte/icons/app-window";
  import Bot from "@lucide/svelte/icons/bot";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import FileCode from "@lucide/svelte/icons/file-code";
  import Plus from "@lucide/svelte/icons/plus";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import Workflow from "@lucide/svelte/icons/workflow";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import * as NativeSelect from "$lib/components/ui/native-select";
  import { Label } from "$lib/components/ui/label";
  import Dialog from "../components/Dialog.svelte";
  import LoadingCards from "../components/LoadingCards.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import PageTitle from "../components/PageTitle.svelte";
  import StatusBadge from "../components/StatusBadge.svelte";
  import When from "../components/When.svelte";
  import { api } from "../lib/api";
  import { RUN_STATE, runSentence, usage, whenSentence } from "../lib/automations";
  import type { AutomationExample, AutomationView } from "../lib/contracts.gen";
  import { navigate, href } from "../lib/router.svelte";

  let automations = $state<AutomationView[] | null>(null);
  let examples = $state<AutomationExample[]>([]);
  let error = $state<string | null>(null);
  let name = $state("");
  let example = $state("");
  let fromExample = $state(false); // the dialog open
  const chosen = $derived(examples.find((ex) => ex.name === example));

  /** What it does, in one sentence: "Every 1h, runs a script that may call mistral/…". */
  function sentence(a: AutomationView): string {
    const llm = a.definition?.services?.llm ?? [];
    return `${whenSentence(a.definition)}, ${runSentence(a.definition)}${llm.length ? ` that may call ${llm.join(", ")}` : ""}.`;
  }

  /** What it runs, as its icon: a script, an agent, an app's route. */
  function icon(a: AutomationView): typeof Bot {
    const run = a.definition?.run;
    if (run === undefined) return Workflow;
    if (typeof run === "string") return FileCode;
    return "agent" in run ? Bot : AppWindow;
  }

  async function load(): Promise<void> {
    try {
      [automations, examples] = await Promise.all([api.automations(), api.automationExamples()]);
      example ||= examples[0]?.name ?? "";
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

  async function create(): Promise<void> {
    error = null;
    try {
      const made = await api.createAutomation(name.trim(), { from: example });
      navigate({ view: "automation", name: made.name });
    } catch (e) {
      error = (e as Error).message;
    }
  }
</script>

<PageHeader titled title="Automations">
  {#snippet actions()}
    <Button variant="outline" size="sm" onclick={() => ((fromExample = true), (error = null))} data-testid="automation-from-example">A script, from an example</Button>
    <Button size="sm" href={href({ view: "edit-automation" })} data-testid="new-automation"><Plus />New automation</Button>
  {/snippet}
</PageHeader>
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-4xl space-y-8 px-8 py-10">
    <PageTitle
      title="Automations"
      description="When a session stops or at a time you set, Handler runs one of your agents (its result comes to your inbox), a route of one of your apps, or a script of yours in a sandbox."
    />
    {#if error && !fromExample}<p class="text-sm text-danger" data-testid="automations-error">{error}</p>{/if}

    {#if !automations}
      <div class="space-y-3"><LoadingCards count={2} height="h-20" /></div>
    {:else if automations.length}
      <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
        {#each automations as a (a.name)}
          {@const run = a.lastRun}
          {@const Icon = icon(a)}
          <li class="enter">
            <a
              href={href({ view: "automation", name: a.name })}
              class="group flex items-center gap-4 px-4 py-3.5 text-foreground no-underline transition-colors hover:bg-muted/40"
              data-testid="automation-card"
            >
              <span class="hidden size-9 shrink-0 items-center justify-center rounded-lg sm:flex {a.enabled ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground'}"
                ><Icon class="size-4" /></span
              >
              <div class="min-w-0 flex-1 space-y-0.5">
                <p class="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span class="font-medium">{a.name}</span>
                  <StatusBadge status={a.enabled ? "on" : "off"} />
                  {#if a.problems?.length}
                    <span class="inline-flex items-center gap-1 rounded-md bg-warn/10 px-1.5 py-0.5 text-xs text-warn" title={a.problems.join("\n")}
                      ><TriangleAlert class="size-3" />{a.problems.length} problem{a.problems.length === 1 ? "" : "s"} to fix</span
                    >
                  {/if}
                  {#if a.capped}<span class="rounded-md bg-warn/10 px-1.5 py-0.5 text-xs text-warn">daily cap reached</span>{/if}
                </p>
                {#if a.description}<p class="text-muted-foreground">{a.description}</p>{/if}
                <p class="text-muted-foreground">{sentence(a)}</p>
                <p class="fact">
                  {#if a.nextAt}next <When at={a.nextAt} /> ·{/if}
                  {#if run}
                    last <When at={run.createdAt} />:
                    <span class={run.state === "failed" ? "text-danger" : ""}>{RUN_STATE[run.state]}</span>{#if run.trial}&nbsp;(a try){/if}{#if usage(run)}&nbsp;· {usage(run)}{/if}
                  {:else}
                    not run yet
                  {/if}
                  {#if a.pending}· {a.pending} waiting{#if a.behind}&nbsp;behind {a.behind}{/if}{/if}
                </p>
              </div>
              <ChevronRight class="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
            </a>
          </li>
        {/each}
      </ul>
    {:else}
      <div class="flex flex-col items-center gap-3 rounded-[10px] border border-dashed px-6 py-12 text-center">
        <span class="flex size-10 items-center justify-center rounded-lg bg-muted text-muted-foreground"><Workflow class="size-5" /></span>
        <p class="font-medium">No automation yet</p>
        <p class="max-w-md text-sm text-muted-foreground">
          Run one of your agents every morning, call one of your apps at a time, or a script of your own when a session stops.
        </p>
        <Button size="sm" href={href({ view: "edit-automation" })}><Plus />New automation</Button>
      </div>
    {/if}
  </div>
</div>

<Dialog
  bind:open={fromExample}
  title="A script, from an example"
  description="A script of your own runs in a sandbox without network, may ask one of your models and adds to a note. The example is copied to your automations folder, off, for you to edit in your editor."
  testid="automation-example-dialog"
>
  <form class="space-y-5" onsubmit={(e) => (e.preventDefault(), void create())}>
    <div class="space-y-1.5">
      <Label for="automation-example">Example</Label>
      <NativeSelect.Root id="automation-example" class="w-full" bind:value={example} data-testid="automation-example">
        {#each examples as ex (ex.name)}<NativeSelect.Option value={ex.name}>{ex.name}</NativeSelect.Option>{/each}
      </NativeSelect.Root>
      {#if chosen?.description}<p class="text-xs text-muted-foreground">{chosen.description}</p>{/if}
    </div>
    <div class="space-y-1.5">
      <Label for="automation-name">Its name</Label>
      <Input id="automation-name" class="font-mono text-sm" placeholder="my-env-issues" bind:value={name} data-testid="automation-name" />
      <p class="text-xs text-muted-foreground">
        Lowercase letters, digits and dashes. Its files go to <span class="font-mono">~/.config/handler-ai/automations/{name.trim() || "<name>"}/</span>
      </p>
    </div>
    {#if error}<p class="text-danger" data-testid="automations-error">{error}</p>{/if}
    <div class="flex justify-end gap-2 border-t pt-4">
      <Button type="button" variant="ghost" size="sm" onclick={() => (fromExample = false)}>Cancel</Button>
      <Button type="submit" size="sm" disabled={!/^[a-z0-9][a-z0-9-]{0,63}$/.test(name.trim()) || !example} data-testid="automation-create">Create</Button>
    </div>
  </form>
</Dialog>
