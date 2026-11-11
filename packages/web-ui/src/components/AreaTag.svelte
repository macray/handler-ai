<script lang="ts">
  // An area's tag (D.19, UI-UX guide): its name in its colour; `any` (an account or
  // a provider usable in every area) in grey. Always the word, never the colour alone.
  import { ANY, areas } from "../lib/areas.svelte";

  let { name }: { name: string } = $props();
</script>

<span
  class="area-tag {name === ANY ? '' : areas.colorClass(name)} inline-flex shrink-0 items-center rounded-full px-1.5 py-px text-[10.5px] leading-4 font-semibold whitespace-nowrap"
  data-testid="area-tag">{name === ANY ? "any area" : name}</span
>
