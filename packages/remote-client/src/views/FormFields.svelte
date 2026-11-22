<script lang="ts">
  // A form's inputs, drawn from its JSON Schema's fields (`fieldsOf`): a nudge's action, an
  // agent's form (D.18). The values are as typed; `fieldValues` makes them what is sent.
  import type { Field } from "../lib/nudges";

  let { fields, values = $bindable(), testid }: { fields: Field[]; values: Record<string, unknown>; testid: string } = $props();
</script>

{#each fields as f (f.key)}
  {#if f.kind === "boolean"}
    <label class="check"><input type="checkbox" bind:checked={values[f.key] as boolean} data-testid={`${testid}-${f.key}`} />{f.title}</label>
  {:else}
    <label class="field">
      <span>{f.title}{f.required ? "" : " (optional)"}</span>
      {#if f.kind === "choice"}
        <select bind:value={values[f.key]} required={f.required} data-testid={`${testid}-${f.key}`}>
          <option value="">—</option>
          {#each f.choices as c (c)}<option value={c}>{c}</option>{/each}
        </select>
      {:else if f.kind === "number"}
        <input type="text" inputmode="decimal" bind:value={values[f.key]} required={f.required} data-testid={`${testid}-${f.key}`} />
      {:else if f.kind === "text"}
        <input type="text" bind:value={values[f.key]} required={f.required} data-testid={`${testid}-${f.key}`} />
      {:else}
        <textarea
          bind:value={values[f.key]}
          rows={f.kind === "long-text" ? 4 : 3}
          class:mono={f.kind === "json"}
          placeholder={f.kind === "json" ? "JSON" : f.kind === "list" ? "One per line" : ""}
          required={f.required}
          data-testid={`${testid}-${f.key}`}
        ></textarea>
      {/if}
    </label>
  {/if}
  {#if f.description}<p class="hint">{f.description}</p>{/if}
{/each}

<style>
  .hint {
    color: var(--muted-foreground);
    font-size: 0.85em;
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    font-size: 0.85em;
    font-weight: 500;
  }
  .field input,
  .field select,
  .field textarea {
    font: inherit;
    font-size: 1rem;
    font-weight: 400;
    color: inherit;
    background: var(--background);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 0.5rem 0.6rem;
    min-height: 44px;
  }
  .field textarea {
    resize: vertical;
  }
  .mono {
    font-family: "JetBrains Mono", ui-monospace, monospace;
    font-size: 0.85em;
  }
  .check {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    min-height: 44px;
  }
  .check input {
    width: 1.2rem;
    height: 1.2rem;
  }
</style>
