<script lang="ts">
  // What a thing uses and what uses it (D.22), two lists of sentences side by side, each thing a
  // link to its page: "agent weekly-report · dev, picks it". Nothing shown while both are empty.
  import { api } from "../lib/api";
  import type { UseRef, Uses } from "../lib/contracts.gen";
  import { href, type Route } from "../lib/router.svelte";

  type UseKind = UseRef["kind"];
  let { kind, id }: { kind: UseKind; id: string } = $props();

  let data = $state<Uses | null>(null);
  $effect(() => {
    void [kind, id];
    api.uses(kind, id).then(
      (u) => (data = u),
      () => (data = null),
    );
  });

  const WORD: Record<UseKind, string> = {
    agent: "agent",
    skill: "skill",
    knowledge: "knowledge",
    addon: "addon",
    account: "account",
    provider: "provider",
    automation: "automation",
    app: "app",
    project: "project",
    handler: "",
  };

  function route(r: UseRef): Route | null {
    switch (r.kind) {
      case "agent":
        return { view: "agent", id: r.id };
      case "skill":
        return { view: "skill", name: r.id };
      case "knowledge":
        return r.id === "." ? { view: "knowledge" } : { view: "knowledge", path: r.id };
      case "addon":
        return { view: "addons" };
      case "account":
      case "provider":
        return { view: "settings", section: "models" };
      case "automation":
        return { view: "automation", name: r.id };
      case "app":
        return { view: "apps" };
      case "project":
        return { view: "project", id: r.id };
      case "handler":
        return null;
    }
  }
</script>

{#snippet list(title: string, refs: UseRef[], testid: string)}
  <div class="rounded-[10px] border px-3.5 py-2.5 text-sm" data-testid={testid}>
    <h3 class="section-label mb-1">{title}</h3>
    {#if refs.length}
      <ul class="space-y-0.5">
        {#each refs as r (`${r.kind}:${r.id}`)}
          {@const to = route(r)}
          <li class="text-muted-foreground">
            {WORD[r.kind]}
            {#if to}<a class="text-link hover:underline" href={href(to)}>{r.label}</a>{:else}<span class="text-foreground">{r.label}</span>{/if}, {r.how}
          </li>
        {/each}
      </ul>
    {:else}
      <p class="text-xs text-muted-foreground">nothing</p>
    {/if}
  </div>
{/snippet}

{#if data && (data.uses?.length || data.usedBy?.length)}
  <div class="grid gap-3 sm:grid-cols-2" data-testid="uses-panel">
    {@render list("it uses", data.uses ?? [], "uses-list")}
    {@render list("used by", data.usedBy ?? [], "used-by-list")}
  </div>
{/if}
