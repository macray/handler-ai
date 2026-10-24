<script lang="ts">
  // A session that cannot start yet: an image it needs is not built on this computer (F.1
  // `missingImage`: the build that makes it, D.4). Prepared from here, its progress followed as in
  // Settings → Images, then the session started. Meant for the session's ended footer.
  import Hammer from "@lucide/svelte/icons/hammer";
  import Play from "@lucide/svelte/icons/play";
  import { Button } from "$lib/components/ui/button";
  import { api } from "../lib/api";
  import type { Build } from "../lib/contracts.gen";
  import { productName } from "../lib/harnesses.svelte";
  import { href } from "../lib/router.svelte";

  // `refused`: when its start was refused; a build ended before did not make the image it lacks
  let { target, agent, refused, error, onstart }: { target: string; agent: string; refused: string; error?: string | null; onstart: () => void } = $props();

  // what it needs, in words: an addon's tools, the agent's program, or Handler's network filter
  const what = $derived(
    target === "network-filter" ? "the network filter" : target.startsWith("addon:") ? `the ${target.slice("addon:".length)} tools` : productName(target),
  );

  let build = $state<Build | null>(null);
  let failure = $state<string | null>(null); // why it could not be started
  let now = $state(Date.now());
  const preparing = $derived(build?.state === "running");
  const elapsed = $derived.by(() => {
    const s = build ? Math.max(0, Math.floor((now - Date.parse(build.startedAt)) / 1000)) : 0;
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  });

  // its last build (handlerd prepares an addon's tools once an agent uses it; Settings → Images):
  // followed while it runs, ready once it succeeded
  $effect(() => {
    void target;
    api.builds().then(
      (list) => {
        const last = list.find((b) => b.target === target); // newest first
        const after = last?.state === "succeeded" && Date.parse(last.endedAt ?? "") > Date.parse(refused);
        build = last && (last.state === "running" || after) ? last : null;
      },
      () => {},
    );
  });

  $effect(() => {
    if (!preparing) return;
    const timer = setInterval(() => {
      now = Date.now();
      if (build) api.build(build.id).then((b) => (build = b), () => {});
    }, 1000);
    return () => clearInterval(timer);
  });

  async function prepare(): Promise<void> {
    failure = null;
    try {
      build = await api.rebuild(target);
      now = Date.now();
    } catch (e) {
      failure = (e as Error).message;
    }
  }
</script>

<div class="flex flex-wrap items-center gap-x-4 gap-y-3" data-testid="missing-image">
  <span class="grid size-8 shrink-0 place-items-center rounded-full bg-warn/10 text-warn"><Hammer class="size-4" /></span>
  <div class="min-w-0 flex-1 basis-64 space-y-0.5" aria-live="polite">
    {#if build?.state === "succeeded"}
      <h2 class="text-sm font-semibold">Ready</h2>
      <p class="text-sm text-muted-foreground">{what} {target.startsWith("addon:") ? "are" : "is"} prepared. Start the session.</p>
    {:else}
      <h2 class="text-sm font-semibold">{agent} can't start yet</h2>
      {#if preparing}
        <p class="text-sm text-muted-foreground" data-testid="missing-image-preparing">
          Preparing {what}… <span class="fact tabular-nums">{elapsed}</span>{#if build?.step && build.steps}<span class="fact tabular-nums"> · step {build.step}/{build.steps}</span>{/if}
        </p>
      {:else if build}
        <p class="text-sm text-danger">
          Preparing {what} failed{build.error ? `: ${build.error}` : ""}. Its log is in
          <a class="text-link hover:underline" href={href({ view: "settings", section: "images" })}>Settings → Images</a>.
        </p>
      {:else}
        <p class="text-sm text-muted-foreground">
          It needs {what}, not prepared on this computer yet. Preparing takes a few minutes, once. Also in
          <a class="text-link hover:underline" href={href({ view: "settings", section: "images" })}>Settings → Images</a>.
        </p>
      {/if}
      {#if failure}<p class="text-sm text-danger" data-testid="missing-image-error">{failure}</p>{/if}
    {/if}
  </div>
  {#if build?.state === "succeeded"}
    <Button onclick={onstart} data-testid="missing-image-start"><Play />Start</Button>
  {:else if !preparing}
    <Button onclick={prepare} data-testid="missing-image-prepare"><Hammer />{build ? "Try again" : "Prepare now"}</Button>
  {/if}
</div>
{#if error}
  <details class="text-xs text-muted-foreground">
    <summary class="cursor-pointer">Details</summary>
    <pre class="mt-1 whitespace-pre-wrap [overflow-wrap:anywhere]" data-testid="error">{error}</pre>
  </details>
{/if}
