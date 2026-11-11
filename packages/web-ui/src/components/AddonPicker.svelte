<script lang="ts">
  // Pick the addons an agent or a project uses (contract G.3): an addon without settings by its
  // name, one with settings in one of its configurations (bindings: its settings and secrets),
  // shown as `addon: configuration`, those used in this project first, each saying which other
  // projects use it (to pick another project's store knowingly). One configuration per addon:
  // picking another replaces it. The addons its project gives are listed first, checked, not
  // choosable. Invalid addons and configurations are not selectable (Library → Addons lists them
  // with their error). `chips`: the agent form's row, what it uses as chips ("github as acme-bot"),
  // the list behind + Add.
  import { Label } from "$lib/components/ui/label";
  import { api } from "../lib/api";
  import type { AddonInfo, AddonUse, BindingInfo } from "../lib/contracts.gen";
  import { byUse, projects } from "../lib/projects.svelte";
  import { href } from "../lib/router.svelte";
  import { hasSlots } from "../lib/setup";
  import PickRow from "./PickRow.svelte";
  import PickerChips from "./PickerChips.svelte";

  let {
    projectId,
    given = [],
    value = $bindable([]),
    hint = "Programs and their skills, those with settings through one of your connections: the Shopify CLI on one store, a browser…",
    chips = false,
  }: {
    projectId?: string; // the project whose use comes first; none: an agent outside projects
    given?: AddonUse[]; // what its project gives to all its agents (an agent's picker)
    value?: AddonUse[]; // the addons picked
    hint?: string;
    chips?: boolean;
  } = $props();

  let addons = $state<AddonInfo[]>([]);
  let bindings = $state<BindingInfo[]>([]);
  let loaded = $state(false);
  let error = $state<string | null>(null);

  $effect(() => {
    Promise.all([api.addons(), api.bindings()]).then(
      ([a, b]) => {
        [addons, bindings, loaded] = [a, b, true];
      },
      (e: Error) => (error = e.message),
    );
  });

  const label = (u: AddonUse): string => (u.binding ? `${u.addon}: ${u.binding}` : u.addon);
  const isGiven = (addon: string): boolean => given.some((u) => u.addon === addon);
  const valid = $derived(addons.filter((a) => !a.error && !isGiven(a.name)));
  // an addon without settings, by its name
  const plain = $derived(valid.filter((a) => !hasSlots(a)));
  // a configuration of an addon with settings
  const configured = $derived(bindings.filter((b) => !b.error && valid.some((a) => a.name === b.addon && hasSlots(a))));
  const rows = $derived([
    ...plain.map((a) => ({ use: { addon: a.name } as AddonUse, description: a.description ?? "", note: "" })),
    ...byUse(projects.list, configured, projectId).map(({ choice: b, note }) => ({
      use: { addon: b.addon ?? "", binding: b.name } as AddonUse,
      description: b.description ?? addons.find((a) => a.name === b.addon)?.description ?? "",
      note,
    })),
  ]);
  const invalid = $derived(addons.filter((a) => a.error).length + bindings.filter((b) => b.error).length);
  const picked = (u: AddonUse): boolean => value.some((v) => v.addon === u.addon && (v.binding ?? null) === (u.binding ?? null));

  // drop what is no longer selectable (once listed)
  $effect(() => {
    if (!loaded) return;
    const keep = value.filter((v) => rows.some((r) => r.use.addon === v.addon && (r.use.binding ?? null) === (v.binding ?? null)));
    if (keep.length !== value.length) value = keep;
  });

  function toggle(use: AddonUse, checked: boolean): void {
    const others = value.filter((v) => v.addon !== use.addon); // one configuration per addon
    value = checked ? [...others, use].sort((a, b) => a.addon.localeCompare(b.addon)) : others;
  }
</script>

{#snippet options()}
  {#each given as u (u.addon)}
    <PickRow name={label(u)} note="given by its project" checked disabled testid="addon-given" />
  {/each}
  {#each rows as { use, description, note } (label(use))}
    <PickRow name={label(use)} {description} {note} checked={picked(use)} onchange={(checked) => toggle(use, checked)} testid="addon-option" />
  {/each}
{/snippet}
{#snippet invalidLine()}
  {#if invalid}
    <p class="text-xs text-muted-foreground">
      {invalid} broken tool(s) or connection(s): see <a class="text-link hover:underline" href={href({ view: "addons" })}>Library → Tools</a>.
    </p>
  {/if}
{/snippet}

{#if chips}
  <PickerChips
    chips={[
      ...given.map((u) => ({ key: `given:${u.addon}`, name: u.addon, as: u.binding ?? undefined, locked: "Given by its project" })),
      ...value.map((u) => ({ key: u.addon, name: u.addon, as: u.binding ?? undefined })),
    ]}
    onremove={(addon) => (value = value.filter((v) => v.addon !== addon))}
    label="Add a tool"
    testid="addon-picker"
  >
    {#snippet list()}
      <div class="divide-y">
        {@render options()}
        {#if !rows.length && !given.length}
          <p class="px-3 py-2 text-xs text-muted-foreground">
            No tool yet: get one in the <a class="text-link hover:underline" href={href({ view: "addons" })}>Library</a>.
          </p>
        {/if}
      </div>
    {/snippet}
  </PickerChips>
  {#if error}<p class="text-sm text-danger">{error}</p>{/if}
  {@render invalidLine()}
{:else if rows.length || given.length || invalid}
  <div class="space-y-2" data-testid="addon-picker">
    <Label>Tools</Label>
    <p class="text-xs text-muted-foreground">
      {hint}
    </p>
    {#if error}<p class="text-sm text-danger">{error}</p>{/if}
    <div class="divide-y overflow-hidden rounded-lg border bg-card">
      {@render options()}
    </div>
    {@render invalidLine()}
  </div>
{/if}
