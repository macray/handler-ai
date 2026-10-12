<script lang="ts">
  // Lines of a run's subject (D.18): read by handlerd from the skill as it is now, not quoted by the
  // agent, so what you read is what is there.
  import { api } from "../lib/api";

  let { skill, path, from, to }: { skill: string; path: string; from: number; to: number } = $props();

  let lines = $state<string[] | null>(null);
  let error = $state<string | null>(null);

  $effect(() => {
    api.skillFile(skill, path).then(
      (f) => {
        if (f.text === undefined || f.text === null) error = "a binary file";
        else lines = f.text.split("\n").slice(from - 1, to);
      },
      (e: Error) => (error = e.message),
    );
  });
</script>

<figure class="overflow-hidden rounded-md border text-xs" data-testid="code-ref">
  <figcaption class="border-b bg-muted px-2 py-1 font-mono text-muted-foreground">{path}:{from}{to > from ? `–${to}` : ""}</figcaption>
  {#if error}
    <p class="px-2 py-1 text-danger">{error}</p>
  {:else if lines}
    <pre class="overflow-x-auto px-2 py-1 leading-relaxed"><code
        >{#each lines as line, i (i)}<span class="mr-3 inline-block w-8 text-right text-muted-foreground select-none">{from + i}</span
          >{line}{"\n"}{/each}</code
      ></pre>
    {#if lines.length < to - from + 1}<p class="px-2 pb-1 text-muted-foreground">(the file is shorter now)</p>{/if}
  {:else}
    <p class="px-2 py-1 text-muted-foreground">Loading…</p>
  {/if}
</figure>
