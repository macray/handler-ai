---
name: handler-skills
description: How Handler keeps Agent Skills and how a skill written in a Handler session gets to its library. Use whenever you create or edit a skill in a Handler session, before writing files and before telling the user the skill is ready.
---

# Skills in Handler

Handler runs coding agents in sandboxes and keeps a library of skills (`~/.config/handler-ai/skills/<name>/`
on the user's machine) that the user gives to their agents. You cannot write the library: you
write the skill in your working folder, and the user saves it to the library from the session's
page (**Save to library**). Nothing you write elsewhere is kept.

## Where the skill goes

- Your working folder (the current directory) is the skill: `SKILL.md` at its root, the other
  files next to it. A `SKILL.md` already there is the skill the user wants improved: edit it in
  place, keep its `name` unless the user wants it renamed.
- One skill per session. Scratch work (test outputs, evals, drafts) goes in a hidden folder such
  as `.work/`: hidden files and folders are left out when the skill is saved.

## The rules Handler checks when it is saved

- `SKILL.md` starts with a YAML frontmatter: `name` (1 to 64 lowercase letters, digits and single
  hyphens) and `description` (1 to 1024 characters: what it does and when to use it, the only
  thing an agent reads before deciding to use it). Other fields are kept (`compatibility`:
  what the skill needs to run, e.g. "python3, network access to api.example.com").
- At most 500 files, 5 MiB per file, 20 MiB in all. No symbolic links (left out).
- Executable bits are kept: `chmod +x` the scripts agents run.

## Where it will run

The agents using the skill run in Handler sandboxes: a container with the user's toolbox image (common
command-line tools, language runtimes the user chose), their project folder, and often a filtered
network (only the hosts the user allowed). So:

- say in `compatibility` what a script needs (commands, runtimes, hosts it reaches);
- prefer what is already there (shell, Python's standard library, Node for a JavaScript script)
  over installing packages;
- never ask for secrets in the skill's files: the agent gets credentials from Handler's tools.

## When it is ready

Check the frontmatter and the files against the rules above, then tell the user to click
**Save to library** on the session's page (global, or for one project). They can review it there
before giving it to their agents.
