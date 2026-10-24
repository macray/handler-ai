<script lang="ts">
  // Chat, Handler's own app (no code of its own): talk about anything, with no folder of yours.
  // Who you talk to are your agents of no project and no app, with no folder, used as a chat
  // (their `chat`, D.1): each conversation gets an empty folder. The one chosen has its
  // workspace below (the box, its conversations); someone new is a short form (a name, how it
  // behaves, its model), the rest of its settings on its Edit page. Ask's "Start a chat about it"
  // opens here with what was said typed in the box (`say`).
  import MessagesSquare from "@lucide/svelte/icons/messages-square";
  import Plus from "@lucide/svelte/icons/plus";
  import { untrack } from "svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import { Textarea } from "$lib/components/ui/textarea";
  import AgentWorkspace from "../components/AgentWorkspace.svelte";
  import Dialog from "../components/Dialog.svelte";
  import ModelAccessPicker from "../components/ModelAccessPicker.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import PageTitle from "../components/PageTitle.svelte";
  import { accessLabel, chosen } from "../lib/access";
  import { isChat } from "../lib/agents";
  import { api } from "../lib/api";
  import type { Agent, AutomationView, Session } from "../lib/contracts.gen";
  import { agentBody, agentLabel, emptyAgent, withModelAlone, type AgentSpec } from "../lib/projects.svelte";
  import { href, navigate } from "../lib/router.svelte";
  import { sessions } from "../lib/sessions.svelte";

  let { agent: chosenId, say, new: adding = false }: { agent?: string; say?: string; new?: boolean } = $props();

  let agents = $state<Agent[]>([]);
  let list = $state<Session[]>([]);
  let automations = $state<AutomationView[]>([]);
  let loaded = $state(false);
  let error = $state<string | null>(null);

  $effect(() => {
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

<PageHeader title="Chat" parent={{ label: "Apps", href: href({ view: "apps" }) }} titled />
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-5xl space-y-6 px-8 py-8">
    <div class="flex items-center gap-4">
      <span class="flex size-12 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary"><MessagesSquare class="size-6" /></span>
      <PageTitle title="Chat" description="Talk about anything. No folder of yours: each conversation starts with an empty one." />
    </div>
    {#if error}<p class="text-sm text-danger" data-testid="chat-error">{error}</p>{/if}

    {#if loaded && !agents.length}
      <div class="space-y-3 rounded-lg border border-dashed px-6 py-8 text-center text-sm text-muted-foreground" data-testid="chat-empty">
        <p>No one to talk to yet. Give them a name, say how they behave (or nothing: a plain assistant), and the model they run on.</p>
        <Button size="sm" onclick={newOne} data-testid="chat-new"><Plus />Someone new to talk to</Button>
      </div>
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
  </div>
</div>

<Dialog bind:open title="Someone new to talk to" description="In Chat, next to the others. No folder, no code: a name, how they behave, and a model. The rest of their settings are on their Edit page." wide testid="chat-new-dialog">
  <form class="space-y-5" onsubmit={(e) => (e.preventDefault(), void add())}>
    <div class="space-y-1.5">
      <Label for="chat-name">Name</Label>
      <Input id="chat-name" bind:value={spec.name} placeholder="Writing partner" required data-testid="chat-name" />
    </div>
    <div class="space-y-1.5">
      <Label for="chat-instructions">How they behave <span class="font-normal text-muted-foreground">optional</span></Label>
      <Textarea id="chat-instructions" bind:value={spec.instructions} rows={4} placeholder="Ask before rewriting anything, and keep my voice." data-testid="chat-instructions" />
    </div>
    <div class="space-y-2">
      <Label>Who answers</Label>
      <div class="flex flex-wrap gap-2" role="radiogroup" aria-label="who answers">
        {#each [{ alone: false, label: "An agent program", hint: "may run tools in its sandbox" }, { alone: true, label: "The model alone", hint: "text only, in seconds" }] as p (p.label)}
          <button
            type="button"
            role="radio"
            aria-checked={spec.modelAlone === p.alone}
            class="cursor-pointer rounded-lg border px-3 py-1.5 text-left text-sm {spec.modelAlone === p.alone ? 'border-primary ring-1 ring-primary' : 'hover:border-foreground/30'}"
            onclick={() => (spec = withModelAlone(spec, p.alone))}
            data-testid={p.alone ? "chat-model-alone" : "chat-program"}>{p.label} <span class="text-xs text-muted-foreground">· {p.hint}</span></button
          >
        {/each}
      </div>
      {#key spec.modelAlone}<ModelAccessPicker bind:value={spec.model} alone={spec.modelAlone} />{/key}
    </div>
    {#if formError}<p class="text-sm text-danger" data-testid="chat-new-error">{formError}</p>{/if}
    <div class="flex justify-end gap-2 border-t pt-4">
      <Button type="button" variant="ghost" size="sm" onclick={() => (open = false)}>Cancel</Button>
      <Button type="submit" size="sm" disabled={saving || !spec.name.trim() || !chosen(spec.model, spec.modelAlone)} data-testid="chat-add">Add</Button>
    </div>
  </form>
</Dialog>
