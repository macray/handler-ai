<script lang="ts">
  // On every page: agents cannot run on this computer (A.8), what is missing, and where it is
  // explained (Settings → Sandboxes, which shows the details itself).
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import { router, href } from "../lib/router.svelte";
  import { runtime } from "../lib/runtime.svelte";

  const missing = $derived(runtime.last?.items.filter((i) => i.required && !i.ok).map((i) => i.name) ?? []);
  const onImages = $derived(router.route.view === "settings" && router.route.section === "sandboxes");
</script>

{#if runtime.blocked && !onImages}
  <div class="flex items-start gap-2 border-b border-danger/40 bg-danger/5 px-4 py-2 text-sm" role="alert" data-testid="runtime-banner">
    <TriangleAlert class="mt-0.5 size-4 shrink-0 text-danger" />
    <p>
      <span class="font-medium">Agents can't run on this computer yet</span>: {missing.join(", ")} missing.
      <a class="text-link hover:underline" href={href({ view: "settings", section: "sandboxes" })}>What to fix →</a>
    </p>
  </div>
{/if}
