<script lang="ts">
  // An addon configuration's form (a binding, G.2, D.15), in its dialog: its name, its settings and
  // its secrets, each labelled with what the addon says of it; an existing one's Delete, offered
  // while no agent uses it.
  // Secret values go to the secret store and are never shown: empty keeps the one it has; a
  // hand-written reference (env, file, command) is kept as it is.
  import { Button } from "$lib/components/ui/button";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import type { AddonInfo, BindingInfo, BindingRequest } from "../lib/contracts.gen";

  let {
    addon,
    start,
    editing = null,
    onsave,
    oncancel,
    ondelete,
    error = null,
  }: {
    addon: AddonInfo;
    start: string; // a free name for a new binding
    editing?: BindingInfo | null; // the binding being edited; null: a new one
    onsave: (body: BindingRequest) => Promise<void>;
    oncancel: () => void;
    ondelete?: () => void; // an existing one, used by no agent
    error?: string | null; // what the last save was refused for
  } = $props();

  // svelte-ignore state_referenced_locally — the form starts from `editing` once
  let name = $state(editing?.name ?? start);
  // svelte-ignore state_referenced_locally
  let description = $state(editing?.description ?? "");
  // svelte-ignore state_referenced_locally
  let settings = $state<Record<string, string>>({
    ...Object.fromEntries((addon.settings ?? []).map((s) => [s.name, ""])),
    ...(editing?.settings ?? {}),
  });
  // svelte-ignore state_referenced_locally
  let secrets = $state<Record<string, string>>(Object.fromEntries((addon.secretSlots ?? []).map((s) => [s.name, ""])));
  // svelte-ignore state_referenced_locally
  let removed = $state<Record<string, boolean>>(Object.fromEntries((addon.secretSlots ?? []).map((s) => [s.name, false])));
  let saving = $state(false);

  const bound = (slot: string) => editing?.secrets?.includes(slot) ?? false;
  const handWritten = (slot: string) => editing?.handWritten?.includes(slot) ?? false;
  const missing = $derived([
    ...(addon.settings ?? []).filter((s) => s.required && !settings[s.name]?.trim()),
    ...(addon.secretSlots ?? []).filter((s) => s.required && !bound(s.name) && !secrets[s.name]?.trim()),
  ]);

  async function submit(): Promise<void> {
    saving = true;
    try {
      await onsave({
        name: name.trim(),
        addon: addon.name,
        description: description.trim() || null,
        settings: Object.fromEntries(Object.entries(settings).filter(([, v]) => v.trim()).map(([k, v]) => [k, v.trim()])),
        secrets: Object.fromEntries(Object.entries(secrets).filter(([k, v]) => v.trim() && !removed[k])),
        removeSecrets: Object.keys(removed).filter((k) => removed[k]),
      });
    } finally {
      saving = false;
    }
  }
</script>

{#snippet slotLabel(id: string, slot: { name: string; required?: boolean })}
  <label for={id} class="font-mono text-xs font-medium">{slot.name}{#if slot.required}<span class="text-danger"> *</span>{/if}</label>
{/snippet}

<form class="space-y-6" onsubmit={(e) => (e.preventDefault(), void submit())} data-testid="binding-form">
  <div class="grid gap-4 sm:grid-cols-[1fr_1.6fr]">
    <div class="space-y-1.5">
      <Label for="binding-name">Name</Label>
      <Input id="binding-name" bind:value={name} required data-testid="binding-name" />
    </div>
    <div class="space-y-1.5">
      <Label for="binding-description">Description (optional)</Label>
      <Input id="binding-description" placeholder="e.g. the dev store" bind:value={description} />
    </div>
  </div>

  {#if addon.settings?.length}
    <fieldset class="space-y-3">
      <legend class="mb-1 font-medium">Settings</legend>
      {#each addon.settings as slot (slot.name)}
        <div class="space-y-1.5">
          {@render slotLabel(`binding-setting-${slot.name}`, slot)}
          <Input id={`binding-setting-${slot.name}`} bind:value={settings[slot.name]} data-testid={`binding-setting-${slot.name}`} />
          {#if slot.description}<p class="text-xs text-muted-foreground">{slot.description}</p>{/if}
        </div>
      {/each}
    </fieldset>
  {/if}

  {#if addon.secretSlots?.length}
    <fieldset class="space-y-3">
      <legend class="mb-1 font-medium">Secrets</legend>
      <p class="text-xs text-muted-foreground">
        Kept in Handler's secret store, never shown again{#if addon.egress?.length}; only meant for the hosts its agents reach:
          <span class="font-mono">{addon.egress.join(", ")}</span>{/if}.
      </p>
      {#each addon.secretSlots as slot (slot.name)}
        <div class="space-y-1.5">
          {@render slotLabel(`binding-secret-${slot.name}`, slot)}
          {#if handWritten(slot.name)}
            <p class="text-xs text-muted-foreground">A hand-written reference, kept.</p>
          {:else}
            <div class="flex items-center gap-3">
              <Input
                id={`binding-secret-${slot.name}`}
                type="password"
                placeholder={bound(slot.name) ? "set (type to replace)" : "paste it"}
                bind:value={secrets[slot.name]}
                disabled={removed[slot.name]}
                data-testid={`binding-secret-${slot.name}`}
              />
              {#if bound(slot.name) && !slot.required}
                <label class="flex shrink-0 items-center gap-1.5 text-xs"><Checkbox bind:checked={removed[slot.name]} />None</label>
              {/if}
            </div>
          {/if}
          {#if slot.description}<p class="text-xs text-muted-foreground">{slot.description}</p>{/if}
        </div>
      {/each}
    </fieldset>
  {:else if addon.egress?.length}
    <p class="text-xs text-muted-foreground">Its agents reach <span class="font-mono">{addon.egress.join(", ")}</span>.</p>
  {/if}

  {#if !addon.settings?.length && !addon.secretSlots?.length}
    <p class="text-xs text-muted-foreground">It asks for nothing: a name is enough.</p>
  {/if}
  {#if error}<p class="text-danger" data-testid="binding-error">{error}</p>{/if}
  <div class="flex flex-wrap items-center gap-2 border-t pt-4">
    {#if ondelete}
      <Button type="button" variant="ghost" size="sm" class="text-destructive hover:text-destructive" onclick={ondelete} data-testid="binding-delete">Delete</Button>
    {/if}
    <span class="flex-1"></span>
    <Button type="button" variant="ghost" size="sm" onclick={oncancel}>Cancel</Button>
    <Button type="submit" size="sm" disabled={saving || !name.trim() || missing.length > 0} data-testid="binding-save">Save</Button>
  </div>
</form>
