<script lang="ts">
  // One agent, of a project or outside projects: with an interface (D.18), a run's form, the
  // automations that run it and its runs; without, a request to start a session with (a
  // folderless one may start from a copy of a skill, to improve it), and its sessions. Its
  // settings are its project's agent editor or, outside projects, the ad-hoc one (with Delete).
  import When from "../components/When.svelte";
  import Pencil from "@lucide/svelte/icons/pencil";
  import Play from "@lucide/svelte/icons/play";
  import Trash from "@lucide/svelte/icons/trash-2";
  import { Button } from "$lib/components/ui/button";
  import { Label } from "$lib/components/ui/label";
  import * as NativeSelect from "$lib/components/ui/native-select";
  import { Textarea } from "$lib/components/ui/textarea";
  import * as Table from "$lib/components/ui/table";
  import PageHeader from "../components/PageHeader.svelte";
  import PageTitle from "../components/PageTitle.svelte";
  import AgentSchedules from "../components/AgentSchedules.svelte";
  import RunForm from "../components/RunForm.svelte";
  import RunList from "../components/RunList.svelte";
  import { accessLabel } from "../lib/access";
  import ModelChoice from "../components/ModelChoice.svelte";
  import { whereLabel } from "../lib/agents";
  import LiveList from "../components/LiveList.svelte";
  import { api } from "../lib/api";
  import type { Agent, AutomationView, ModelAccess, Session, SkillInfo } from "../lib/contracts.gen";
  import { agentLabel, projects } from "../lib/projects.svelte";
  import { href, navigate } from "../lib/router.svelte";
  import { runState } from "../lib/runs";
  import { sessions } from "../lib/sessions.svelte";

  let { id }: { id: string } = $props();

  let agent = $state<Agent | null>(null);
  let list = $state<Session[]>([]);
  let skills = $state<SkillInfo[]>([]);
  let request = $state("");
  let fromSkill = $state("");
  let model = $state<ModelAccess | undefined>(); // undefined: its first (D.1)
  let error = $state<string | null>(null);
  let automations = $state<AutomationView[]>([]);

  const project = $derived(agent ? projects.get(agent.projectId) : undefined);
  const settings = $derived(
    agent ? (agent.projectId ? href({ view: "edit-agent", project: agent.projectId, id: agent.id }) : href({ view: "edit-ad-hoc", id: agent.id })) : "",
  );

  const runs = $derived(list.filter((s) => s.input));
  const chats = $derived(list.filter((s) => !s.input));
  const running = $derived(runs.some((r) => runState(r) === "running"));

  async function refresh(): Promise<void> {
    try {
      [agent, list] = await Promise.all([api.agent(id), api.agentSessions(id)]);
    } catch (e) {
      error = (e as Error).message;
    }
  }

  $effect(() => {
    void refresh();
    api.skills().then(
      (all) => (skills = all.filter((s) => !s.error)),
      () => (skills = []),
    );
    api.automations().then(
      (list) => (automations = list),
      () => (automations = []),
    );
  });

  $effect(() => {
    const timer = setInterval(refresh, running ? 2000 : 5000); // also shows terminals come and go
    return () => clearInterval(timer);
  });

  async function start(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (!agent) return;
    error = null;
    try {
      const runs = model;
      const session = fromSkill
        ? sessions.open(await api.createSessionFromSkill(agent.id, fromSkill, runs), agent)
        : await sessions.start(agent, undefined, request.trim() || undefined, runs);
      navigate({ view: "session", key: session.key });
    } catch (e) {
      error = (e as Error).message;
    }
  }

  async function remove(): Promise<void> {
    if (!agent || !confirm(`Delete the agent ${agentLabel(agent)}? Its running sessions are stopped.`)) return;
    try {
      await api.deleteAdHocAgent(agent.id);
      navigate({ view: "agents" }, true);
    } catch (e) {
      error = (e as Error).message;
    }
  }
</script>

<PageHeader
  title={agent ? agentLabel(agent) : "Agent"}
  parent={project ? { label: project.name, href: href({ view: "project", id: project.id }) } : { label: "Agents", href: href({ view: "agents" }) }}
  titled
>
  {#snippet actions()}
    {#if agent}
      <Button variant="ghost" size="sm" href={settings} data-testid="agent-edit"><Pencil />Settings</Button>
      {#if !agent.projectId}
        <Button variant="ghost" size="sm" class="text-destructive hover:text-destructive" onclick={remove} data-testid="agent-delete"><Trash />Delete</Button>
      {/if}
    {/if}
  {/snippet}
</PageHeader>
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-4xl space-y-10 px-8 py-10">
    {#if agent}
      <PageTitle title={agentLabel(agent)} description={agent.description ?? ""} />
      <p class="text-xs text-muted-foreground">{agent.models.map(accessLabel).join(" | ")} · works in {agent.scope ? agent.scope : "a folder per session"}</p>
      {#if agent.interface}
        <div class="flex flex-wrap items-center gap-1.5">
          <AgentSchedules {automations} name={agent.name} project={project?.name ?? null} />
          <Button variant="ghost" size="sm" href={agent.name ? href({ view: "edit-automation", agent: agent.id }) : undefined} disabled={!agent.name} data-testid="agent-page-schedule">
            Run it on a schedule…
          </Button>
        </div>
      {/if}
      {#each agent.models.filter((m) => m.problem) as m (accessLabel(m))}
        <p class="text-sm text-danger">It cannot start with {accessLabel(m)} now: {m.problem}</p>
      {/each}
    {/if}
    {#if error}<p class="text-sm text-danger">{error}</p>{/if}

    {#if agent?.interface}
      <section class="space-y-3">
        <h2 class="text-base font-semibold">New run</h2>
        <div class="rounded-lg border bg-card p-4">
          <RunForm {agent} onstarted={(run) => navigate({ view: "run", id: run.id })} />
        </div>
      </section>
      <section class="space-y-3">
        <h2 class="text-base font-semibold">Runs</h2>
        <RunList {runs} agents={[agent]} />
      </section>
    {:else if agent}
      <section class="space-y-3">
        <h2 class="text-base font-semibold">New session</h2>
        <form class="space-y-3 rounded-lg border bg-card p-4" onsubmit={start}>
          {#if !agent.scope}
            <div class="space-y-1.5">
              <Label for="from-skill">Its folder</Label>
              <NativeSelect.Root id="from-skill" bind:value={fromSkill} class="w-full" data-testid="from-skill">
                <NativeSelect.Option value="">Empty</NativeSelect.Option>
                {#each skills as s (s.name)}<NativeSelect.Option value={s.name}>A copy of the skill {s.name}</NativeSelect.Option>{/each}
              </NativeSelect.Root>
            </div>
          {/if}
          <Textarea bind:value={request} rows={3} placeholder="What should it do? (optional: you can also start empty)" disabled={!!fromSkill} data-testid="ad-hoc-request" />
          <div class="flex flex-wrap items-center gap-3">
            <Button type="submit" data-testid="ad-hoc-start"><Play />Start</Button>
            <ModelChoice {agent} bind:value={model} />
          </div>
        </form>
      </section>
    {/if}

    {#if agent}<LiveList agents={[agent]} list={[]} />{/if}

    {#if agent && chats.length}
      <section class="space-y-3">
        <h2 class="text-base font-semibold">Sessions</h2>
        <div class="overflow-hidden rounded-lg border bg-card">
          <Table.Root>
            <Table.Body>
              {#each chats as s (s.id)}
                <Table.Row>
                  <Table.Cell><a href={href({ view: "session", key: s.id })}>{s.title ?? "untitled"}</a></Table.Cell>
                  <Table.Cell class="text-muted-foreground">{s.state}</Table.Cell>
                  <Table.Cell class="text-muted-foreground" title={s.scope}>{whereLabel({ scope: agent.scope ? s.scope : null })}</Table.Cell>
                  <Table.Cell class="text-muted-foreground"><When at={s.lastActivityAt} /></Table.Cell>
                </Table.Row>
              {/each}
            </Table.Body>
          </Table.Root>
        </div>
      </section>
    {/if}
  </div>
</div>
