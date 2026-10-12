<script lang="ts">
  // Automations (contract I): each is a folder of ~/.config/handler-ai/automations; here they are listed,
  // made (from the form: an agent or an app's route; a script from an example), and opened (what
  // it does, files, runs, on and off).
  import Plus from "@lucide/svelte/icons/plus";
  import { Button } from "$lib/components/ui/button";
  import * as Card from "$lib/components/ui/card";
  import { Input } from "$lib/components/ui/input";
  import * as NativeSelect from "$lib/components/ui/native-select";
  import PageHeader from "../components/PageHeader.svelte";
  import PageTitle from "../components/PageTitle.svelte";
  import StatusBadge from "../components/StatusBadge.svelte";
  import When from "../components/When.svelte";
  import { api } from "../lib/api";
  import { runSentence, usage, whenSentence } from "../lib/automations";
  import type { AutomationExample, AutomationView } from "../lib/contracts.gen";
  import { navigate, href } from "../lib/router.svelte";

  let automations = $state<AutomationView[] | null>(null);
  let examples = $state<AutomationExample[]>([]);
  let error = $state<string | null>(null);
  let name = $state("");
  let example = $state("");

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
    <Button size="sm" href={href({ view: "edit-automation" })} data-testid="new-automation"><Plus />New automation</Button>
  {/snippet}
</PageHeader>
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-4xl space-y-8 px-8 py-10">
    <PageTitle
      title="Automations"
      description="When a session stops or at a time you set, Handler runs your script in a sandbox, one of your agents (its result comes to your inbox) or a route of one of your apps."
    />
    {#if error}<p class="text-sm text-danger" data-testid="automations-error">{error}</p>{/if}

    <section class="space-y-3">
      {#each automations ?? [] as a (a.name)}
        {@const run = a.lastRun}
        <a href={href({ view: "automation", name: a.name })} class="block no-underline" data-testid="automation-card">
          <Card.Root class="transition-colors hover:border-foreground/20">
            <Card.Header>
              <Card.Title class="flex items-center gap-3">
                <span>{a.name}</span>
                <StatusBadge status={a.enabled ? "on" : "off"} />
                {#if a.problems?.length}<span class="text-sm font-normal text-danger">{a.problems.length} problem{a.problems.length === 1 ? "" : "s"}</span>{/if}
              </Card.Title>
              <Card.Description>{a.description ?? ""}</Card.Description>
            </Card.Header>
            <Card.Content class="space-y-1 text-sm text-muted-foreground">
              <p>
                {whenSentence(a.definition)}, {runSentence(a.definition)}{#if a.definition?.services?.llm?.length} that may call {a.definition.services.llm.join(", ")}{/if}.
                {#if a.nextAt}Next run <When at={a.nextAt} />.{/if}
              </p>
              <p>
                {#if run}
                  Last run <When at={run.createdAt} />: <span class={run.state === "failed" ? "text-danger" : ""}>{run.state}</span>{#if run.trial} (a try){/if}
                  {#if usage(run)}· {usage(run)}{/if}
                {:else}
                  Not run yet.
                {/if}
                {#if a.pending}· {a.pending} waiting{#if a.behind} behind {a.behind}{/if}{/if}
                {#if a.capped}<span class="text-warn"> · daily cap reached</span>{/if}
              </p>
            </Card.Content>
          </Card.Root>
        </a>
      {:else}
        {#if automations}
          <div class="space-y-3 rounded-lg border bg-card px-4 py-6 text-center text-sm text-muted-foreground">
            <p>No automation yet. Run one of your agents every morning, call one of your apps at a time, or a script of your own when a session stops.</p>
            <Button size="sm" href={href({ view: "edit-automation" })}><Plus />New automation</Button>
          </div>
        {/if}
      {/each}
    </section>

    <Card.Root>
      <Card.Header>
        <Card.Title>A script, from an example</Card.Title>
        <Card.Description>
          A script of your own runs in a sandbox without network, may ask one of your models and adds to a note. The example is copied to
          <code>~/.config/handler-ai/automations/&lt;name&gt;/</code>, off, for you to edit in your editor.
        </Card.Description>
      </Card.Header>
      <Card.Content>
        <form class="flex flex-wrap items-center gap-2" onsubmit={(e) => (e.preventDefault(), create())}>
          <NativeSelect.Root class="w-48" bind:value={example} aria-label="example" data-testid="automation-example">
            {#each examples as ex (ex.name)}<NativeSelect.Option value={ex.name}>{ex.name}</NativeSelect.Option>{/each}
          </NativeSelect.Root>
          <Input class="h-9 w-56" placeholder="its name (my-env-issues)" bind:value={name} aria-label="name" data-testid="automation-name" />
          <Button type="submit" disabled={!/^[a-z0-9][a-z0-9-]{0,63}$/.test(name.trim()) || !example} data-testid="automation-create">Create</Button>
        </form>
        {#if examples.find((ex) => ex.name === example)?.description}
          <p class="mt-2 text-xs text-muted-foreground">{examples.find((ex) => ex.name === example)?.description}</p>
        {/if}
      </Card.Content>
    </Card.Root>
  </div>
</div>
