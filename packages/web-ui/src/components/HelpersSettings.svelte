<script lang="ts">
  // Settings → Helpers: the agents behind Handler's own features (D.18, its needs), one row each
  // by the feature it serves (its icon and name, the helper's name and where you meet it), who
  // works (two chips, or the model alone's one), what it can do in short, and Ready; one not set
  // up yet is set up the first time its feature is used (its card there). A row opens the
  // helper's page.
  import { api } from "../lib/api";
  import type { Agent, HandlerNeed } from "../lib/contracts.gen";
  import { factsOf, FEATURES, settingsOf } from "../lib/helpers";
  import { href } from "../lib/router.svelte";
  import HelperIcon from "./HelperIcon.svelte";
  import WhoWorks from "./WhoWorks.svelte";

  let needs = $state<HandlerNeed[] | null>(null);
  let agents = $state<Agent[]>([]);
  let error = $state<string | null>(null);

  $effect(() => {
    Promise.all([api.handlerNeeds(), api.agents()]).then(
      ([n, a]) => ((needs = n), (agents = a)),
      (e: Error) => (error = e.message),
    );
  });

  const rows = $derived(
    FEATURES.flatMap((f) => {
      const need = (needs ?? []).find((n) => n.name === f.need);
      if (!need) return [];
      const agent = need.agentId ? agents.find((a) => a.id === need.agentId) : undefined;
      return [{ f, need, agent }];
    }),
  );
</script>

<section class="space-y-3" data-testid="helpers">
  {#if error}<p class="text-sm text-danger">{error}</p>{/if}
  <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
    {#each rows as { f, need, agent } (f.need)}
      {@const facts = agent ? factsOf(f.need, settingsOf(agent)) : []}
      <li data-testid="helper" data-need={f.need}>
        <a class="grid items-center gap-4 px-4 py-3.5 text-inherit no-underline hover:bg-muted/40 md:grid-cols-[minmax(13rem,1.2fr)_minmax(12rem,1fr)_minmax(8rem,1fr)_6rem]" href={href({ view: "settings", section: "helpers", helper: f.need })}>
          <span class="flex min-w-0 items-center gap-3">
            <HelperIcon icon={f.icon} />
            <span class="min-w-0">
              <span class="block font-medium">{f.feature}</span>
              <span class="block truncate text-xs text-muted-foreground">{need.definition.agentName.toLowerCase()} · {f.where}</span>
            </span>
          </span>
          {#if agent}
            <WhoWorks {agent} />
            <span class="flex flex-wrap gap-1">
              {#each facts.slice(0, 2) as fact (fact.key)}<span class="rounded-md bg-muted px-1.5 py-0.5 text-xs text-foreground/75">{fact.chip ?? fact.text}</span>{/each}
            </span>
            {#if agent.model.problem}
              <span class="text-xs text-warn" title={agent.model.problem}>Cannot start</span>
            {:else}
              <span class="flex items-center gap-1.5 text-xs text-ok" data-testid="helper-ready"><span class="size-1.5 rounded-full bg-ok"></span>Ready</span>
            {/if}
          {:else}
            <span class="text-xs text-muted-foreground md:col-span-2">set up the first time you use it</span>
            <span class="text-xs text-muted-foreground" data-testid="helper-not-set-up">Not set up</span>
          {/if}
        </a>
      </li>
    {/each}
  </ul>
</section>
