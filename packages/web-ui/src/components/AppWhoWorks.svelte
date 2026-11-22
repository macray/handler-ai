<script lang="ts">
  // Who works for an app's jobs, or for one of them (H.2): the one Who works control
  // (WhoWorksChoice, in its own mode) on a WhoWorks instead of an agent's model: a program on an
  // account or a provider, and a model; or the model alone, on a provider (the program's menu
  // swaps them). Each pick is `onchange`'s; `limits` greys what cannot do the work, with why;
  // `unattended`: an automation runs it (on a subscription, the line recommending an API key).
  import { untrack } from "svelte";
  import type { ModelAccess, WhoWorks } from "../lib/contracts.gen";
  import type { Limits } from "../lib/whoworks";
  import WhoWorksChoice from "./WhoWorksChoice.svelte";

  let {
    name,
    value,
    limits,
    unattended = false,
    onchange,
  }: {
    name: string; // what works: the app's title, or the job's description
    value: WhoWorks | null | undefined;
    limits?: Limits;
    unattended?: boolean;
    onchange: (who: WhoWorks) => void;
  } = $props();

  // the one shown: what was given, then each pick (the control follows the model it is given)
  let current = $state(untrack(() => value ?? null));
  let alone = $state(untrack(() => !!value && !value.program));

  const agent = $derived({
    id: "",
    name,
    model: { harness: current?.program ?? null, account: current?.account ?? null, provider: current?.provider ?? null, model: current?.model ?? null },
    area: null,
    modelAlone: alone,
  });

  function picked(m: ModelAccess): void {
    const who: WhoWorks = m.harness
      ? { program: m.harness, ...(m.account ? { account: m.account } : { provider: m.provider }), ...(m.model ? { model: m.model } : {}) }
      : { provider: m.provider, ...(m.model ? { model: m.model } : {}) };
    current = who;
    onchange(who);
  }
</script>

<WhoWorksChoice {agent} own {unattended} {limits} onchange={picked} onalone={(a) => (alone = a)} />
