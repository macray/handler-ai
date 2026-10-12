<script lang="ts">
  import { diffLines } from "diff";

  let { path, oldText, newText }: { path: string; oldText?: string | null; newText: string } = $props();

  const parts = $derived(diffLines(oldText ?? "", newText));
</script>

<div class="diff">
  <div class="path">{oldText == null ? "new file: " : ""}{path}</div>
  <pre>{#each parts as part, i (i)}<span class:add={part.added} class:del={part.removed}
        >{part.value}</span
      >{/each}</pre>
</div>

<style>
  .path {
    font-family: var(--mono);
    font-size: 0.8rem;
    color: var(--muted-foreground);
    margin-bottom: 0.25rem;
  }
  pre {
    max-height: 24rem;
    overflow: auto;
  }
  .add {
    background: var(--diff-add);
    display: block;
  }
  .del {
    background: var(--diff-del);
    display: block;
    text-decoration: line-through;
    opacity: 0.8;
  }
</style>
