<script lang="ts">
  // A skill's trust panel (D.17, D.18): what handlerd's scan found in its files (no model involved),
  // its reviews (runs of the skill reviewer Handler uses, D.18, or of your agents whose interface takes
  // a skill), and Edit with an agent (a session of the skill creator Handler uses starting as a copy of
  // it, saved back from there).
  import { Button } from "$lib/components/ui/button";
  import * as NativeSelect from "$lib/components/ui/native-select";
  import HelperCard from "./HelperCard.svelte";
  import RunForm from "./RunForm.svelte";
  import RunList from "./RunList.svelte";
  import { api } from "../lib/api";
  import type { Agent, Session, SkillInfo } from "../lib/contracts.gen";
  import { agentLabel } from "../lib/projects.svelte";
  import { href, navigate } from "../lib/router.svelte";
  import { runState, skillField } from "../lib/runs";
  import { sessions } from "../lib/sessions.svelte";

  let { skill }: { skill: SkillInfo } = $props();

  let agents = $state<Agent[]>([]);
  let runs = $state<Session[]>([]);
  let reviewer = $state("");
  let error = $state<string | null>(null);
  let given = $state<Record<string, string>>({}); // Handler's need → the agent given (D.18)

  // the one given for the built-in reviewer first
  const reviewers = $derived(
    agents
      .filter((a) => a.interface?.result && skillField(a.interface))
      .sort((a, b) => Number(b.id === given["skill-review"]) - Number(a.id === given["skill-review"])),
  );
  const creator = $derived(agents.find((a) => a.id === given["skill-creator"]));
  const chosen = $derived(reviewers.find((a) => a.id === reviewer));
  const running = $derived(runs.some((r) => runState(r) === "running"));
  const scan = $derived(skill.scan);
  const nothing = $derived(
    scan && !scan.executables?.length && !scan.binaries?.length && !scan.hosts?.length && !scan.hiddenText?.length && !scan.blobs?.length,
  );

  async function refresh(): Promise<void> {
    try {
      const [all, list, needs] = await Promise.all([api.agents(), api.skillRuns(skill.name), api.handlerNeeds()]);
      agents = all;
      runs = list;
      given = Object.fromEntries(needs.filter((b) => b.agentId).map((b) => [b.name, b.agentId as string]));
      reviewer ||= reviewers[0]?.id ?? "";
    } catch (e) {
      error = (e as Error).message;
    }
  }

  $effect(() => {
    void refresh();
  });

  $effect(() => {
    if (!running) return;
    const timer = setInterval(refresh, 2000);
    return () => clearInterval(timer);
  });

  async function edit(): Promise<void> {
    const agent = creator;
    if (!agent) return;
    error = null;
    try {
      const session = sessions.open(await api.createSessionFromSkill(agent.id, skill.name), agent);
      navigate({ view: "session", key: session.key });
    } catch (e) {
      error = (e as Error).message;
    }
  }
</script>

<div class="space-y-10 border-t pt-8" data-testid="skill-review">
  <section class="space-y-2" data-testid="skill-scan">
    <h2 class="text-base font-semibold">What Handler found in its files</h2>
    <p class="text-xs text-muted-foreground">Read by Handler itself, no model: a skill cannot talk its way out of it.</p>
    {#if nothing}
      <p class="text-sm">No executable or binary file, no URL, no hidden character, no long encoded blob.</p>
    {:else if scan}
      <ul class="space-y-1 text-sm">
        {#if scan.executables?.length}<li><span class="text-muted-foreground">Runs:</span> <code>{scan.executables.join(", ")}</code></li>{/if}
        {#if scan.binaries?.length}<li><span class="text-muted-foreground">Binary files:</span> <code>{scan.binaries.join(", ")}</code></li>{/if}
        {#if scan.hosts?.length}
          <li>
            <span class="text-muted-foreground">Hosts it names:</span>
            {#each [...new Set(scan.hosts.map((h) => h.text))] as host (host)}<code class="mr-2">{host}</code>{/each}
          </li>
        {/if}
        {#each scan.hiddenText ?? [] as h (h.path + h.line)}
          <li class="text-danger">Hidden characters at <code>{h.path}:{h.line}</code>: <code class="break-all">{h.text}</code></li>
        {/each}
        {#each scan.blobs ?? [] as b (b.path + b.line)}
          <li class="text-warn">A long encoded run at <code>{b.path}:{b.line}</code>: <code>{b.text}</code></li>
        {/each}
      </ul>
    {/if}
  </section>

  <section class="scroll-mt-6 space-y-3" id="skill-reviews">
    <h2 class="text-base font-semibold">Reviews</h2>
    {#if reviewers.length}
      <div class="space-y-4 rounded-lg border bg-card p-4">
        {#if reviewers.length > 1}
          <NativeSelect.Root bind:value={reviewer} class="w-full" data-testid="reviewer">
            {#each reviewers as a (a.id)}<NativeSelect.Option value={a.id}>Review with {agentLabel(a)}</NativeSelect.Option>{/each}
          </NativeSelect.Root>
        {:else}
          <p class="text-sm">Review with <a class="text-link hover:underline" href={href({ view: "agent", id: reviewers[0]!.id })}>{agentLabel(reviewers[0]!)}</a></p>
        {/if}
        {#if chosen}
          {#key chosen.id}<RunForm agent={chosen} skill={skill.name} onstarted={(run) => navigate({ view: "run", id: run.id })} />{/key}
        {/if}
      </div>
    {:else}
      <div data-testid="make-reviewer">
        <HelperCard need="skill-review" onready={() => void refresh()}>
          {#snippet preview()}
            <div class="space-y-1 text-xs">
              <p class="font-medium">Does what it says · runs 1 script · reaches no site</p>
              <p>scripts/check.sh only reads the files it is given.</p>
            </div>
          {/snippet}
        </HelperCard>
      </div>
    {/if}
    {#if runs.length}<RunList {runs} {agents} digest={skill.digest} />{/if}
    <p class="text-xs text-muted-foreground">A review advises: it never allows or blocks anything. Read what it points at.</p>
  </section>

  <section class="space-y-3">
    <h2 class="text-base font-semibold">Edit with an agent</h2>
    {#if creator}
      <div class="flex flex-wrap items-center gap-2">
        <Button size="sm" onclick={edit} data-testid="skill-edit-with-agent">Edit with {agentLabel(creator)}</Button>
      </div>
      <p class="text-xs text-muted-foreground">A session working on a copy of the skill: nothing changes here until you save it back from the session (Save to library, Replace).</p>
    {:else}
      <HelperCard need="skill-creator" onready={() => void refresh()} />
    {/if}
  </section>
  {#if error}<p class="text-sm text-danger">{error}</p>{/if}
</div>
