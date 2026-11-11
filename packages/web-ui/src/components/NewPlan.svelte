<script lang="ts">
  // New plan (D.27): a draft for a project and a session of the plan builder on it, opened. The
  // first time, the plan builder's set-up card under the button (a helper, D.18), then the plan
  // starts. `project`: the one chosen (a project's page), else one is chosen here (Plans). The
  // builder's model refused for the project's area: another one of that area, for this session.
  import Plus from "@lucide/svelte/icons/plus";
  import { Button } from "$lib/components/ui/button";
  import * as NativeSelect from "$lib/components/ui/native-select";
  import { chosen, noAccess, type ModelAccess } from "../lib/access";
  import { areaRefused, startPlan } from "../lib/plans";
  import { projects } from "../lib/projects.svelte";
  import HelperCard from "./HelperCard.svelte";
  import ModelAccessPicker from "./ModelAccessPicker.svelte";

  let { project }: { project?: string } = $props();

  // svelte-ignore state_referenced_locally
  let picked = $state(project ?? "");
  const target = $derived(project ?? picked);
  const area = $derived(projects.list.find((p) => p.id === target)?.area ?? null);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let other = $state<ModelAccess | null>(null); // the builder's model refused: another one
  let setUp = $state(false); // no plan builder yet: its card
  const projectName = $derived(projects.list.find((p) => p.id === target)?.name);

  async function start(): Promise<void> {
    if (!target) return;
    busy = true;
    error = null;
    try {
      setUp = !(await startPlan(target, other && chosen(other) ? other : undefined));
    } catch (e) {
      if (areaRefused(e) && other === null) other = noAccess();
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

<div class="space-y-2 {setUp ? 'w-full' : ''}" data-testid="new-plan">
  <div class="flex flex-wrap items-center gap-2">
    {#if !project}
      <NativeSelect.Root class="w-56" value={picked} onchange={(e) => ((picked = e.currentTarget.value), (other = null), (error = null))} aria-label="The project of the plan" data-testid="new-plan-project">
        <NativeSelect.Option value="" disabled>Choose a project…</NativeSelect.Option>
        {#each projects.list as p (p.id)}<NativeSelect.Option value={p.id}>{p.name}</NativeSelect.Option>{/each}
      </NativeSelect.Root>
    {/if}
    <Button
      size="sm"
      disabled={busy || !target || (other !== null && !chosen(other))}
      onclick={start}
      data-testid="new-plan-start"><Plus />{other ? "Start with this model" : "New plan"}</Button
    >
  </div>
  {#if error}<p class="text-sm text-danger" data-testid="new-plan-error">{error}</p>{/if}
  {#if setUp}
    <HelperCard need="plan-builder" title={projectName ? `Plans for ${projectName}` : undefined} onready={() => ((setUp = false), void start())}>
      {#snippet preview()}
        <ol class="space-y-1.5 text-xs">
          {#each ["Move the cart to a drawer component", "Replace the inline script", "Test at 390px and 1440px"] as step, i (i)}
            <li class="flex items-center gap-2"><span class="size-2 rounded-full {i < 2 ? 'bg-muted-foreground/60' : 'border border-muted-foreground/60'}"></span>{i + 1} · {step}</li>
          {/each}
        </ol>
      {/snippet}
    </HelperCard>
  {/if}
  {#if other !== null}
    <div class="space-y-2 text-sm" data-testid="new-plan-model">
      <p class="text-muted-foreground">The plan builder's model is not for this project's area. Choose one that is, for this plan:</p>
      <ModelAccessPicker bind:value={other} {area} />
    </div>
  {/if}
</div>
