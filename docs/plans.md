# Plans: long work in steps

Some work takes a day: tests for every part of a project, a migration module by module, the docs
of each feature. Done in one conversation, the agent's context fills up; done by hand, you clear
the conversation and type "do the next step" again and again. A **plan** does it for you:

1. You write the plan with the **plan builder**: steps that each stand alone, with how to know
   each is done.
2. You read it in Handler and approve it, once.
3. Handler runs the steps one after another, each in a **new session** of an agent of the
   project, and stops at the first step that is not done.

## Write one with the plan builder

On the project's page, its **Plans** tab → **New plan**. The tab says who writes it (*Written by
the plan builder*, with its program and model; the link opens its page in Settings → Helpers). The
first time, its card opens in place: who works (you choose the program and the account or key with
its model) and what it can do, then **Turn on**. Then a session of the plan builder opens: it
reads the project, asks what you want done, and writes the plan.

The plan builder only writes: it sees the project **read-only**, all of it, and writes in a
**draft** Handler keeps, never in your project. It gets no tool and no secret but its model's,
and its network reaches only its model's sites. Changed to have more, Handler refuses to
start it, saying what to undo. Its model must be one of the project's area; when it is not,
*New plan* lets you choose another for this plan.

When the plan is written, **Review this plan** on the session's page opens it. Plans being
written are listed on the project's Plans tab under **Being written**: review one,
**Continue** its plan builder session, or **Throw away** the draft (its session stays).

## Or write one with your agent

Give the agent the skill **handler-plan** (Handler puts it in your Skills library: give it in the
agent's settings, or to every agent of a project in the project's settings). Then, in a session,
discuss the work with it and ask: *write a plan for this*. It writes `plans/<name>.md` in its
folder:

```markdown
# Plan: tests for every route of the API
Agent: dev
Context: read docs/api.md first; one test file per route in tests/api/; commit after each step.
Step time limit: 2h

## 1. The routes of projects
Goal: tests for every route of api/projects.py, each error included.
Done when: `pytest tests/api/test_projects.py` passes.

## 2. The routes of sessions
Goal: the same for api/sessions.py.
Done when: `pytest tests/api` passes.
```

- **Agent:** the agent that runs every step, one working in this folder. You may leave it out
  and choose the agent when you review the plan.
- **Context:** what every step must know. A step starts fresh: it reads the folder, the plan and
  the notes the steps before it left, never your conversation.
- **Step time limit:** how long a step may run, from `1m` to `24h` (3 hours when left out).
- Each step has a **Goal** and a **Done when**: a check the step runs itself (a test command and
  what it must show) before it says it is done.

The file is yours: edit it before you approve it, commit it or not. (The plan builder's drafts
are Handler's: edit them on the review page.)

## Review and approve it

A draft: **Review this plan** on its plan builder session, or on Plans. A file: in the session,
open **Files**, the plan's file, then **Review this plan** (or, in a terminal in that folder,
`handler plan run plans/<name>.md`; a draft: `handler plan run <its id>`). Handler reads the plan,
shows its steps and its problems (a step without *Done when*, an agent that does not exist…): a
plan with problems cannot be approved.

**Edit** (a draft only) changes its text by hand. It is saved over the text you read: if the plan
builder wrote meanwhile, Handler says so and keeps its version; read it again.

**Who runs its steps.** The review shows the agent that runs them: the one the plan names, or
one you choose among the agents working in that folder, the project's (your choice wins over the plan's
`Agent:` line; the plan's text is not changed). The agent must be one you chat with, working in the
folder, and set to never ask before acting. Where it is not, the review offers the fix:

- **Switch it to Auto-approve**: the agent asks before acting, and nobody answers a plan's steps.
  This saves the agent's permissions as *Auto-approve*, for all its sessions, not only the plan's.
- **Create a plan runner**: no agent of the project can run steps (each takes a form, say). It
  opens a new agent of the project (it never asks, and reaches only the sites it needs), on the
  model of the project's default agent: change what you like, save it, and you
  are back on the review with it chosen.

**Approve and run** approves the plan as you read it. If it changes before you click (the agent
still writing it, say), Handler refuses it: read it again. Once approved, Handler keeps its own
copy: editing the file or the draft afterwards changes nothing that runs. To change a plan, edit
it and approve it again: it is a new plan. On a plan's page, **Edit as a new draft** copies the
plan you approved into a new draft, to change and approve again.

The agent must be set to never ask before acting (permissions *Auto-approve*): nobody answers its
steps. It runs with its own settings: its folder, its network, its tools, its model. A plan
cannot give it more.

**On a subscription.** A plan's steps run one after another without you following them. Your
subscription's terms may expect you at the keyboard: the review says so, and an API key (a
provider) is recommended. Approving a plan is starting its steps yourself.

## Follow it

The project's **Plans** tab lists its plans. One that runs shows its steps: done (what it did),
running (its session, the time used), waiting (its *Done when*); one that stopped shows why on the
step it stopped at, with the fix there (*Allow it and run again from step 3* for a host the network
filter refused, *Keep blocked*, or *Run again from step 3*). The finished ones are folded. A
plan's page shows each step: waiting, running, done or
failed, its summary, the notes it left for the next steps, and **Its session**: open it to watch
the step work (you cannot type in it: the step runs on its own).

A step is **done** when it says so after checking its *Done when*. When a step **fails** (it says
so, or ends without a result, or runs past its time limit), the plan **stops**: no later step
runs on a broken one. Its page says why. Fix what failed (in a session with the agent, or in
your editor), then **Run again from here** on that step. **Cancel** stops the step running.
A plan that stops comes to your [inbox](automations.md#your-inbox) too: its name, the step and why.

**A host blocked by the network filter.** When the filter blocked a host the step needed, the
plan says so, "Stopped: step 1 failed: pypi.org:443 was blocked by the network filter", instead of
the agent's guess. A step that completed without some hosts says "Completed, with 2 hosts
refused", how many times each, what the agent did instead, and that the result may differ from
what you would get with these hosts; its notes end with "Hosts refused: …", so the next steps
know, and your inbox is told. **Allow and run again from step n** allows them for the agent and
runs the plan from that step; **Keep blocked** keeps them out for good (never listed again).

One plan runs per agent at a time. A plan's steps wait for the agent's other runs (a job's) to
end, as runs of one agent do.

From a terminal: [`handler plan`](cli/plan.md).

## What a plan does not do

- It does not check a step's work on its own: the step runs its *Done when* itself, as the agent
  does when you ask it in a session; its session shows what it ran.
- It does not tell your inbox when it ends: look at its page.
- A step cannot use another agent, another folder, more network or a secret its agent does not
  have.
