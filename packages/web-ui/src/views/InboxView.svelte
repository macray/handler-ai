<script lang="ts">
  // The person's inbox: what handler told you, newest first. Apps' notifications (H.9) and automations'
  // results and failures (I.3); an agent's result opens as its run, shown from its schema.
  import { Button } from "$lib/components/ui/button";
  import PageHeader from "../components/PageHeader.svelte";
  import PageTitle from "../components/PageTitle.svelte";
  import StatusBadge from "../components/StatusBadge.svelte";
  import When from "../components/When.svelte";
  import { api } from "../lib/api";
  import type { InboxMessage } from "../lib/contracts.gen";
  import { href } from "../lib/router.svelte";

  let messages = $state<InboxMessage[] | null>(null);
  let error = $state<string | null>(null);

  async function load(): Promise<void> {
    try {
      messages = await api.inbox();
      error = null;
    } catch (e) {
      error = (e as Error).message;
    }
  }

  $effect(() => {
    void load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  });

  async function markRead(m: InboxMessage): Promise<void> {
    try {
      await api.markRead(m.id);
      await load();
    } catch (e) {
      error = (e as Error).message;
    }
  }

  /** Where a message leads: an agent's run, the automation, the apps. */
  function link(m: InboxMessage): { label: string; url: string } {
    if (m.sessionId) return { label: "Open its result", url: href({ view: "run", id: m.sessionId }) };
    if (m.source === "automation") return { label: "Open the automation", url: href({ view: "automation", name: m.name }) };
    return { label: "Open apps", url: href({ view: "apps" }) };
  }
</script>

<PageHeader titled title="Inbox" />
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-4xl space-y-6 px-8 py-10">
    <PageTitle title="Inbox" description="What Handler told you: your apps' notifications, your automations' results and failures. Your agents cannot write here." />
    {#if error}<p class="text-sm text-danger" data-testid="inbox-error">{error}</p>{/if}
    <ul class="divide-y rounded-lg border bg-card text-sm" data-testid="inbox">
      {#each messages ?? [] as m (m.id)}
        {@const to = link(m)}
        <li class="space-y-1 px-4 py-3" data-testid="inbox-message">
          <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
            {#if m.status}<StatusBadge status={m.status} />{/if}
            <span class={m.read ? "" : "font-semibold"}>{m.title}</span>
            <span class="text-xs text-muted-foreground">
              {m.source === "app" ? `app ${m.name}` : `automation${m.agent ? `, agent ${m.agent}` : ""}`}{#if m.person !== "owner"} · for {m.person}{/if}
            </span>
            <span class="ml-auto text-xs text-muted-foreground"><When at={m.at} /></span>
          </div>
          {#if m.summary}<p class="whitespace-pre-wrap">{m.summary}</p>{/if}
          <div class="flex items-center gap-2">
            <a class="text-xs text-link hover:underline" href={to.url}>{to.label}</a>
            {#if !m.read}
              <Button size="sm" variant="ghost" onclick={() => markRead(m)} data-testid="inbox-read">Mark read</Button>
            {/if}
          </div>
        </li>
      {:else}
        {#if messages}<li class="px-4 py-6 text-center text-muted-foreground">Nothing yet.</li>{/if}
      {/each}
    </ul>
  </div>
</div>
