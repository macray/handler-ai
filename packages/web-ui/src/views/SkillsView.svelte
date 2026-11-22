<script lang="ts">
  // The Library's Skills shelf (D.17): what agents load when a task calls for it, yours or the
  // ways to get one, its Community (SkillLibrary); then, with yours, the helpers that write and review skills
  // (D.18), each named and linked to its page in Settings → Helpers.
  import HelperLink from "../components/HelperLink.svelte";
  import ShelfBar from "../components/ShelfBar.svelte";
  import SkillLibrary from "../components/SkillLibrary.svelte";
  import { LIBRARY_WIDTH, type ShelfLists } from "../lib/library";

  let { more = false, lists }: { more?: boolean; lists?: ShelfLists } = $props();
</script>

<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full {LIBRARY_WIDTH} space-y-5 px-8 py-6" data-testid="skills-page">
    <ShelfBar {lists} />
    <SkillLibrary {more} />
    {#if !more}
      <p class="text-sm text-muted-foreground" data-testid="skill-helpers"><HelperLink need="skill-creator" /> · <HelperLink need="skill-review" /></p>
    {/if}
  </div>
</div>
