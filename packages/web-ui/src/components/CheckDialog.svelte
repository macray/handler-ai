<script lang="ts">
  // A run kept as a check, or a check changed (D.20): its name, and which of its result's fields
  // must come back the same (those that are not free text: free text is shown, never compared).
  import { api } from "../lib/api";
  import type { Check } from "../lib/contracts.gen";
  import { fieldsOf, type Schema } from "../lib/runs";
  import { Button } from "$lib/components/ui/button";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import Dialog from "./Dialog.svelte";

  let {
    open = $bindable(false),
    agentId,
    result,
    comparable,
    answer,
    fromRun,
    check,
    name: startName = "",
    onsaved,
  }: {
    open: boolean;
    agentId: string;
    result: Schema | undefined; // the job's result schema: its fields' titles
    comparable: string[]; // the fields a check may compare
    answer: Record<string, unknown>; // the right result: the run's, or the check's
    fromRun?: string; // keep this run
    check?: Check; // or change this check
    name?: string;
    onsaved: (check: Check) => void;
  } = $props();

  // svelte-ignore state_referenced_locally
  let name = $state(check?.name ?? startName);
  // svelte-ignore state_referenced_locally
  let compare = $state<string[]>(check ? [...check.compare] : [...comparable]);
  let busy = $state(false);
  let error = $state<string | null>(null);

  const fields = $derived(fieldsOf(result));
  const shown = (v: unknown) => (v === undefined ? "—" : typeof v === "string" ? v : JSON.stringify(v));

  function toggle(key: string, on: boolean): void {
    compare = on ? [...compare, key] : compare.filter((k) => k !== key);
  }

  async function save(): Promise<void> {
    busy = true;
    error = null;
    try {
      const saved = check
        ? await api.updateCheck(agentId, check.id, name.trim(), compare)
        : await api.keepCheck(agentId, fromRun!, name.trim(), compare);
      open = false;
      onsaved(saved);
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

<Dialog bind:open title={check ? "Change the check" : "Keep as a check"} description="Run again with the same input, it passes when these come back the same." testid="check-dialog">
  <form
    class="space-y-4"
    onsubmit={(e) => {
      e.preventDefault();
      void save();
    }}
  >
    <div class="space-y-1.5">
      <Label for="check-name">Name</Label>
      <Input id="check-name" bind:value={name} placeholder="e.g. A polite no" required data-testid="check-name" />
    </div>
    <div class="space-y-1.5">
      <Label>What must come back the same</Label>
      <ul class="divide-y rounded-lg border" data-testid="check-fields">
        {#each fields as f (f.key)}
          {@const can = comparable.includes(f.key)}
          <li class="flex items-start gap-2 px-3 py-2">
            <Checkbox id="check-{f.key}" checked={compare.includes(f.key)} disabled={!can} onCheckedChange={(c) => toggle(f.key, c === true)} />
            <div class="min-w-0 space-y-0.5">
              <Label for="check-{f.key}" class="font-normal {can ? '' : 'text-muted-foreground'}">{f.title}</Label>
              <p class="fact text-xs break-words text-muted-foreground">{shown(answer[f.key])}</p>
              {#if !can}<p class="text-xs text-muted-foreground">Free text: shown, never compared.</p>{/if}
            </div>
          </li>
        {/each}
      </ul>
    </div>
    {#if error}<p class="text-sm text-danger">{error}</p>{/if}
    <div class="flex justify-end gap-2">
      <Button type="button" variant="ghost" onclick={() => (open = false)}>Cancel</Button>
      <Button type="submit" disabled={busy || !name.trim() || !compare.length} data-testid="check-save">{check ? "Save" : "Keep it"}</Button>
    </div>
  </form>
</Dialog>
