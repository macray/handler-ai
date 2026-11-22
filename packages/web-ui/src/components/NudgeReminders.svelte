<script lang="ts">
  // How a nudge of an app alerts you (H.17), chosen directly: "Reminders: As the app says ▾"
  // opens the three choices, each with what it means for this nudge ("reminds you every day, 2
  // times"). It holds for that nudge's next ones; the same on an open nudge in the inbox and on
  // the app's page.
  import Bell from "@lucide/svelte/icons/bell";
  import Check from "@lucide/svelte/icons/check";
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import { Button } from "$lib/components/ui/button";
  import Popover from "./Popover.svelte";
  import { SETTING_WORDS, SETTINGS, settingMeaning, type NudgeSetting } from "../lib/nudges";
  import type { AppManifestNudgeRemind } from "../lib/contracts.gen";

  let {
    setting,
    remind,
    disabled = false,
    onchange,
  }: { setting: NudgeSetting; remind?: AppManifestNudgeRemind | null; disabled?: boolean; onchange: (to: NudgeSetting) => void } = $props();

  let open = $state(false);
</script>

<Popover bind:open align="end" label="Reminders" width="17rem" testid="nudge-reminders-menu">
  {#snippet trigger(props)}
    <Button size="xs" variant="outline" {disabled} {...props} data-testid="nudge-reminders"
      ><Bell />Reminders: <span class="font-medium" data-testid="nudge-setting">{SETTING_WORDS[setting]}</span><ChevronDown /></Button
    >
  {/snippet}
  {#snippet children(close)}
    <p class="px-2 pt-1 pb-1.5 text-xs text-muted-foreground">After it comes, Handler reminds you</p>
    {#each SETTINGS as s (s)}
      <button
        type="button"
        class="menu-item items-start"
        role="menuitemradio"
        aria-checked={s === setting}
        onclick={() => (close(), s !== setting && onchange(s))}
        data-testid="nudge-setting-{s}"
      >
        <span class="mt-0.5 w-4 shrink-0">{#if s === setting}<Check class="size-4 text-primary" />{/if}</span>
        <span class="min-w-0 text-left">
          <span class="block">{SETTING_WORDS[s]}</span>
          <span class="block text-xs text-muted-foreground">{settingMeaning(s, remind)}</span>
        </span>
      </button>
    {/each}
  {/snippet}
</Popover>
