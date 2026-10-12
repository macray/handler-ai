<script lang="ts">
  // A project context's tag (D.19, docs/dev/ui-ux.md): its name in its colour; `any` (an account or
  // a provider usable in every context) in grey. Always the word, never the colour alone.
  import { ANY, contexts } from "../lib/contexts.svelte";

  let { name }: { name: string } = $props();
</script>

<span
  class="ctx-tag {name === ANY ? '' : contexts.colorClass(name)} inline-flex shrink-0 items-center rounded-full px-1.5 py-px text-[10.5px] leading-4 font-semibold whitespace-nowrap"
  data-testid="context-tag">{name === ANY ? "any context" : name}</span
>
