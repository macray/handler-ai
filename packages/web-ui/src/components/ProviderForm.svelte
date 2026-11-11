<script lang="ts">
  // A provider's form (D.12), in its dialog: name, endpoints by protocol, key, models. Starts from a
  // template or from the provider being edited. The key goes to the secret store and is never shown: empty
  // keeps the one it has. Model fields the form does not show (temperature, native…) are kept.
  // Test asks its server for its models from where a sandbox would (D.12): what it serves fills the
  // models when none is typed; a server on this computer is ready only once it answered.
  import Plus from "@lucide/svelte/icons/plus";
  import X from "@lucide/svelte/icons/x";
  import { Button } from "$lib/components/ui/button";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import AreasPicker from "./AreasPicker.svelte";
  import { api } from "../lib/api";
  import { fillModels, onThisComputer, reachLine, type ReachState } from "../lib/providers";
  import type { ProviderInfo, ProviderModel, ProviderReach, ProviderRequest, ProviderTemplate } from "../lib/contracts.gen";

  let {
    start,
    editing = null,
    onsave,
    oncancel,
    ondelete,
    error = null,
  }: {
    start: ProviderTemplate | ProviderInfo;
    editing?: ProviderInfo | null; // the provider being edited; null: a new one
    onsave: (body: ProviderRequest) => Promise<void>;
    oncancel: () => void;
    ondelete?: () => void; // an existing provider: its Delete
    error?: string | null; // what the last save was refused for
  } = $props();

  const PROTOCOLS = [
    ["anthropic", "Anthropic (Claude Code)"],
    ["openai-chat", "OpenAI chat (pi, Vibe)"],
    ["responses", "Responses (Codex)"],
    ["transcriptions", "Speech to text (Voice)"],
  ] as const;

  // svelte-ignore state_referenced_locally — the form starts from `start` once
  let name = $state(editing?.name ?? start.name);
  // svelte-ignore state_referenced_locally
  let description = $state(start.description ?? "");
  // svelte-ignore state_referenced_locally — a template is made for no area yet
  let areas = $state<string[]>(editing?.areas ?? []);
  // svelte-ignore state_referenced_locally
  let endpoints = $state<Record<string, string>>({ ...(start.endpoints ?? {}) });
  // a model row: its checkboxes bind booleans (binding undefined to one with a default throws)
  const row = (m: ProviderModel): ProviderModel => ({ ...m, reasoning: m.reasoning ?? false, images: m.images ?? false, speech: m.speech ?? false });
  // svelte-ignore state_referenced_locally
  let models = $state<ProviderModel[]>((start.models ?? []).map(row));
  let key = $state("");
  let removeKey = $state(false);
  let saving = $state(false);

  // the last test, and the endpoints it was of: changed since, it says nothing of them
  // svelte-ignore state_referenced_locally — an edited provider shows its last test
  let reach = $state<ProviderReach | null>(editing?.reached ?? null);
  // svelte-ignore state_referenced_locally
  let tested = $state(editing?.reached ? JSON.stringify(given()) : "");
  let testing = $state(false);
  let testError = $state<string | null>(null);

  /** The endpoints typed, the empty ones left out. */
  function given(): Record<string, string> {
    return Object.fromEntries(Object.entries(endpoints).filter(([, url]) => url?.trim()).map(([p, url]) => [p, url.trim()]));
  }
  const local = $derived(Object.values(endpoints).some((url) => url && onThisComputer(url)));
  const reachState: ReachState = $derived(
    testing ? "testing" : !reach || tested !== JSON.stringify(given()) ? "untested" : reach.ok ? "ready" : "not reached",
  );
  const served = $derived(reach?.ok ? (reach.models ?? []) : []);

  async function test(): Promise<void> {
    testing = true;
    testError = null;
    const asked = given();
    try {
      reach = await api.testProvider({ endpoints: asked, key: key.trim() || null, provider: editing?.name ?? null });
      tested = JSON.stringify(asked);
      if (reach.ok) models = fillModels(models, reach.models ?? []).map(row);
    } catch (e) {
      testError = (e as Error).message;
    } finally {
      testing = false;
    }
  }

  const handWritten = $derived(editing?.key && editing.key !== "secret");
  const asksForKey = $derived(editing ? editing.key === "secret" || !editing.key : Boolean((start as ProviderTemplate).needsKey));

  async function submit(): Promise<void> {
    saving = true;
    try {
      const filled = given();
      const kept = models.filter((m) => m.id.trim());
      await onsave({
        name: name.trim(),
        description: description.trim() || null,
        endpoints: filled,
        models: kept as ProviderRequest["models"],
        key: key.trim() || null,
        removeKey,
        areas,
        // a template's config files for some harnesses (codex's system prompt): given once, kept
        files: editing ? null : ((start as ProviderTemplate).files ?? null),
      });
    } finally {
      saving = false;
    }
  }
</script>

<form class="space-y-6" onsubmit={(e) => (e.preventDefault(), void submit())} data-testid="provider-form">
  <div class="space-y-4">
    <div class="grid gap-4 sm:grid-cols-[1fr_2fr]">
      <div class="space-y-1.5">
        <Label for="provider-name">Name</Label>
        <Input id="provider-name" bind:value={name} required data-testid="provider-name" />
      </div>
      <div class="space-y-1.5">
        <Label for="provider-description">Description (optional)</Label>
        <Input id="provider-description" bind:value={description} />
      </div>
    </div>
    <AreasPicker bind:value={areas} />
  </div>

  <fieldset class="space-y-2">
    <legend class="mb-1 font-medium">Where it answers</legend>
    <p class="text-xs text-muted-foreground">Its URL for each protocol it speaks; the agent programs that speak one can use it.</p>
    <div class="grid items-center gap-x-3 gap-y-2 sm:grid-cols-[11rem_1fr]">
      {#each PROTOCOLS as [protocol, label] (protocol)}
        <label for="provider-endpoint-{protocol}" class="text-xs text-muted-foreground">{label}</label>
        <Input id="provider-endpoint-{protocol}" class="font-mono text-xs" placeholder="not spoken" bind:value={endpoints[protocol]} data-testid={`provider-endpoint-${protocol}`} />
      {/each}
    </div>
    {#if local}
      <p class="text-xs {reachState === 'not reached' ? 'text-warn' : 'text-muted-foreground'}" data-testid="provider-listen">
        A server on this computer must listen where sandboxes reach it, not only on 127.0.0.1: start llama-server with
        <code class="font-mono">--host 0.0.0.0 --jinja</code>, Ollama with <code class="font-mono">OLLAMA_HOST=0.0.0.0</code>.
      </p>
    {/if}
    <div class="flex flex-wrap items-center gap-3 pt-1">
      <Button type="button" variant="outline" size="sm" onclick={() => void test()} disabled={testing || !Object.keys(given()).length} data-testid="provider-test">
        {testing ? "Testing…" : "Test"}
      </Button>
      <p
        class="min-w-0 flex-1 text-xs whitespace-normal {reachState === 'ready' ? 'text-ok' : reachState === 'not reached' ? 'text-danger' : 'text-muted-foreground'}"
        data-testid="provider-reach"
        data-state={reachState}
      >
        {#if reachState === "testing"}
          Asking it for its models, from where a sandbox would…
        {:else if reachState === "untested" || !reach}
          {local ? "Not tested yet: Test asks it for its models, from where a sandbox would." : "Test asks it for its models."}
        {:else}
          {reachLine(reach)}
        {/if}
      </p>
    </div>
    {#if testError}<p class="text-xs text-danger" data-testid="provider-test-error">{testError}</p>{/if}
  </fieldset>

  {#if handWritten}
    <p class="text-xs text-muted-foreground">Key: a hand-written reference ({editing?.key}), kept.</p>
  {:else if asksForKey || editing}
    <div class="space-y-1.5">
      <Label for="provider-key">API key</Label>
      <div class="flex flex-wrap items-center gap-3">
        <Input
          id="provider-key"
          class="max-w-sm"
          type="password"
          placeholder={editing?.key === "secret" ? "set (type to replace)" : "paste it"}
          bind:value={key}
          disabled={removeKey}
          data-testid="provider-key"
        />
        {#if editing?.key === "secret"}
          <label class="flex items-center gap-1.5 text-xs"><Checkbox bind:checked={removeKey} />No key</label>
        {/if}
      </div>
      <p class="text-xs text-muted-foreground">Kept in Handler's secret store, never shown again.</p>
    </div>
  {/if}

  <fieldset class="space-y-2">
    <legend class="mb-1 font-medium">Models</legend>
    <p class="text-xs text-muted-foreground">
      The first is the default. In tokens: <em>context</em>, what the model reads at most; <em>reply</em>, what it writes at most. A <em>speech</em> model writes down what
      you say (Settings → Voice), at the speech to text endpoint: never one agents run on.
      An agent sums up its conversation before it fills the context, keeping room for a reply (at most a fifth of the context).
      Test fills them from what the server serves, with its context when it says it.
    </p>
    {#if !models.length}
      <p class="text-xs text-warn" data-testid="provider-no-model">No model yet: Test lists what the server serves, or add one.</p>
    {/if}
    <div class="overflow-x-auto rounded-[10px] border">
      <div class="grid min-w-[42rem] grid-cols-[1.4fr_1fr_6.5rem_6.5rem_auto_auto_auto_2rem] items-center gap-x-2 gap-y-1.5 p-2.5">
        <span class="px-1 text-xs text-muted-foreground">id</span>
        <span class="px-1 text-xs text-muted-foreground">name</span>
        <span class="px-1 text-xs text-muted-foreground">context</span>
        <span class="px-1 text-xs text-muted-foreground">reply</span>
        <span class="text-xs text-muted-foreground">thinks</span>
        <span class="text-xs text-muted-foreground">images</span>
        <span class="text-xs text-muted-foreground">speech</span>
        <span></span>
        {#each models as model, i (i)}
          <div class="contents" data-testid="provider-model">
            <Input class="font-mono text-xs" placeholder="id" list="provider-served" bind:value={model.id} />
            <Input placeholder="name" bind:value={model.name} />
            <Input type="number" placeholder="tokens" bind:value={model.contextWindow} />
            <Input type="number" placeholder="16384" bind:value={model.maxOutput} data-testid="provider-model-reply" />
            <span class="flex justify-center"><Checkbox bind:checked={model.reasoning} aria-label="thinks" /></span>
            <span class="flex justify-center"><Checkbox bind:checked={model.images} aria-label="images" /></span>
            <span class="flex justify-center"><Checkbox bind:checked={model.speech} aria-label="speech" /></span>
            <Button type="button" variant="ghost" size="icon-sm" class="text-muted-foreground" aria-label="Remove the model" onclick={() => models.splice(i, 1)}><X /></Button>
          </div>
        {/each}
      </div>
    </div>
    <datalist id="provider-served">{#each served as m (m.id)}<option value={m.id}></option>{/each}</datalist>
    <Button type="button" variant="ghost" size="sm" onclick={() => models.push(row({ id: "" }))}><Plus />Add a model</Button>
  </fieldset>

  {#if error}<p class="text-danger" data-testid="provider-error">{error}</p>{/if}
  <div class="flex flex-wrap items-center gap-2 border-t pt-4">
    {#if ondelete}
      <Button type="button" variant="ghost" size="sm" class="text-destructive hover:text-destructive" onclick={ondelete} data-testid="provider-delete">Delete</Button>
    {/if}
    <span class="flex-1"></span>
    <Button type="button" variant="ghost" size="sm" onclick={oncancel}>Cancel</Button>
    <Button type="submit" size="sm" disabled={saving || !name.trim() || !models.some((m) => m.id.trim())} data-testid="provider-save">Save</Button>
  </div>
</form>
