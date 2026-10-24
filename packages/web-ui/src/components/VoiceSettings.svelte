<script lang="ts">
  // Settings → Voice (D.25): what writes down what you say to Ask, here and on your phone (one of
  // your providers' speech models, the transcribe service: a vendor's API or a server on this
  // computer), or off; where the sound goes, said; and when answers are read aloud (by the device
  // itself: nothing is sent for that). No speech model yet: how to get one.
  import { Checkbox } from "$lib/components/ui/checkbox";
  import { Button } from "$lib/components/ui/button";
  import { api } from "../lib/api";
  import type { Voice } from "../lib/contracts.gen";
  import { href } from "../lib/router.svelte";

  let voice = $state<Voice | null>(null);
  let error = $state<string | null>(null);

  $effect(() => {
    api.voice().then(
      (v) => (voice = v),
      (e: Error) => (error = e.message),
    );
  });

  const chosen = $derived(voice?.models.find((m) => m.model === voice?.model));

  async function save(change: Partial<Voice>): Promise<void> {
    if (!voice) return;
    const next = { ...voice, ...change };
    try {
      voice = await api.setVoice({ model: next.model ?? null, readAloudSpoken: next.readAloudSpoken, readAloudTyped: next.readAloudTyped });
      error = null;
    } catch (e) {
      error = (e as Error).message;
    }
  }
</script>

<section class="max-w-3xl space-y-8" data-testid="voice">
  <p class="text-sm text-muted-foreground">Speak to Ask, here or on your phone, instead of typing. Nothing listens until you press the microphone, and Handler keeps neither the sound nor its text.</p>
  {#if error}<p class="text-sm text-danger">{error}</p>{/if}

  <div class="space-y-2">
    <h2 class="flex items-baseline gap-2 font-semibold">What writes down what you say <span class="text-xs font-normal text-muted-foreground">a model that turns speech into text</span></h2>
    {#if voice && !voice.models.length}
      <div class="space-y-2 rounded-[10px] border bg-card px-4 py-3.5 text-sm shadow-panel" data-testid="voice-none">
        <p>None of your providers turns speech into text yet.</p>
        <p class="text-muted-foreground">
          A provider can when its server writes down speech (the OpenAI <span class="font-mono text-xs">/audio/transcriptions</span> endpoint): Mistral (Voxtral), OpenAI, Groq, or a server on this
          computer (vLLM, whisper.cpp, speaches). Add one from its template, or add the endpoint and a speech model to one you have. Your subscriptions can't: they are used through their own apps only.
        </p>
        <Button size="sm" variant="outline" href={href({ view: "settings", section: "models" })}>Model access</Button>
      </div>
    {:else if voice}
      <div class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel" role="radiogroup" aria-label="speech model">
        {#each voice.models as m (m.model)}
          <label class="flex cursor-pointer items-center gap-3 px-4 py-3" data-testid="voice-model">
            <input type="radio" name="voice-model" class="accent-primary" checked={voice.model === m.model} onchange={() => save({ model: m.model })} />
            <span class="flex-1"><span class="font-medium">{m.name}</span><span class="block text-xs text-muted-foreground">{m.provider} · {m.local ? "on this computer: what you say does not leave it" : "the provider's servers"}</span></span>
          </label>
        {/each}
        <label class="flex cursor-pointer items-center gap-3 px-4 py-3 text-muted-foreground">
          <input type="radio" name="voice-model" class="accent-primary" checked={!voice.model} onchange={() => save({ model: null })} data-testid="voice-off" />
          Off: no microphone anywhere
        </label>
      </div>
      {#if voice.problem}<p class="text-sm text-danger" data-testid="voice-problem">{voice.model}: {voice.problem}</p>{/if}
      {#if chosen && !chosen.local}
        <p class="text-xs text-muted-foreground" data-testid="voice-where">What you say is sent to {chosen.provider} to be written down, then goes through Ask as if typed.</p>
      {/if}
    {/if}
  </div>

  {#if voice}
    <div class="space-y-2">
      <h2 class="font-semibold">Answers read aloud</h2>
      <p class="text-xs text-muted-foreground">In your device's own voice: nothing is sent anywhere.</p>
      <div class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
        <label class="flex items-center gap-3 px-4 py-3"><Checkbox checked={voice.readAloudSpoken} onCheckedChange={(v) => save({ readAloudSpoken: v === true })} data-testid="voice-read-spoken" />When you spoke</label>
        <label class="flex items-center gap-3 px-4 py-3"><Checkbox checked={voice.readAloudTyped} onCheckedChange={(v) => save({ readAloudTyped: v === true })} />When you typed</label>
      </div>
    </div>
  {/if}
</section>
