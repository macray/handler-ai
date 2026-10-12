<script lang="ts">
  // A list of allowed hosts (HOST:PORT) to add to and remove from. `onchange` gets the new list
  // (sorted, no duplicates); `saving` disables it while the caller saves. `suggestions`: hosts
  // offered one click each (e.g. asked for recently, no entry allowing them: never added
  // automatically, the agent picks them).
  import Plus from "@lucide/svelte/icons/plus";
  import X from "@lucide/svelte/icons/x";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { isEgressEntry, normalizeEntry, withEntry } from "../lib/hosts";

  let {
    value,
    onchange,
    saving = false,
    suggestions = [],
    empty = "None.",
  }: {
    value: string[];
    onchange: (next: string[]) => void | Promise<void>;
    saving?: boolean;
    suggestions?: string[];
    empty?: string;
  } = $props();

  let input = $state("");
  let error = $state<string | null>(null);

  const entry = $derived(normalizeEntry(input));
  const offered = $derived(suggestions.filter((h) => !value.includes(h)));

  async function add(event?: SubmitEvent): Promise<void> {
    event?.preventDefault();
    if (!isEgressEntry(entry)) {
      error =
        "an entry is HOST:PORT, with the port written out (443 for https, 80 for http): example.com:443, " +
        "*.example.com:443 for its subdomains, 192.168.1.20:11434";
      return;
    }
    error = null;
    await onchange(withEntry(value, entry));
    input = "";
  }
</script>

<div class="flex flex-col gap-2 text-sm" data-testid="host-list">
  <ul class="flex flex-wrap gap-1.5">
    {#each value as host (host)}
      <li class="flex items-center gap-1 rounded-md border bg-background py-0.5 pr-0.5 pl-2 font-mono text-xs" data-testid="allow-entry">
        {host}
        <Button variant="ghost" size="icon-sm" class="size-5" disabled={saving} onclick={() => onchange(value.filter((h) => h !== host))} aria-label={`remove ${host}`}>
          <X class="size-3" />
        </Button>
      </li>
    {:else}
      <li class="text-xs text-muted-foreground">{empty}</li>
    {/each}
  </ul>
  <!-- a div, not a form: this list sits inside other forms -->
  <div class="flex max-w-md gap-2">
    <Input
      bind:value={input}
      class="h-8 font-mono text-xs"
      placeholder="example.com:443 or *.example.com:443"
      aria-label="host to allow"
      onkeydown={(e: KeyboardEvent) => {
        if (e.key === "Enter") {
          e.preventDefault();
          void add();
        }
      }}
    />
    <Button type="button" variant="outline" size="sm" disabled={saving || !entry} onclick={() => add()}><Plus />Allow</Button>
  </div>
  {#if offered.length}
    <div class="space-y-1.5">
      <p class="text-xs text-muted-foreground">Asked for recently, not allowed (refused, or let through by log only): check before allowing:</p>
      <ul class="flex flex-wrap gap-1.5">
        {#each offered as host (host)}
          <li>
            <Button variant="outline" size="sm" class="h-6 font-mono text-xs text-danger" disabled={saving} onclick={() => onchange(withEntry(value, host))} data-testid="allow-denied">
              <Plus class="size-3" />{host}
            </Button>
          </li>
        {/each}
      </ul>
    </div>
  {/if}
  {#if error}<p class="text-xs text-danger">{error}</p>{/if}
</div>
