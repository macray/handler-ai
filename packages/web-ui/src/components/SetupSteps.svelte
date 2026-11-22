<script lang="ts">
  // The three steps of setting Handler up (E1, lib/firstrun): connect a model, say where your code
  // is, your first project. Large, side by side, on the empty Projects page; small, one row each,
  // in the menu's Set up Handler card's panel. The next one is marked and has the only primary
  // button; a done one says what is ready. Steps 1 and 2 are done in a dialog over the page you
  // are on (a Connect, lib/connect; Add a folder, lib/workfolders); step 3 is New project, after
  // step 1. `onaction` is told before a step's action (the card's panel closes).
  import Check from "@lucide/svelte/icons/check";
  import Plus from "@lucide/svelte/icons/plus";
  import { Button } from "$lib/components/ui/button";
  import DisabledReason from "./DisabledReason.svelte";
  import { connect } from "../lib/connect.svelte";
  import { firstRun, STEP_NAMES, type StepId } from "../lib/firstrun.svelte";
  import { href } from "../lib/router.svelte";
  import { addFolder } from "../lib/workfolders.svelte";
  import { shortFolder } from "../lib/projects.svelte";

  let { large = false, onaction }: { large?: boolean; onaction?: () => void } = $props();

  const facts = $derived(firstRun.facts);
  const setup = $derived(firstRun.setup);

  const TEXT: Record<StepId, string> = $derived({
    model: "A subscription you have, an API key, or a local model.",
    folders: "Agents only work inside these folders.",
    project: large ? "Pick a folder; on its page, add an agent and type your first request." : "A folder of yours and an agent, ready for a request.",
  });

  function act(then: () => void): void {
    onaction?.();
    then();
  }
</script>

{#snippet mark(id: StepId, n: number, done: boolean)}
  <span
    class="grid shrink-0 place-items-center rounded-full font-mono text-xs {large ? 'size-6.5' : 'size-5.5'} {done
      ? 'bg-ok/15 text-ok'
      : setup?.next === id
        ? 'bg-primary text-primary-foreground'
        : 'text-muted-foreground ring-[1.5px] ring-border ring-inset'}">{#if done}<Check class="size-3.5" />{:else}{n}{/if}</span
  >
{/snippet}

{#snippet notAnswering()}
  {#if facts?.unreached.length}
    <p class="text-xs text-warn" data-testid="model-not-reached"><span class="font-mono">{facts.unreached.join(", ")}</span> not reached: start its server, then Test it in Settings → Model access.</p>
  {/if}
{/snippet}

<!-- what each step shows under its words: done, what is ready; else its action -->
{#snippet modelState()}
  {#if setup?.model}
    <p class="flex items-center gap-1.5 text-xs text-ok"><Check class="size-3.5" /><span class="font-mono">{facts?.ready.join(", ")}</span> ready</p>
    {@render notAnswering()}
  {:else}
    {@render notAnswering()}
    {#if facts && facts.unready > facts.unreached.length}<p class="text-xs text-muted-foreground">Not ready yet: log in to your account, or set your provider's key.</p>{/if}
    {#if facts?.unready}
      <Button class="self-start" size="sm" href={href({ view: "settings", section: "models" })} onclick={() => onaction?.()} data-testid="setup-finish">Finish connecting</Button>
    {:else}
      <Button class="self-start" size="sm" onclick={() => act(() => connect.open("both"))} data-testid="setup-connect">Connect…</Button>
    {/if}
  {/if}
{/snippet}

{#snippet foldersState()}
  {#if setup?.folders}
    <p class="flex min-w-0 items-center gap-1.5 text-xs text-ok"><Check class="size-3.5 shrink-0" /><span class="truncate font-mono" title={facts?.existing.join(", ")}>{facts?.existing.map(shortFolder).join(", ")}</span></p>
  {:else}
    {#if facts?.roots.length}<p class="text-xs text-muted-foreground"><span class="font-mono" title={facts.roots.join(", ")}>{facts.roots.map(shortFolder).join(", ")}</span> {facts.roots.length === 1 ? "doesn't" : "don't"} exist yet.</p>{/if}
    <Button class="self-start" size="sm" variant={setup?.next === "folders" ? "default" : "outline"} onclick={() => act(() => addFolder.show())} data-testid="setup-folder">Choose a folder…</Button>
  {/if}
{/snippet}

{#snippet projectState()}
  {#if setup?.model}
    <Button class="self-start" size="sm" variant={setup.next === "project" ? "default" : "outline"} href={href({ view: "edit-project" })} onclick={() => onaction?.()} data-testid="setup-project"><Plus />New project</Button>
  {:else if large}
    <DisabledReason blocked={{ reason: "After step 1" }} testid="setup-project-later" />
  {:else}
    <p class="text-xs text-muted-foreground" data-testid="setup-project-later">After step 1</p>
  {/if}
{/snippet}

{#if setup}
  {#if large}
    <ol class="grid gap-3.5 sm:grid-cols-3" data-testid="setup-steps">
      {#each [["model", modelState], ["folders", foldersState], ["project", projectState]] as const as [id, body], i (id)}
        {@const done = id === "model" ? setup.model : id === "folders" ? setup.folders : false}
        <li
          class="flex min-h-48 flex-col gap-2 rounded-xl bg-card p-4.5 {setup.next === id ? 'shadow-panel ring-2 ring-primary' : 'shadow-panel'} {id === 'project' && !setup.model ? 'opacity-60' : ''}"
          data-testid="step-{id}"
          data-done={done}
        >
          {@render mark(id, i + 1, done)}
          <h2 class="mt-1 text-[0.9375rem] font-semibold">{STEP_NAMES[id]}</h2>
          <p class="text-sm text-muted-foreground">{TEXT[id]}</p>
          <div class="mt-auto flex flex-col gap-2 pt-2">{@render body()}</div>
        </li>
      {/each}
    </ol>
  {:else}
    <ol class="space-y-0.5" data-testid="setup-steps">
      {#each [["model", modelState], ["folders", foldersState], ["project", projectState]] as const as [id, body], i (id)}
        {@const done = id === "model" ? setup.model : id === "folders" ? setup.folders : false}
        <li class="flex items-start gap-2.5 rounded-[9px] px-2 py-2 {setup.next === id ? 'bg-primary/8' : ''}" data-testid="step-{id}" data-done={done}>
          <span class="mt-px">{@render mark(id, i + 1, done)}</span>
          <div class="flex min-w-0 flex-1 flex-col gap-1.5">
            <p class="text-[0.8125rem] font-semibold {done ? 'text-muted-foreground' : ''}">{STEP_NAMES[id]}</p>
            {#if !done}<p class="text-xs text-muted-foreground">{TEXT[id]}</p>{/if}
            {@render body()}
          </div>
          {#if id === "folders" && done}
            <a class="mt-0.5 shrink-0 text-xs text-link hover:underline" href={href({ view: "settings", section: "folders" })} onclick={() => onaction?.()} data-testid="setup-folders-change">Change</a>
          {/if}
        </li>
      {/each}
    </ol>
  {/if}
{/if}
