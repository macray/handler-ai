<script lang="ts">
  // Pick the addon configurations (bindings: an addon's settings and secrets, contract G) an agent
  // gets, each shown as `addon: configuration`: those used in its project first, each saying which
  // other projects use it (to pick another project's store knowingly). Invalid bindings are not
  // selectable (Settings lists them with their error).
  import { Label } from "$lib/components/ui/label";
  import { api } from "../lib/api";
  import type { BindingInfo } from "../lib/contracts.gen";
  import { byUse, projects } from "../lib/projects.svelte";
  import { href } from "../lib/router.svelte";
  import PickRow from "./PickRow.svelte";

  let {
    projectId,
    value = $bindable([]),
    hint = "Programs and their skills, each in one of its configurations: the Shopify CLI on one store, a browser…",
  }: {
    projectId?: string; // none: an ad-hoc agent
    value?: string[]; // the selected bindings
    hint?: string;
  } = $props();

  let bindings = $state<BindingInfo[]>([]);
  let error = $state<string | null>(null);

  $effect(() => {
    api.bindings().then(
      (list) => (bindings = list),
      (e: Error) => (error = e.message),
    );
  });

  const selectable = $derived(bindings.filter((b) => !b.error));
  const rows = $derived(byUse(projects.list, selectable, projectId));
  const invalid = $derived(bindings.filter((b) => b.error).length);

  // drop what is no longer selectable (once listed)
  $effect(() => {
    if (!bindings.length) return;
    const keep = value.filter((name) => selectable.some((b) => b.name === name));
    if (keep.length !== value.length) value = keep;
  });

  function toggle(name: string, checked: boolean): void {
    value = checked ? [...value, name] : value.filter((n) => n !== name);
  }
</script>

{#if selectable.length || invalid}
  <div class="space-y-2" data-testid="binding-picker">
    <Label>Addons</Label>
    <p class="text-xs text-muted-foreground">
      {hint}
    </p>
    {#if error}<p class="text-sm text-danger">{error}</p>{/if}
    <div class="divide-y overflow-hidden rounded-lg border bg-card">
      {#each rows as { choice: b, note } (b.name)}
        <PickRow
          name={`${b.addon}: ${b.name}`}
          description={b.description ?? ""}
          {note}
          checked={value.includes(b.name)}
          onchange={(checked) => toggle(b.name, checked)}
          testid="binding-option"
        />
      {/each}
    </div>
    {#if invalid}
      <p class="text-xs text-muted-foreground">
        {invalid} invalid configuration(s): see <a class="text-link hover:underline" href={href({ view: "settings", section: "addons" })}>Settings → Addons</a>.
      </p>
    {/if}
  </div>
{/if}
