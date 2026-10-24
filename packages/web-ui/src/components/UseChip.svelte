<script lang="ts" module>
  import ClipboardList from "@lucide/svelte/icons/clipboard-list";
  import MessageSquare from "@lucide/svelte/icons/message-square";
  import NotebookPen from "@lucide/svelte/icons/notebook-pen";
  import type { Use } from "../lib/interface";

  /** Each use's icon, the editor's card's: also an agent's icon in a list. */
  export const USE_ICON: Record<Use, typeof MessageSquare> = { chat: MessageSquare, brief: NotebookPen, job: ClipboardList };
</script>

<script lang="ts">
  // How an agent is used (D.18), the same chip wherever it is shown: Chat, Brief or Job.
  import { USE_LABEL } from "../lib/interface";

  let { use }: { use: Use } = $props();

  const Icon = $derived(USE_ICON[use]);
</script>

<span class="inline-flex items-center gap-1 rounded-[5px] border px-1.5 py-px text-xs font-medium text-foreground/80" data-testid="agent-use"
  ><Icon class="size-3 text-muted-foreground" />{USE_LABEL[use]}</span
>
