# handler schema

The schemas of your Library: each one kind of document an agent keeps in your notes (contacts,
decisions), with the fields and sections every document of that kind has.

## When to use it

To add a schema an agent will read or write (`--schema ID`), to see what you have, or to remove
one no agent uses any more. A schema is found by its `$id`, such as `contacts@1`: a new version
of a schema is another `$id` (`contacts@2`), kept beside the first.

## Usage

```
handler schema list
handler schema show ID
handler schema add FILE [--replace]
handler schema rm ID
```

## Options

| Option | |
|---|---|
| `--replace` | `add` only: replace the schema of that `$id` when yours differs. Without it, yours is kept and the command says so |

## Output

`list`: each schema's `$id`, its title, and why one cannot be used (a file that is not a schema,
a schema it extends that is not there). `show`: its file. `rm` is refused while an agent uses it
or another schema extends it.

## See also

[agent options](agent-options.md#what-it-gets) · [notes folders](../notes.md)
