<script lang="ts">
  // An agent's address, wherever it is (`#/agents/:id`, linked from runs, terminals, sessions):
  // it opens its place with it chosen, its project's page, Chat or Agents outside projects.
  import PageHeader from "../components/PageHeader.svelte";
  import { isChat } from "../lib/agents";
  import { api } from "../lib/api";
  import { navigate } from "../lib/router.svelte";

  let { id }: { id: string } = $props();

  let error = $state<string | null>(null);

  $effect(() => {
    api.agent(id).then(
      (a) => {
        if (a.projectId) navigate({ view: "project", id: a.projectId, agent: a.id }, true);
        else navigate(isChat(a) ? { view: "chat", agent: a.id } : { view: "agents", agent: a.id }, true);
      },
      (e: Error) => (error = e.message),
    );
  });
</script>

<PageHeader width="max-w-4xl" title="Agent" />
<div class="mx-auto w-full max-w-4xl px-8 py-10">
  {#if error}<p class="text-sm text-danger">{error}</p>{:else}<p class="text-sm text-muted-foreground">Loading…</p>{/if}
</div>
