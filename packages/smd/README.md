# smd — `handler_smd`

**Implements:** structured markdown (SMD), the format of the structured knowledge ability:
markdown humans write, that agents and apps parse, validate and edit. Its spec is the SMD spec
(the build brief: milestones M1–M6, one at a time; its decisions are recorded in its section 12).
**Depends on:** pydantic, markdown-it-py, PyYAML. **Nothing from Handler**, not even
`handler_contracts` (`tests/architecture`): the format stands alone.
**Used by:** handlerd (the Library's schemas, the notes' history, an app's code reading and writing
documents through it, confined to the folders given to the app) and the `knowledge` tool, by its
command, `handler-smd` (`cli.py`), installed with Handler.

The core is pure: it takes text and data, returns data. Bad input is a `Diagnostic`, never an
exception; only a programmer's error raises.

| File | Role |
|---|---|
| `models.py` | the parsed model (`Document`, `Item`, its `Entry`s, `Section`) and `Diagnostic`, `Severity` (spec 3.2, 6) |
| `parser.py` | `parse(text, file)`: markdown to the model, the syntax diagnostics (spec 3); `slug`, `section_key` (3.3) |
| `schema.py` | the schema vocabulary (`TypeDefinition`, `ItemDef`, `FieldDef`, `SectionDef`) and `parse_typedef(text, file)`: a schema file's text, or its `invalid-schema` diagnostics (spec 5.1, 5.2) |
| `validator.py` | `validate(document, typedef, file)`: the document checked against its schema, the same model typed (fields coerced, sections under the schema's keys) and its diagnostics (spec 4, 5.1, 6) |
| `renderer.py` | `render(document, typedef=None)`: the one canonical markdown (spec 7) |
| `scanner.py` | with `cli.py`, the only I/O: the schemas folder (`*.schema.json`), a folder's documents, `check` (every diagnostic, `broken-ref` by following references), `fmt` (rewrites what changes), `write` (a document given as data, then checked); confined `within` a folder: nothing read or written outside it nor through a link |
| `agent.py` | a schema as an agent reads it (spec 8): `to_json_schema`, `template` (a blank document, descriptions as hints), `prompt` (the rules and the schema) |
| `cli.py` | `handler-smd check | fmt | parse | write | schema export|template|prompt`; the schemas folder: `--schemas`, else `$SMD_SCHEMAS` |
| `resolver.py` | `index_schemas`: one folder's schemas by `$id`, `extends` applied once; `resolve_schema`: a document's schema by its `$id` alone (spec 5.3) |

Tests: `tests/test_parser.py` (golden: `tests/fixtures/*.md` and their `*.expected.json`),
`tests/test_schema.py` (the spec's example schema: `tests/fixtures/decision-log.schema.json`),
`tests/test_resolver.py`, `tests/test_entries.py` (list entries, spec 13: parsed, typed, rendered,
told to an agent), `tests/test_validator.py` (golden: the spec's 9.2,
`tests/fixtures/decision-log-invalid.md`), `tests/test_renderer.py` (the laws of spec 7 on documents
`hypothesis` generates), `tests/test_scanner.py` (files in a temporary folder, the CLI), `tests/test_agent.py` (the JSON Schema checked
with `jsonschema`, the template, the prompt, `write`).
