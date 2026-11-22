---
name: knowledge
description: Read and write structured notes, documents of a known shape (contacts, decisions, a reading log) checked against a schema. Use when a task reads, adds to or changes such documents in /notes, or when the person asks to keep a list of things in their notes.
---

# Structured notes

A structured note is a plain markdown file with a known shape: a frontmatter naming its schema
(`schema: contacts@1`), a `# Title`, then one `## ` heading per item, each with a block of
`field: value` lines and maybe `### ` sections. A **schema** says which fields and sections an
item has. People read and edit these files as ordinary markdown; you work with them through
`handler-smd` (also `smd`), so their shape stays right.

## What you have

- The schemas you may use: `ls "$SMD_SCHEMAS"` (one `<id>.schema.json` each). They are
  read-only, and `handler-smd` finds them there by itself: no flag needed.
- Your notes folders: `ls /notes`. Write only in a folder you can write to (test with
  `test -w /notes/<folder>`); the others are read-only.

## Before you write documents of a schema

Read what that schema asks, every time you start on one:

```bash
handler-smd schema prompt contacts@1     # the rules, the fields and sections, the JSON Schema
handler-smd schema template contacts@1   # a blank document of that kind
```

## The rules

1. **Never write the markdown yourself.** Write the document as JSON and let `handler-smd write`
   render it: the file comes out in its one canonical form, and is checked.
2. **Never invent a value.** What your source does not say is `null`: the check reports it, and
   the person completes it.
3. **Discard nothing.** What fits no field goes into the item's body, a field or a section of
   your own (if the schema allows it).
4. **Say what you guessed.** A value you inferred ("last Tuesday" made a date) goes in the
   item's `### Review notes` section, one list item per guess.
5. **Long text goes in a section**, never in a field: a field value is one line.

## Commands

```bash
handler-smd parse /notes/people/contacts.md > /tmp/doc.json    # a document as JSON
# … change /tmp/doc.json …
handler-smd write /notes/people/contacts.md < /tmp/doc.json    # render, write, check
handler-smd check /notes/people                                # every problem in a folder
```

To change a document: `parse` it, change the JSON, `write` it back; what you did not change
stays as it was. A new document: start from `schema template`, or write the JSON from scratch
with `meta.schema` set. `write` prints the problems it found (exit 1 when one is an error; the
file is written all the same): fix them, or leave a review note saying why not.

The frontmatter (the `---` block at the top) is the person's: `write` keeps it exactly as they
wrote it, comments and layout, while its fields are the same. Change a field there only when the
task asks for it; `write` refuses (the file untouched) when the frontmatter holds a comment, a
key written twice or text that is not YAML, which changing its fields would lose: tell the person
to change it by hand. `handler-smd fmt FOLDER` lays documents out in their canonical form, below
the frontmatter; run it only when the person asks.

## What not to do

- Do not add, change or copy schemas into the person's Library: only they add one, in Handler.
  To propose a new schema, write it as a file in your work folder and test it with
  `handler-smd check --schema <file> <document>`, then tell the person.
- Do not change files of a notes folder beyond what the task needs: the person sees every
  change you make there.
