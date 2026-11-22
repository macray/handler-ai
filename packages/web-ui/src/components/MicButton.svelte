<script lang="ts">
  // Push to talk (D.25): one click records, the next stops and writes it down (Esc drops it); what
  // was heard goes to `onheard`. Voice off (no speech model, or no microphone here), it leads to
  // Settings → Voice instead. Ask sends what was heard; a nudge's form is filled with it (H.17).
  // The recording is bound out, for the place to say it listens and for how long.
  import Mic from "@lucide/svelte/icons/mic";
  import { Button } from "$lib/components/ui/button";
  import { api } from "../lib/api";
  import { href } from "../lib/router.svelte";
  import { record, type Recording } from "../lib/voice";

  let {
    listens,
    disabled = false,
    recording = $bindable(null),
    hearing = $bindable(false),
    stopLabel = "stop and send",
    onheard,
    onerror,
    testid,
  }: {
    listens: boolean;
    disabled?: boolean;
    recording?: Recording | null;
    hearing?: boolean;
    stopLabel?: string;
    onheard: (text: string) => void | Promise<void>;
    onerror: (message: string) => void;
    testid: string;
  } = $props();

  $effect(() => {
    if (!recording) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && cancel();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  });

  async function start(): Promise<void> {
    try {
      recording = await record(() => void stop());
    } catch (e) {
      onerror(`The microphone: ${(e as Error).message}`);
    }
  }

  function cancel(): void {
    recording?.cancel();
    recording = null;
  }

  async function stop(): Promise<void> {
    const r = recording;
    if (!r) return;
    recording = null;
    hearing = true;
    try {
      const speech = await r.stop();
      const heard = speech ? (await api.transcribe(speech)).text : "";
      if (heard) await onheard(heard);
    } catch (e) {
      onerror(`Nothing was written down: ${(e as Error).message}`);
    } finally {
      hearing = false;
    }
  }
</script>

{#if listens}
  <Button
    type="button"
    size="icon"
    variant={recording ? "destructive" : "outline"}
    class="rounded-full"
    disabled={disabled || hearing}
    aria-label={recording ? stopLabel : "speak"}
    onclick={() => (recording ? stop() : start())}
    data-testid={testid}><Mic /></Button
  >
{:else}
  <a
    class="flex size-9 items-center justify-center rounded-full text-muted-foreground/60 ring-1 ring-border hover:text-foreground"
    href={href({ view: "settings", section: "voice" })}
    title="Speak instead of typing: Settings → Voice"
    aria-label="set up speaking"
    data-testid={`${testid}-setup`}><Mic class="size-4" /></a
  >
{/if}
