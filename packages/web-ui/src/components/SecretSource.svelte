<script lang="ts">
  // Where a secret comes from (E2): pasted here (handler keeps it in its secret store), or where the
  // person keeps it: an environment variable of handlerd, a file (its first line), a command printing
  // it (`pass show claude-pro`). `given()` gives what the Control API takes. Pasting is the
  // usual way: the other three are folded behind "Keep it elsewhere…" until one is chosen.
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import { Input } from "$lib/components/ui/input";
  import * as NativeSelect from "$lib/components/ui/native-select";

  let { source = $bindable(), placeholder = "paste it" }: { source: Source; placeholder?: string } = $props();

  let elsewhere = $state(false);
  const hints = $derived({
    secret: placeholder,
    env: "variable name, e.g. CLAUDE_TOKEN (handlerd's environment)",
    file: "absolute path; its first line is used",
    command: "e.g. pass show claude-pro (words separated by spaces)",
  });
</script>

<script lang="ts" module>
  import type { CommandSecret, EnvSecret, FileSecret } from "../lib/contracts.gen";

  export type Source = { kind: "secret" | "env" | "file" | "command"; text: string };

  /** What the Control API takes: the value, or a reference to where it is kept. */
  export function given(source: Source): { value: string } | { ref: EnvSecret | FileSecret | CommandSecret } {
    const text = source.text.trim();
    if (source.kind === "env") return { ref: { env: text } };
    if (source.kind === "file") return { ref: { file: text } };
    if (source.kind === "command") {
      const [first = "", ...rest] = text.split(/\s+/);
      return { ref: { command: [first, ...rest] } };
    }
    return { value: text };
  }
</script>

<div class="space-y-2" data-testid="secret-source">
  <div class="flex flex-wrap gap-2">
    {#if elsewhere}
      <NativeSelect.Root class="w-44" bind:value={source.kind} data-testid="secret-source-kind">
        <NativeSelect.Option value="secret">Paste it</NativeSelect.Option>
        <NativeSelect.Option value="env">Environment variable</NativeSelect.Option>
        <NativeSelect.Option value="file">File</NativeSelect.Option>
        <NativeSelect.Option value="command">Command</NativeSelect.Option>
      </NativeSelect.Root>
    {/if}
    <Input
      class="min-w-40 flex-1 {source.kind === 'secret' ? '' : 'font-mono'}"
      type={source.kind === "secret" ? "password" : "text"}
      placeholder={hints[source.kind]}
      bind:value={source.text}
      data-testid="secret-source-text"
    />
  </div>
  {#if !elsewhere}
    <button
      type="button"
      class="flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground"
      onclick={() => (elsewhere = true)}
      data-testid="secret-source-elsewhere"
      ><ChevronRight class="size-3.5" />Keep it elsewhere: an environment variable, a file, a command</button
    >
  {/if}
</div>
