<script lang="ts">
  // What comes in and what goes out of a brief or a job (D.18), on one line: its form's fields,
  // then its result's (a job's). Nothing for a chat.
  import type { AgentInterface } from "../lib/contracts.gen";
  import { fieldsOf, type Field, type Schema } from "../lib/runs";
  import ArrowRight from "@lucide/svelte/icons/arrow-right";

  let { iface }: { iface: AgentInterface | null | undefined } = $props();

  const KIND: Record<Field["kind"], string> = {
    text: "text",
    "long-text": "text",
    skill: "skill",
    number: "number",
    boolean: "yes/no",
    choice: "choice",
    list: "list",
    json: "data",
  };
  const ins = $derived(fieldsOf(iface?.fields as Schema | undefined));
  const outs = $derived(fieldsOf(iface?.result as Schema | undefined));
</script>

{#if iface}
  <div class="flex flex-wrap items-center gap-1.5 rounded-lg border bg-muted px-3 py-2 text-xs" data-testid="interface-strip">
    <span class="section-label">in</span>
    {#each ins as f (f.key)}
      <span class="rounded-md border bg-card px-1.5 py-0.5">{f.title} <span class="fact text-muted-foreground">{f.choices.length ? f.choices.join(" · ") : KIND[f.kind]}</span></span>
    {:else}
      <span class="text-muted-foreground">nothing</span>
    {/each}
    {#if iface.result}
      <ArrowRight class="size-3.5 text-muted-foreground" />
      <span class="section-label">out</span>
      {#each outs as f (f.key)}
        <span class="rounded-md border bg-card px-1.5 py-0.5">{f.title} <span class="fact text-muted-foreground">{f.choices.length ? f.choices.join(" · ") : KIND[f.kind]}</span></span>
      {/each}
    {/if}
  </div>
{/if}
