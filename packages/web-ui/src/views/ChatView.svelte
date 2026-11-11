<script lang="ts">
  // Chat, Handler's own app (no code of its own): talk about anything, with no folder of yours.
  // Who you talk to are your agents of no project and no app, with no folder, used as a chat
  // (their `chat`, D.1): each conversation gets an empty folder. The one chosen has its
  // workspace below (the box, its conversations); someone new is a short form (a name, how it
  // behaves, who works: the two chips of ModelChoice), the rest of its settings on its Edit page.
  // With no one yet: Assistant (never a vendor's name), added in one click on what you used last
  // or the one model ready (suggestedAccess), or someone new. That is the Talk tab; the Ask tab
  // (`ask`, AskPanel) is Ask, apart: what you say goes to the router, which runs an app's action.
  // Ask's "Start a chat about it" opens Talk with what was said typed in the box (`say`).
  import Plus from "@lucide/svelte/icons/plus";
  import { untrack } from "svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import { Textarea } from "$lib/components/ui/textarea";
  import AgentWorkspace from "../components/AgentWorkspace.svelte";
  import AskPanel from "../components/AskPanel.svelte";
  import Dialog from "../components/Dialog.svelte";
  import MessageSquare from "@lucide/svelte/icons/message-square";
  import ModelChoice from "../components/ModelChoice.svelte";
  import PageHeader, { type PageTab } from "../components/PageHeader.svelte";
  import { accessLabel, accessOf, chosen, type ModelAccess } from "../lib/access";
  import { isChat } from "../lib/agents";
  import { api } from "../lib/api";
  import type { Agent, AutomationView, Session } from "../lib/contracts.gen";
  import { productName } from "../lib/harnesses.svelte";
  import { agentBody, agentLabel, emptyAgent, projects, suggestedAccess, withModelAlone, type AgentSpec } from "../lib/projects.svelte";
  import { href, navigate } from "../lib/router.svelte";
  import { sessions } from "../lib/sessions.svelte";

  let { agent: chosenId, say, new: adding = false, ask = false }: { agent?: string; say?: string; new?: boolean; ask?: boolean } = $props();

  const tabs: PageTab[] = $derived([
    { label: "Talk", href: href({ view: "chat" }), active: !ask, testid: "chat-tab-talk" },
    { label: "Ask", href: href({ view: "ask" }), active: ask, testid: "chat-tab-ask" },
  ]);

  let agents = $state<Agent[]>([]);
  let list = $state<Session[]>([]);
  let automations = $state<AutomationView[]>([]);
  let loaded = $state(false);
  let error = $state<string | null>(null);

  $effect(() => {
    if (ask) return; // the Ask tab reads its own
    void sessions.stopping.size; // a conversation closed here has stopped: load again
    void say; // a new message to send: read who you talk to now
    const load = () =>
      Promise.all([api.agents(), api.sessions(), api.automations().catch(() => [])]).then(
        ([all, s, auto]) => {
          agents = all.filter(isChat).sort((x, y) => (y.lastUsedAt ?? y.createdAt).localeCompare(x.lastUsedAt ?? x.createdAt));
          list = s.filter((x) => agents.some((a) => a.id === x.agentId));
          automations = auto;
          loaded = true;
          // a message to send and no one to send it to: someone new first (once per message)
          if (say && !agents.length && offeredFor !== say) {
            offeredFor = say;
            newOne();
          }
        },
        (e: Error) => (error = e.message),
      );
    void load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  });

  // the one chosen, else the one you talked to last
  const agent = $derived(agents.find((a) => a.id === chosenId) ?? agents[0]);

  // with no one yet: Assistant, on what you used last or the one model ready
  let suggested = $state<ModelAccess | null>(null);
  Promise.all([api.accounts(), api.providers(), projects.refresh()]).then(
    ([accounts, providers]) => (suggested = suggestedAccess(projects.list, accounts, providers, null)),
    () => undefined,
  );
  async function addAssistant(): Promise<void> {
    if (!suggested) return;
    spec = { ...emptyAgent(suggested), name: "Assistant" };
    await add();
  }

  // someone new: a name, how it behaves, who works and on what model
  let open = $state(false);
  let spec = $state<AgentSpec>(emptyAgent());
  let saving = $state(false);
  let formError = $state<string | null>(null);
  let offeredFor: string | undefined;
  $effect(() => {
    if (adding) untrack(newOne);
  });

  function newOne(): void {
    spec = emptyAgent();
    formError = null;
    open = true;
  }

  async function add(): Promise<void> {
    saving = true;
    formError = null;
    try {
      const made = await api.createAgent(agentBody(spec, { chat: true, scope: null }));
      sessions.updateAgent(made);
      open = false;
      agents = [made, ...agents];
      navigate({ view: "chat", agent: made.id, ...(say ? { say } : {}) }, true);
    } catch (e) {
      formError = (e as Error).message;
    } finally {
      saving = false;
    }
  }
</script>

<PageHeader width="max-w-5xl" title="Chat" {tabs} />
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-5xl space-y-6 px-8 py-8">
    {#if ask}
      <AskPanel />
    {:else}
      {#if error}<p class="text-sm text-danger" data-testid="chat-error">{error}</p>{/if}

      {#if loaded && !agents.length}
        <section class="space-y-4 rounded-[14px] border border-dashed p-7" data-testid="chat-empty">
          <h2 class="text-base font-semibold">No one to talk to yet</h2>
          {#if suggested}
            <div class="flex items-center gap-3.5 rounded-[10px] border bg-card px-4 py-3 shadow-panel" data-testid="chat-suggestion">
              <span class="grid size-9 shrink-0 place-items-center rounded-lg bg-accent-soft text-primary"><MessageSquare class="size-4" /></span>
              <div class="min-w-0 flex-1">
                <p class="text-sm"><b class="font-semibold">Assistant</b> <span class="text-muted-foreground">· anything, with no folder of yours</span></p>
                <p class="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                  <span>{productName(suggested.harness ?? "")}</span>·<span class="fact">{suggested.account ?? suggested.provider}</span>{#if suggested.model}·<span>{suggested.model}</span>{/if}
                </p>
              </div>
              <Button disabled={saving} onclick={addAssistant} data-testid="chat-add-assistant">Add Assistant</Button>
            </div>
          {/if}
          <Button variant="outline" onclick={newOne} data-testid="chat-new"><Plus />Someone new</Button>
          {#if formError && !open}<p class="text-sm text-danger">{formError}</p>{/if}
        </section>
      {:else if agents.length}
        <section class="space-y-2.5">
          <h2 class="flex items-baseline gap-2 font-semibold">Who you talk to <span class="text-xs font-normal text-muted-foreground">each with their own instructions and model</span></h2>
          <ul class="grid gap-2.5 sm:grid-cols-3 lg:grid-cols-4" data-testid="chat-who">
            {#each agents as a (a.id)}
              <li>
                <a
                  class="flex h-full flex-col gap-1 rounded-xl border bg-card px-3.5 py-3 text-foreground no-underline shadow-panel transition-colors hover:border-foreground/30 {a.id === agent?.id
                    ? 'border-primary ring-1 ring-primary'
                    : ''}"
                  href={href({ view: "chat", agent: a.id })}
                  aria-current={a.id === agent?.id ? "true" : undefined}
                  data-testid="chat-pick"
                >
                  <span class="truncate font-semibold">{agentLabel(a)}</span>
                  {#if a.description}<span class="line-clamp-2 text-sm text-muted-foreground">{a.description}</span>{/if}
                  <span class="fact mt-auto truncate pt-1">{accessLabel(a.model)}</span>
                </a>
              </li>
            {/each}
            <li>
              <button
                type="button"
                class="flex h-full min-h-20 w-full cursor-pointer items-center justify-center gap-1.5 rounded-xl border border-dashed text-sm text-muted-foreground hover:bg-accent/60"
                onclick={newOne}
                data-testid="chat-new"><Plus class="size-4" />Someone new</button
              >
            </li>
          </ul>
        </section>

        {#if agent}
          {#key agent.id}
            <AgentWorkspace {agent} {list} {automations} {say} edit={href({ view: "edit-ad-hoc", id: agent.id })} />
          {/key}
        {/if}
      {:else if !error}
        <p class="text-sm text-muted-foreground">Loading…</p>
      {/if}
    {/if}
  </div>
</div>

<Dialog bind:open title="Someone new to talk to" description="In Chat, next to the others: a name, how they behave, and who works. The rest of their settings are on their Edit page." wide testid="chat-new-dialog">
  <form class="space-y-5" onsubmit={(e) => (e.preventDefault(), void add())}>
    <div class="space-y-1.5">
      <Label for="chat-name">Name</Label>
      <Input id="chat-name" bind:value={spec.name} placeholder="Writing partner" required data-testid="chat-name" />
    </div>
    <div class="space-y-1.5">
      <Label for="chat-instructions">How they behave <span class="font-normal text-muted-foreground">optional</span></Label>
      <Textarea id="chat-instructions" bind:value={spec.instructions} rows={4} placeholder="Ask before rewriting anything, and keep my voice." data-testid="chat-instructions" />
    </div>
    <div class="space-y-1.5">
      <Label>Who works</Label>
      <ModelChoice
        agent={{ id: "", name: spec.name, model: spec.model, area: null, modelAlone: spec.modelAlone }}
        own
        onchange={(m) => (spec.model = accessOf(m))}
        onalone={(alone) => (spec = withModelAlone(spec, alone))}
      />
    </div>
    {#if formError}<p class="text-sm text-danger" data-testid="chat-new-error">{formError}</p>{/if}
    <div class="flex justify-end gap-2 border-t pt-4">
      <Button type="button" variant="ghost" size="sm" onclick={() => (open = false)}>Cancel</Button>
      <Button type="submit" size="sm" disabled={saving || !spec.name.trim() || !chosen(spec.model, spec.modelAlone)} data-testid="chat-add">Add</Button>
    </div>
  </form>
</Dialog>
