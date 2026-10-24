# Checks

A run of a job kept with its right answer, run again later to see that the same answer still
comes. Normative: [contracts §D.20](../contracts.md).

## Why

An agent changes: its instructions are rewritten, its model replaced by a cheaper one, its
knowledge grows. Whether it still does its job is otherwise found out by chance. A check is the
smallest way to know: a case where you know the right answer, kept, and run again. It is also
what an improvement needs to know what "better" is (*Improve until they pass*, not built yet).

## Choices

- **Kept from a real run.** No form to fill in a test: you run the job, the answer is right,
  you keep it. The input and the whole result are kept; you choose what must come back.
- **Jobs only, never free text.** A job's result is data: a verdict, a choice, a number come
  back the same or not. Free text (a summary, a "why") never comes back word for word; it is
  shown, not compared. Comparing meaning is a judge's work (another agent), later.
- **The agent's, not its settings.** Checks are kept beside the agent and go with it; saving
  its settings does not carry them (two editors would otherwise overwrite each other's), and an
  agents file carries them.
- **Run only when asked.** Each check is a run: for an agent program, minutes and money. So
  nothing runs behind the person's back, not even after a save; the block says what changed
  since the last check run ("Not run since you changed its instructions").
- **A check's run is a run.** The same runs as the Run button's (D.18), with origin `check`: the
  same sandbox or model alone, the same result parsing. They are left out of the agent's history
  and never told to the inbox, and deleted with the check run that made them.
- The word: *check*, not *test*, for people who are not developers; the module that holds the
  rules an agent must pass to be saved is `save_rules.py`, so that "check" means one thing.

## Improve until they pass

An improvement (D.21) is what checks were also made for: knowing what "better" is.

- **The writer is an agent you can change**, not a hidden model call: the built-in *prompt
  writer*, on the model alone. Its instructions are the default prompt ("clearer, and fix what
  the checks say"); you change them by editing it. Each improvement says its own goal. It also
  keeps to the rule that Handler calls a model only for you, never on its own.
- **Attempts are text, kept by Handler**: a version of the instructions and its checks' results.
  Not copies of the agent (they would crowd its place and its history), not files in the project
  (an attempt of a prompt is no file). An attempt's checks are runs of the job with the attempt's
  instructions instead of its own: the agent is not touched until you keep one, which is an
  ordinary save, and attempt 0 puts the old instructions back.
- **No checks kept aside** yet: with few checks, an attempt can learn them rather than the rule;
  the dialog says so. Keeping some from the writer is the next step if it proves needed.
- **A budget of attempts and minutes**, tokens not priced (Handler does not know the prices).

## Not built yet

- A judge (an agent on the model alone that says whether an answer is right) and *you* (pick the
  better of two answers), for briefs, chats and free text.
- Checks kept aside from the writer; a diff of an attempt with the instructions it started from.
- Checks run on a schedule (opt-in), and before an update of agents set up from a file.
- Checks of apps.
