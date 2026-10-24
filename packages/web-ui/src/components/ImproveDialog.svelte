<script lang="ts">
  // Improve a job until its checks pass (D.21): what to improve (the person's words, given to the
  // prompt writer), how many attempts and minutes at most. Without a prompt writer, the way to set
  // one up (D.18: where it is needed). With few checks, a warning: an attempt may learn them, not
  // the rule.
  import { api } from "../lib/api";
  import type { Improvement } from "../lib/contracts.gen";
  import { href } from "../lib/router.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import { Textarea } from "$lib/components/ui/textarea";
  import Dialog from "./Dialog.svelte";

  let { open = $bindable(false), agentId, checks, onstarted }: { open: boolean; agentId: string; checks: number; onstarted: (i: Improvement) => void } = $props();

  let goal = $state("");
  let attempts = $state(5);
  let minutes = $state(15);
  let writer = $state<string | false | null>(null); // the prompt writer given (its id); null: not known yet
  let busy = $state(false);
  let error = $state<string | null>(null);

  $effect(() => {
    if (!open) return;
    api.handlerNeeds().then(
      (list) => (writer = list.find((b) => b.name === "prompt-writer")?.agentId ?? false),
      () => (writer = null),
    );
  });

  async function start(): Promise<void> {
    busy = true;
    error = null;
    try {
      const started = await api.improve(agentId, goal.trim(), attempts, minutes);
      open = false;
      onstarted(started);
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

<Dialog bind:open title="Improve until its checks pass" description="The prompt writer rewrites its instructions, its checks judge each attempt. Nothing changes until you keep one." testid="improve-dialog">
  {#if writer === false}
    <div class="space-y-2" data-testid="improve-no-writer">
      <p>Improving needs a <span class="font-medium">prompt writer</span>: an agent on the model alone that rewrites instructions. Its own instructions are the default prompt; change them as you like.</p>
      <Button href={href({ view: "set-up-helper", need: "prompt-writer" })} data-testid="improve-setup-writer">Set up the prompt writer</Button>
    </div>
  {:else}
    <form
      class="space-y-4"
      onsubmit={(e) => {
        e.preventDefault();
        void start();
      }}
    >
      <div class="space-y-1.5">
        <Label for="improve-goal">What to improve</Label>
        <Textarea id="improve-goal" bind:value={goal} rows={3} placeholder="e.g. It says rewrite for a plain, polite no." data-testid="improve-goal" />
        <p class="text-xs text-muted-foreground">
          The prompt writer reads it with the checks that fail: say where it goes wrong, or what to make clearer.
          {#if writer}<a class="text-link hover:underline" href={href({ view: "edit-ad-hoc", id: writer })}>Change how it writes</a>.{/if}
        </p>
      </div>
      <div class="grid grid-cols-2 gap-3">
        <div class="space-y-1.5">
          <Label for="improve-attempts">Attempts at most</Label>
          <Input id="improve-attempts" type="number" min={1} max={10} bind:value={attempts} />
        </div>
        <div class="space-y-1.5">
          <Label for="improve-minutes">Minutes at most</Label>
          <Input id="improve-minutes" type="number" min={1} max={240} bind:value={minutes} />
        </div>
      </div>
      {#if checks < 4}
        <p class="text-xs text-warn" data-testid="improve-few-checks">
          With {checks} check{checks === 1 ? "" : "s"}, an attempt can learn them rather than the rule: keep a few more runs as checks.
        </p>
      {/if}
      {#if error}<p class="text-sm text-danger">{error}</p>{/if}
      <div class="flex justify-end gap-2">
        <Button type="button" variant="ghost" onclick={() => (open = false)}>Cancel</Button>
        <Button type="submit" disabled={busy || !goal.trim()} data-testid="improve-start">Start</Button>
      </div>
    </form>
  {/if}
</Dialog>
