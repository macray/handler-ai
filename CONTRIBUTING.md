# Contributing

Handler is open source, but not open to code contributions: **pull requests are very unlikely to be merged**. What helps
most is hearing how you use it.

## What I'm looking for

- **Your use cases**: what you tried to do with Handler (the task, the harness, the model), whether
  it worked, and where you gave up, even at install.
- **Your pain points** with coding agents and personal automation, even those Handler does not
  address yet: what you do by hand, what you don't trust an agent with, what you gave up on.
- **Bugs**, with what you ran, what you expected and what happened.

All of these go to [Issues](https://github.com/macray/handler-ai/issues/new/choose). A security
problem goes to [`SECURITY.md`](SECURITY.md) instead.

## Why no pull requests

Handler is mostly written with coding agents, by one person who must keep understanding all of it.
Code is cheap to produce now; reviewing someone else's long change is not, and a merged change I
don't fully understand is one I can't keep. So describe the problem, not the patch. When an idea
fits, it is built in a later release (from the description, not from a diff), and the release
notes say whose idea it was.

## How the repository works

Each commit here is one release; what changed is in [`CHANGELOG.md`](CHANGELOG.md), with the issues each release fixes.
To explore the code: [`CLAUDE.md`](CLAUDE.md) (also `AGENTS.md`), the instructions the coding
agents work with (point yours at it), then each package's README (what it implements, what it may
depend on) and its tests (what it promises).
