---
name: handler-plan
description: How to write a Handler plan - long work split into steps that Handler runs one after another, each in a fresh session of one agent of the project. Use when the user asks for a plan to be run by Handler, or when work will take many hours and needs several fresh contexts.
---

# Plans in Handler

Handler runs you in a sandbox. A **plan** is a file you write; the user reviews it in Handler
and approves it, then Handler runs its steps one after another, each in a **new session of the
agent the plan names** (its runner), with that agent's settings, unattended: nobody answers its
questions, and it remembers nothing of this conversation. The plan stops at the first step that
is not done.

You cannot run a plan yourself, nor start a session: only the user can, in Handler.

Where you write it:

- **As Handler's plan builder** (your session's brief says so): in `plan.md` of your own folder,
  a draft Handler keeps. You see the project read-only, at the path the brief gives: the steps
  will work there.
- **Otherwise**, in your working folder: `plans/<name>.md`; the steps work in that folder.

## When to write one

- Work that takes hours and is better done in parts, each with a fresh context: a migration
  module by module, tests for each area, the docs of each feature.
- Not for work that fits in one session: just do it.

## How to split the work

- **One step, one session.** A step is what one session can finish: a few hours at most (each
  step's turn is limited, 3 hours unless the plan says otherwise).
- **Each step stands alone.** It starts with nothing but the folder, the plan's context, its own
  step and the notes of the steps before it. Never "as discussed" or "the approach we chose":
  write it in the context or the step.
- **In order.** Step 2 may rely on what step 1 left in the folder (its files, its commit), never
  on its conversation. Each step ends by writing notes for the next ones (what it did, where,
  what is left): say in a step's goal what its notes must hold when a later step needs it.
- **A "Done when" it can check itself.** A command and what it must show (`./scripts/ci.sh`
  passes; `pytest tests/x` passes; the page lists every rule), never a feeling ("the code is
  clean"). The step runs it in its sandbox before it says it is done, and says `failed` when it
  is not met: the plan then stops before anything is built on a broken step.
- **A commit at its end** when the folder is a git repository: say so in the context, so the
  steps after it and the user see what each step did.
- Things a step cannot do in its sandbox (sign in somewhere, use a device, a secret it does not
  have) are not steps: tell the user before or after the plan.

## The format

Write it where you write plans (above; in your folder, `plans/<name>.md`: a short name in
lowercase, with hyphens), exactly so:

```markdown
# Plan: <what the plan achieves>
Agent: <the name in Handler of the agent that runs its steps>
Context: <what every step must know: the goal, where to read first, the conventions,
what to commit>. It may run on several lines, until the first step.
Step time limit: 3h

## 1. <the first step's title>
Goal: <what this step does, on several lines if needed: files, commands, what to leave
for the next steps in its notes>.
Done when: <the check this step runs itself, and what it must show>.

## 2. <the next step's title>
Goal: …
Done when: …
```

- `# Plan:` first, once. `Agent:` names the agent that runs every step: as the plan builder, one
  of those your brief lists (ask the user when several may); otherwise your own name in Handler
  (ask the user if you do not know it). Leave it out when none is known: the user chooses the
  agent on the review page. `Context:` is optional; `Step time limit:` too (`<n>h` or `<n>m`, from 1 minute
  to 24 hours; 3 hours when left out).
- Steps are `## 1.`, `## 2.`, … in order, each with `Goal:` and `Done when:`. Other text under a
  step is part of its goal. Code blocks are fine.
- Nothing else in the header: an unknown line is a problem, and Handler refuses a plan with a
  problem.

## When it is written

As the plan builder, tell the user: "The plan is written. Review it with *Review this plan* on
this session's page: you may edit it there and choose the agent that runs it."

Otherwise, tell the user: "The plan is in `plans/<name>.md`. Review it in Handler: open the file
in this session's Files and choose *Review this plan*, or run `handler plan run
plans/<name>.md`."

Do not start on the steps yourself.

## When you are one of its steps

Your first message then says "You are doing step n of N". Do that step only, check its "Done
when" yourself, and answer with the result block it asks for: `done` only when the check passes,
`failed` with why otherwise, and notes for the steps after yours.
