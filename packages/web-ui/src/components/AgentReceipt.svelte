<script lang="ts">
  // What an agent is, in three blocks (the agent's page, under how it starts): who works (its
  // program or the model alone, its models, how it is used), what it is given (its folder,
  // skills, knowledge, addons), what it may do (its permissions, network, sandbox). Each block
  // leads to the editor. On the model alone (D.18), what it cannot have says why in one line, and
  // what it may do is that it does nothing outside the call, with what is sent to its provider.
  import Bot from "@lucide/svelte/icons/bot";
  import BookOpen from "@lucide/svelte/icons/book-open";
  import Folder from "@lucide/svelte/icons/folder";
  import Globe from "@lucide/svelte/icons/globe";
  import Lock from "@lucide/svelte/icons/lock";
  import Monitor from "@lucide/svelte/icons/monitor";
  import Package from "@lucide/svelte/icons/package";
  import Puzzle from "@lucide/svelte/icons/puzzle";
  import Send from "@lucide/svelte/icons/send";
  import Server from "@lucide/svelte/icons/server";
  import ShieldAlert from "@lucide/svelte/icons/shield-alert";
  import ShieldCheck from "@lucide/svelte/icons/shield-check";
  import Sparkles from "@lucide/svelte/icons/sparkles";
  import Zap from "@lucide/svelte/icons/zap";
  import { programLabel } from "../lib/access";
  import { PERMISSION_LABEL } from "../lib/agents";
  import type { Agent } from "../lib/contracts.gen";
  import { useOfAgent } from "../lib/interface";
  import { USE_ICON } from "./UseChip.svelte";

  let { agent, edit }: { agent: Agent; edit: string } = $props();
  const folder = $derived(agent.scope ?? null); // its project's, its own, or none: one per session

  type Tone = "" | "off" | "warn" | "danger";
  type Line = { icon: typeof Bot; title: string; note: string; tone?: Tone };

  const alone = $derived(agent.modelAlone ?? false);
  const m = $derived(agent.model);
  const use = $derived(useOfAgent(agent));
  const USE_NOTE = { chat: "a chat: you talk with it", brief: "a brief: a form to start, then you work on it together", job: "a job: from its form to its result, alone" };
  const list = (names: string[]) => names.join(", ");

  const who = $derived<Line[]>([
    {
      icon: alone ? Zap : Bot,
      title: programLabel(m),
      note: alone ? "no program: one model call a turn, in seconds" : "an agent program: works on files, runs tools",
    },
    {
      icon: Server,
      title: [m.account ?? m.provider, m.model].filter(Boolean).join(" · "),
      note: m.problem ? `cannot start now: ${m.problem}` : m.account ? "an account: your subscription, for your own use" : "a provider: billed by use, or a local model",
      tone: m.problem ? "danger" : "",
    },
    { icon: USE_ICON[use], title: use === "job" ? "Works alone" : use === "brief" ? "Starts from a form" : "You talk with it", note: USE_NOTE[use] },
  ]);

  const skills = $derived([...(agent.skills ?? []), ...(agent.projectSkills ?? [])]);
  const given = $derived<Line[]>(
    alone
      ? [
          knowledgeLine("put into each call"),
          { icon: Folder, title: "No folder", note: "it reads what its form and the conversation give it", tone: "off" },
          { icon: Sparkles, title: "No skills", note: "a skill can run scripts: it needs an agent program", tone: "off" },
          { icon: Puzzle, title: "No addons", note: "an addon is a tool: it needs an agent program", tone: "off" },
        ]
      : [
          { icon: Folder, title: folder ?? "A new folder each session", note: folder ? "reads and writes" : "kept with its session" },
          skills.length
            ? { icon: Sparkles, title: `${skills.length} skill${skills.length === 1 ? "" : "s"}`, note: list(skills) }
            : { icon: Sparkles, title: "No skills", note: "", tone: "off" },
          knowledgeLine("reads only"),
          agent.bindings?.length
            ? { icon: Puzzle, title: list(agent.bindings), note: "its addons" }
            : { icon: Puzzle, title: "No addons", note: "", tone: "off" },
        ],
  );

  function knowledgeLine(how: string): Line {
    const names = agent.knowledge ?? [];
    return names.length ? { icon: BookOpen, title: `Knowledge: ${list(names)}`, note: how } : { icon: BookOpen, title: "No knowledge", note: "", tone: "off" };
  }

  const hosts = $derived([...(agent.allow ?? []), ...(m.requiredHosts ?? []).map((r) => r.host)]);
  const may = $derived<Line[]>(
    alone
      ? []
      : [
          agent.permissions === "bypass"
            ? {
                icon: ShieldAlert,
                title: "Never asks before acting",
                note: use === "job" ? "a job works alone: its sandbox and its network are all that limit it" : "its sandbox and its network are all that limit it",
                tone: "warn",
              }
            : { icon: ShieldCheck, title: PERMISSION_LABEL[agent.permissions], note: agent.permissions === "ask" ? "you answer each of its requests" : "it edits files without asking; anything else is asked" },
          agent.network === "none"
            ? { icon: Globe, title: "No network", note: "no model API either, unless a local one" }
            : agent.network === "open"
              ? { icon: Globe, title: "Any host", note: "anything on the internet and your LAN", tone: "warn" }
              : agent.egress === "log-only"
                ? { icon: Globe, title: "Every host, logged", note: "log only: learning its hosts", tone: "warn" }
                : { icon: Globe, title: `${hosts.length} host${hosts.length === 1 ? "" : "s"}`, note: hosts.length ? `${list(hosts)} · nothing else` : "nothing else" },
          agent.confinement === "strict"
            ? { icon: Lock, title: "Only its folder", note: "nothing else on your computer; never Handler's own files" }
            : agent.confinement === "nested"
              ? { icon: Lock, title: "Runs containers", note: "podman inside its sandbox: a weaker confinement", tone: "warn" }
              : { icon: Lock, title: "Privileged", note: "about as safe as no sandbox", tone: "danger" },
          ...(agent.display ? [{ icon: Monitor, title: "Your screen and clipboard", note: "it opens windows and reads what you copy", tone: "warn" as Tone }] : []),
        ],
  );
  const sent = $derived(
    `${m.provider ?? "its provider"}: the conversation${use === "chat" ? "" : " (its form's values first)"}${agent.knowledge?.length ? " and its knowledge's notes" : ""}, at each call`,
  );

  const TONE: Record<Tone, string> = { "": "", off: "text-muted-foreground", warn: "text-warn", danger: "text-danger" };
</script>

{#snippet block(title: string, icon: typeof Bot, lines: Line[], testid: string)}
  {@const Icon = icon}
  <section class="overflow-hidden rounded-[10px] border bg-card shadow-panel" data-testid={testid}>
    <h3 class="flex items-center gap-2 border-b px-3.5 py-2.5 text-sm font-semibold">
      <Icon class="size-4 text-muted-foreground" />{title}
      <a class="ml-auto text-xs font-normal text-link hover:underline" href={edit}>Change</a>
    </h3>
    <ul class="divide-y">
      {#each lines as l, i (i)}
        {@const LineIcon = l.icon}
        <li class="grid grid-cols-[1rem_1fr] gap-x-2 px-3.5 py-2 text-sm {TONE[l.tone ?? '']}">
          <LineIcon class="mt-0.5 size-4 {l.tone ? '' : 'text-muted-foreground'}" />
          <span class="min-w-0 font-medium break-words">{l.title}</span>
          {#if l.note}<span class="col-start-2 text-xs break-words {l.tone === 'off' ? '' : 'text-muted-foreground'}">{l.note}</span>{/if}
        </li>
      {/each}
    </ul>
  </section>
{/snippet}

<div class="grid items-start gap-3 xl:grid-cols-3" data-testid="agent-receipt">
  {@render block("Who works", alone ? Zap : Bot, who, "agent-receipt-who")}
  {@render block("What it is given", Package, given, "agent-receipt-given")}
  {#if alone}
    <section class="overflow-hidden rounded-[10px] border bg-card shadow-panel" data-testid="agent-receipt-may">
      <div class="space-y-1.5 bg-ok/5 px-3.5 py-3">
        <p class="flex items-center gap-2 text-sm font-semibold text-ok"><ShieldCheck class="size-4" />Nothing outside this call</p>
        <p class="text-xs text-muted-foreground">No files, no network, no tools: it reads what it is sent and answers. There is nothing it could do on its own.</p>
      </div>
      <div class="grid grid-cols-[1rem_1fr] gap-x-2 border-t px-3.5 py-2 text-sm">
        <Send class="mt-0.5 size-4 text-muted-foreground" />
        <span class="font-medium">Sent to {sent}</span>
      </div>
    </section>
  {:else}
    {@render block("What it may do", ShieldCheck, may, "agent-receipt-may")}
  {/if}
</div>
