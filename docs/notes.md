# Notes

Notes your agents read: who you are, how a project works, what was decided. They are plain
markdown folders (*notes folders* on the command line) under one **notes root**, and an agent
reads the folders you select for it, never the others.

```
<notes root>/
├── me/                         how you work, your preferences
└── projects/
    └── my-theme/               this project's decisions and notes
```

## Where they are

There is nothing to set up: the notes root is `~/.local/share/handler-ai/notes` until you change
it, and Handler creates it. **Library → Notes** shows it; **Change** makes another folder the
root, such as an Obsidian vault: type its full path (starting with `/` or `~/`), and the button
says what happens, **Use this folder** for one you have, **Create this folder** for a new one.
The shelf also creates folders and shows each folder's notes; links between notes work there. It
only reads: you write the notes. `HANDLER_NOTES_DIR` sets the root instead of the shelf.

## Give folders to an agent

In the agent's settings, pick the folders next to the tools (a folder covers its sub-folders), or
from the command line:

```bash
handler notes list                       # the root and the folders you can pick
cd ~/code/my-theme && handler run claude-perso --notes me --notes projects/my-theme
```

Each folder appears in the agent's sandbox at `/notes/<folder name>`, **read-only**: an agent
never changes your notes. Two selected folders cannot have the same name, nor be inside one
another; hidden folders cannot be selected.

## Help the agent read them

Folders say nothing by themselves about how to read them. A skill can: add it in **Library →
Skills** and pick it on the agents that read notes. When a folder has an `_index.md`
(its summary), Library → Notes shows it first.

## What writes to them

You. The only exception you set up yourself: an [automation](automations.md) may add what its
script found to a note you name, once it succeeded, with a line saying where it came from.

## See also

[`handler notes`](cli/notes.md)
