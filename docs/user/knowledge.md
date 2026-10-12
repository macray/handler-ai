# Knowledge folders

Notes your agents read: who you are, how a project works, what was decided. They are plain
markdown folders under one **knowledge root** (by default `~/knowledge`), and an agent reads the
folders you select for it, never the others.

```
~/knowledge/
├── me/                         how you work, your preferences
└── projects/
    └── my-theme/               this project's decisions and notes
```

## Set it up

The **Knowledge** page sets the root (or creates it), creates folders, and shows each folder's
notes; links between notes work there. The page only reads: you write the notes in your editor
(or Obsidian). `HANDLER_KNOWLEDGE_DIR` sets the root instead of the page.

## Give folders to an agent

In the agent's settings, pick the folders next to the addons (a folder covers its sub-folders), or
from the command line:

```bash
handler knowledge list                       # the root and the folders you can pick
cd ~/code/my-theme && handler run claude-perso --knowledge me --knowledge projects/my-theme
```

On a folder's page, **Use in a new project** opens a new project with that folder selected.

Each folder appears in the agent's sandbox at `/knowledge/<folder name>`, **read-only**: an agent
never changes your notes. Two selected folders cannot have the same name, nor be inside one
another; hidden folders cannot be selected.

## Help the agent read them

Folders say nothing by themselves about how to read them. A skill can: add it to the **Skills**
page and pick it on the agents that read knowledge folders. When a folder has an `_index.md`
(its summary), the Knowledge page shows it first.

## What writes to them

You. The only exception you set up yourself: an [automation](automations.md) may add what its
script found to a note you name, once it succeeded, with a line saying where it came from.

## See also

[`handler knowledge`](cli/knowledge.md) · how it is built:
[knowledge design](../dev/design/knowledge.md)
