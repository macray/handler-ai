<script lang="ts">
  // A run's result (D.18), shown from its interface's `result` schema: objects as titled fields,
  // lists as lists, enums marked "verdict" as badges, code references as the lines they point at.
  // What the schema does not describe is shown as JSON.
  import OutputView from "./OutputView.svelte";
  import CodeRef from "./CodeRef.svelte";
  import { codeRef, properties, titleOf, toneOf, type Schema, type Tone } from "../lib/runs";

  let { schema, value, skill }: { schema: Schema | undefined; value: unknown; skill?: string } = $props();

  const TONE: Record<Tone, string> = {
    ok: "border-ok/40 bg-ok/10 text-ok",
    warn: "border-warn/40 bg-warn/10 text-warn",
    danger: "border-danger/40 bg-danger/10 text-danger",
    muted: "border-border bg-muted text-muted-foreground",
  };

  const s = $derived(schema ?? {});
  const ref = $derived(s["x-handler"] === "code-ref" ? codeRef(value) : null);
  const items = $derived((s.items as Schema | undefined) ?? undefined);
  const known = $derived(properties(s).map(([k]) => k));
  const extra = $derived(
    value && typeof value === "object" && !Array.isArray(value) ? Object.keys(value).filter((k) => !known.includes(k)) : [],
  );
</script>

{#if ref && skill}
  <CodeRef {skill} path={ref.path} from={ref.from} to={ref.to} />
{:else if ref}
  <code class="text-xs">{ref.path}:{ref.from}–{ref.to}</code>
{:else if s["x-handler"] === "verdict" && typeof value === "string"}
  <span class="inline-flex rounded-md border px-2 py-0.5 text-xs font-medium {TONE[toneOf(s, value)]}" data-testid="verdict">{value}</span>
{:else if Array.isArray(value)}
  {#if value.length === 0}
    <p class="text-sm text-muted-foreground">None.</p>
  {:else if value.every((v) => v === null || typeof v !== "object")}
    <ul class="list-disc space-y-0.5 pl-5 text-sm">
      {#each value as item, i (i)}<li><OutputView schema={items} value={item} {skill} /></li>{/each}
    </ul>
  {:else}
    <div class="space-y-3">
      {#each value as item, i (i)}
        <div class="rounded-lg border bg-card p-3"><OutputView schema={items} value={item} {skill} /></div>
      {/each}
    </div>
  {/if}
{:else if value && typeof value === "object"}
  <dl class="space-y-3">
    {#each properties(s) as [key, sub] (key)}
      {@const v = (value as Record<string, unknown>)[key]}
      {#if v !== undefined && v !== null}
        <div class="space-y-1">
          <dt class="text-xs font-medium text-muted-foreground">{titleOf(key, sub)}</dt>
          <dd><OutputView schema={sub} value={v} {skill} /></dd>
        </div>
      {/if}
    {/each}
    {#each extra as key (key)}
      <div class="space-y-1">
        <dt class="text-xs font-medium text-muted-foreground">{titleOf(key, {})}</dt>
        <dd><OutputView schema={undefined} value={(value as Record<string, unknown>)[key]} {skill} /></dd>
      </div>
    {/each}
  </dl>
{:else if typeof value === "string"}
  <p class="text-sm whitespace-pre-wrap">{value}</p>
{:else if value === undefined || value === null}
  <p class="text-sm text-muted-foreground">—</p>
{:else}
  <span class="text-sm">{String(value)}</span>
{/if}
