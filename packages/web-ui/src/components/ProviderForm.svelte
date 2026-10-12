<script lang="ts">
  // A provider's form (D.12): name, endpoints by protocol, key, models. Starts from a template or
  // from the provider being edited. The key goes to the secret store and is never shown: empty
  // keeps the one it has. Model fields the form does not show (maxOutput, native…) are kept.
  import X from "@lucide/svelte/icons/x";
  import { Button } from "$lib/components/ui/button";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import { Input } from "$lib/components/ui/input";
  import ContextsPicker from "./ContextsPicker.svelte";
  import type { ProviderInfo, ProviderModel, ProviderRequest, ProviderTemplate } from "../lib/contracts.gen";

  let {
    start,
    editing = null,
    onsave,
    oncancel,
  }: {
    start: ProviderTemplate | ProviderInfo;
    editing?: ProviderInfo | null; // the provider being edited; null: a new one
    onsave: (body: ProviderRequest) => Promise<void>;
    oncancel: () => void;
  } = $props();

  const PROTOCOLS = [
    ["anthropic", "Anthropic (Claude Code)"],
    ["openai-chat", "OpenAI chat (pi, Vibe)"],
    ["responses", "Responses (Codex)"],
  ] as const;

  // svelte-ignore state_referenced_locally — the form starts from `start` once
  let name = $state(editing?.name ?? start.name);
  // svelte-ignore state_referenced_locally
  let description = $state(start.description ?? "");
  // svelte-ignore state_referenced_locally — a template is made for no context yet
  let contexts = $state<string[]>(editing?.contexts ?? []);
  // svelte-ignore state_referenced_locally
  let endpoints = $state<Record<string, string>>({ ...(start.endpoints ?? {}) });
  // a model row: its checkboxes bind booleans (binding undefined to one with a default throws)
  const row = (m: ProviderModel): ProviderModel => ({ ...m, reasoning: m.reasoning ?? false, images: m.images ?? false });
  // svelte-ignore state_referenced_locally
  let models = $state<ProviderModel[]>((start.models ?? []).map(row));
  let key = $state("");
  let removeKey = $state(false);
  let saving = $state(false);

  const handWritten = $derived(editing?.key && editing.key !== "secret");
  const asksForKey = $derived(editing ? editing.key === "secret" || !editing.key : Boolean((start as ProviderTemplate).needsKey));

  async function submit(): Promise<void> {
    saving = true;
    try {
      const filled = Object.fromEntries(Object.entries(endpoints).filter(([, url]) => url.trim()));
      const kept = models.filter((m) => m.id.trim());
      await onsave({
        name: name.trim(),
        description: description.trim() || null,
        endpoints: filled,
        models: kept as ProviderRequest["models"],
        key: key.trim() || null,
        removeKey,
        contexts,
        // a template's config files for some harnesses (codex's system prompt): given once, kept
        files: editing ? null : ((start as ProviderTemplate).files ?? null),
      });
    } finally {
      saving = false;
    }
  }
</script>

<form class="space-y-3 rounded-lg border bg-card p-3 text-sm" onsubmit={(e) => (e.preventDefault(), void submit())} data-testid="provider-form">
  <div class="flex flex-wrap gap-2">
    <Input class="w-44" placeholder="name" bind:value={name} required data-testid="provider-name" />
    <Input class="min-w-48 flex-1" placeholder="description (optional)" bind:value={description} />
  </div>
  <ContextsPicker bind:value={contexts} />
  <div class="grid grid-cols-[10rem_1fr] items-center gap-x-2 gap-y-1">
    {#each PROTOCOLS as [protocol, label] (protocol)}
      <span class="text-xs text-muted-foreground">{label}</span>
      <Input placeholder="URL, if it speaks it" bind:value={endpoints[protocol]} data-testid={`provider-endpoint-${protocol}`} />
    {/each}
  </div>
  {#if handWritten}
    <p class="text-xs text-muted-foreground">Key: a hand-written reference ({editing?.key}), kept.</p>
  {:else if asksForKey || editing}
    <div class="flex flex-wrap items-center gap-3">
      <Input
        class="max-w-sm"
        type="password"
        placeholder={editing?.key === "secret" ? "key: set (type to replace)" : "key"}
        bind:value={key}
        disabled={removeKey}
        data-testid="provider-key"
      />
      {#if editing?.key === "secret"}
        <label class="flex items-center gap-1.5 text-xs"><Checkbox bind:checked={removeKey} />No key</label>
      {/if}
    </div>
  {/if}
  <div class="space-y-1">
    <div class="text-xs text-muted-foreground">Models (the first is the default)</div>
    {#each models as model, i (i)}
      <div class="flex flex-wrap items-center gap-2" data-testid="provider-model">
        <Input class="w-56 font-mono" placeholder="id" bind:value={model.id} />
        <Input class="w-44" placeholder="name" bind:value={model.name} />
        <Input class="w-32" type="number" placeholder="context" bind:value={model.contextWindow} />
        <label class="flex items-center gap-1.5 text-xs"><Checkbox bind:checked={model.reasoning} />thinks</label>
        <label class="flex items-center gap-1.5 text-xs"><Checkbox bind:checked={model.images} />images</label>
        <Button type="button" variant="ghost" size="icon-sm" aria-label="Remove the model" onclick={() => models.splice(i, 1)}><X /></Button>
      </div>
    {/each}
    <Button type="button" variant="ghost" size="sm" onclick={() => models.push(row({ id: "" }))}>Add a model</Button>
  </div>
  <div class="flex gap-2">
    <Button type="submit" size="sm" disabled={saving || !name.trim() || !models.some((m) => m.id.trim())} data-testid="provider-save">Save</Button>
    <Button type="button" variant="ghost" size="sm" onclick={oncancel}>Cancel</Button>
  </div>
</form>
