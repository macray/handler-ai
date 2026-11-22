<script lang="ts">
  // Try one of an app's actions (H.12), from its page or from Ask's Not this: its form (the
  // route's, or its agent's), one real run, its answer (ActionForm).
  import Play from "@lucide/svelte/icons/play";
  import type { AppAction } from "../lib/contracts.gen";
  import { fieldsOf, formValues, type Schema } from "../lib/runs";
  import ActionForm from "./ActionForm.svelte";

  let { app, action, initial = {} }: { app: string; action: AppAction; initial?: Record<string, unknown> } = $props();

  // the props give the initial values only (Ask's Not this: what the router had filled)
  // svelte-ignore state_referenced_locally
  let values = $state<Record<string, unknown>>(formValues(fieldsOf(action.fields as Schema | undefined), initial));
</script>

<ActionForm
  {app}
  action={action.name}
  schema={action.fields as Schema | undefined}
  bind:values
  label="Run"
  again="Run again"
  icon={Play}
  note={`One real run, as if you asked it: ${action.by === "code" ? "its code answers at once" : action.by === "job" ? "one of its jobs works on it, which may take a while" : "its agent works on it, which may take a while"}.`}
/>
