<script lang="ts">
  // An agent's instructions, its form's fields seen in them (D.18): a `{{key}}` of its form is
  // coloured, one naming no field is underlined in red, with a way to fix it (one of the form's
  // fields in its place). The text is a plain textarea over a copy of it that only paints those
  // marks: same font, padding and wrapping, its text transparent.
  import { textParts } from "../lib/interface";
  import { Textarea } from "$lib/components/ui/textarea";

  let {
    value = $bindable(),
    ref = $bindable(null),
    fields,
    id,
    placeholder,
    testid,
  }: {
    value: string;
    ref?: HTMLTextAreaElement | null;
    fields: { key: string; title: string }[]; // its form's
    id: string;
    placeholder?: string;
    testid?: string;
  } = $props();

  const parts = $derived(textParts(value, fields.map((f) => f.key)));
  const unknown = $derived([...new Set(parts.filter((p) => p.kind === "unknown").map((p) => p.key!))]);

  function replace(from: string, to: string): void {
    value = parts.map((p) => (p.kind === "unknown" && p.key === from ? `{{${to}}}` : p.text)).join("");
  }
</script>

<div class="space-y-1.5">
  <div class="relative">
    <div aria-hidden="true" class="pointer-events-none absolute inset-0 overflow-hidden rounded-lg border border-transparent px-2.5 py-2 text-base break-words whitespace-pre-wrap text-transparent md:text-sm" data-testid="prompt-marks">
      {#each parts as p, i (i)}{#if p.kind === "field"}<mark class="rounded bg-accent-soft text-transparent ring-1 ring-primary/20">{p.text}</mark>{:else if p.kind === "unknown"}<mark class="rounded bg-danger/10 text-transparent underline decoration-danger decoration-wavy underline-offset-4" data-testid="prompt-unknown">{p.text}</mark>{:else}{p.text}{/if}{/each}{"\n"}
    </div>
    <Textarea {id} bind:value bind:ref rows={3} {placeholder} class="relative" data-testid={testid} />
  </div>
  {#each unknown as key (key)}
    <p class="flex flex-wrap items-center gap-1.5 text-xs text-danger" data-testid="prompt-unknown-fix">
      <span><code>{`{{${key}}}`}</code> is not a field of its form.</span>
      {#each fields as f (f.key)}
        <button type="button" class="cursor-pointer text-link hover:underline" onclick={() => replace(key, f.key)}>Use {f.title}</button>
      {/each}
    </p>
  {/each}
</div>
