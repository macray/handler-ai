<script lang="ts">
  // An addon configuration's form (a binding, G.2, D.15): its name, its settings and its secrets.
  // Secret values go to the secret store and are never shown: empty keeps the one it has; a
  // hand-written reference (env, file, command) is kept as it is.
  import { Button } from "$lib/components/ui/button";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import { Input } from "$lib/components/ui/input";
  import type { AddonInfo, BindingInfo, BindingRequest } from "../lib/contracts.gen";

  let {
    addon,
    start,
    editing = null,
    onsave,
    oncancel,
  }: {
    addon: AddonInfo;
    start: string; // a free name for a new binding
    editing?: BindingInfo | null; // the binding being edited; null: a new one
    onsave: (body: BindingRequest) => Promise<void>;
    oncancel: () => void;
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

<form class="space-y-3 rounded-md border bg-background p-3 text-sm" onsubmit={(e) => (e.preventDefault(), void submit())} data-testid="binding-form">
  <div class="flex flex-wrap gap-2">
    <Input class="w-44" placeholder="configuration name" bind:value={name} required data-testid="binding-name" />
    <Input class="min-w-40 flex-1" placeholder="description (optional)" bind:value={description} />
  </div>
  {#if addon.settings?.length || addon.secretSlots?.length}
    <div class="grid grid-cols-[minmax(6rem,auto)_1fr] gap-x-3 gap-y-2.5">
      {#each addon.settings ?? [] as slot (slot.name)}
        <label for={`binding-setting-${slot.name}`} class="pt-2 font-mono text-xs">{slot.name}{#if slot.required}<span class="text-danger"> *</span>{/if}</label>
        <div class="min-w-0 space-y-1">
          <Input id={`binding-setting-${slot.name}`} bind:value={settings[slot.name]} data-testid={`binding-setting-${slot.name}`} />
          {#if slot.description}<p class="text-xs text-muted-foreground">{slot.description}</p>{/if}
        </div>
      {/each}
      {#each addon.secretSlots ?? [] as slot (slot.name)}
        <label for={`binding-secret-${slot.name}`} class="pt-2 font-mono text-xs">{slot.name}{#if slot.required}<span class="text-danger"> *</span>{/if}</label>
        <div class="min-w-0 space-y-1">
          {#if handWritten(slot.name)}
            <p class="pt-2 text-xs text-muted-foreground">A hand-written reference, kept.</p>
          {:else}
            <div class="flex items-center gap-3">
              <Input
                id={`binding-secret-${slot.name}`}
                type="password"
                placeholder={bound(slot.name) ? "set (type to replace)" : "secret"}
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
    </div>
  {/if}
  {#if addon.egress?.length}
    <p class="text-xs text-muted-foreground">Its agents reach {addon.egress.join(", ")}; secrets are only meant for these hosts.</p>
  {/if}
  <div class="flex gap-2">
    <Button type="submit" size="sm" disabled={saving || !name.trim() || missing.length > 0} data-testid="binding-save">Save</Button>
    <Button type="button" variant="ghost" size="sm" onclick={oncancel}>Cancel</Button>
  </div>
</form>
