# handler plan

Review, approve and follow a plan: long work split into steps, written with the plan builder (a
draft Handler keeps) or by an agent in its folder. Handler runs the steps one after another, each
a new session of an agent of the project, and stops at the first step that is not done.

## When to use it

- Work that takes many hours, in parts that each need a fresh start: you would otherwise clear
  the conversation and type "do the next step" again and again.
- To read a plan an agent wrote before anything runs, then approve it.
- To see how far a plan went, why it stopped, and to run it again from a step.

Write it with the plan builder: *New plan* in the web UI (Plans, or a project's page) makes a
draft, whose id (`d_…`) this command reads. Or give an agent the skill `handler-plan` and ask it,
in a session, to write a plan: it writes `plans/<name>.md` in its folder. Each step has a goal
and a "Done when" the step checks itself before it says it is done.

## Usage

```
handler plan check PATH|DRAFT
handler plan run PATH|DRAFT [--yes]
handler plan run ID --from N [--allow HOST:PORT]...
handler plan list
handler plan show ID
handler plan cancel ID
handler plan delete ID [--yes]
```

## Subcommands

| Subcommand | |
|---|---|
| `check PATH` | read a plan file of an agent's folder, or a draft (its id): its steps and its problems (exit 1 when it has some). Nothing runs |
| `run PATH` | show its steps, ask, then approve it as you read it and run it; `--yes` does not ask. If the file (or the draft) changes after you read it, it is refused: read it again |
| `run ID --from N` | run a plan that stopped (or is done) again from step N, at most its first step not done: once you fixed what failed. `--allow HOST:PORT` (repeatable) first allows for its agent a host the network filter blocked in that step (`show` gives the command) |
| `list` | every plan: its id, state (running, done, stopped), steps done, agent, when you approved it, title |
| `show ID` | each step: its state, its summary, why it failed, the hosts the network filter blocked in it (how many times, what the agent said of them), the command to open its session |
| `cancel ID` | stop the step running: the plan stops |
| `delete ID` | forget a plan that is not running; its sessions stay with the agent. Asks first, `--yes` does not |

The agent that runs a plan is the one its `Agent:` line names, with its own settings: it must be
set to never ask (permissions *bypass*), as nobody answers its steps. On a subscription, Handler
recommends an API key, as for any agent that runs on its own. From the command line the plan
names its agent; the web UI's review may choose another, or fix the agent (see
[Plans](../plans.md#review-and-approve-it)).

## Example

```bash
cd ~/code/my-project
handler plan check plans/tests.md
handler plan run plans/tests.md
handler plan show p_3f2a9c1d0b8e4a71
handler attach s_9c1d0b8e4a713f2a          # watch the step running
handler plan run p_3f2a9c1d0b8e4a71 --from 2   # after fixing what step 2 broke
```

## See also

[plans guide](../plans.md) · [`attach`](attach.md) · [`session`](session.md)
