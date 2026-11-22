"""Markdown to the parsed model (SMD spec 3): pure, no schema, never raises on bad input.

Structure comes from markdown-it's tokens, never from regexes over the text, so a heading in a
code fence, a quote or a list is content. Only top-level H1, H2 and H3 are structure; every other
line lands in the preamble, a body or a section, as written.
"""

import re
from dataclasses import dataclass
from typing import Any

import yaml
from markdown_it import MarkdownIt

from handler_smd.models import Diagnostic, Document, Entry, Item, ParseResult, Section, Severity

# a field line: a snake_case key, a colon, then a space and the value, or nothing (spec 3.1.5)
FIELD = re.compile(r"^([a-z][a-z0-9_]*):(?:[ \t]+(.*))?$")
_NOT_ALNUM = re.compile(r"[\W_]+")
_LINE_BREAK = re.compile(r"[ \t]*\n[ \t]*")
# an entry's first line (spec 13.1): its bullet, then its content; the checkbox at its start
_BULLET = re.compile(r"^( {0,3}[-*+])(?:([ \t]+)(.*))?$")
CHECKBOX = re.compile(r"^\[( |x|X)\](?:[ \t]+(.*))?$")
_MARKDOWN = MarkdownIt("commonmark")


def slug(title: str) -> str:
    """An item's slug (spec 3.3): lowercase, each run of non-alphanumerics a `-`, trimmed."""
    return _NOT_ALNUM.sub("-", title.lower()).strip("-")


def section_key(heading: str) -> str:
    """A section's key (spec 3.3): the slug with `_`."""
    return slug(heading).replace("-", "_")


@dataclass(frozen=True)
class _Block:
    """A top-level block of the markdown: its lines [start, end), 0-based."""

    kind: str  # markdown-it's token type: paragraph_open, heading_open, fence…
    start: int
    end: int
    heading: int = 0  # 1 for an H1…; 0 for anything else
    text: str = ""  # a heading's text
    bullets: tuple[tuple[int, int], ...] = ()  # a bullet list's items, their lines [start, end)


@dataclass
class _Diagnostics:
    file: str
    found: list[Diagnostic]

    def add(self, line: int, path: str, severity: Severity, code: str, message: str) -> None:
        self.found.append(
            Diagnostic(
                file=self.file, line=line, path=path, severity=severity, code=code, message=message
            )
        )


def parse(text: str, file: str) -> ParseResult:
    lines = text.splitlines()
    report = _Diagnostics(file, [])
    meta, body_start = _frontmatter(lines, report)
    # the frontmatter's lines blanked, not removed: markdown-it's line numbers stay the file's
    blocks = _blocks("\n".join([""] * body_start + lines[body_start:]))

    title: _Block | None = None
    item_heads: list[_Block] = []
    sections: dict[int, list[_Block]] = {}  # by item head's start
    for block in blocks:
        if block.heading == 1 and item_heads:
            report.add(
                block.start + 1,
                f"items[{len(item_heads) - 1}].body",
                Severity.ERROR,
                "misplaced-title",
                "a title (#) after the first item (##) is not the "
                "document's title: it stays in the item",
            )
        elif block.heading == 1 and title is None:
            title = block
        elif block.heading == 1:
            report.add(
                block.start + 1,
                "preamble",
                Severity.ERROR,
                "multiple-titles",
                f"only one title (#) is expected, already '{title and title.text}'",
            )
        elif block.heading == 2:
            item_heads.append(block)
            sections[block.start] = []
        elif block.heading == 3 and item_heads:
            sections[item_heads[-1].start].append(block)
    if title is None:
        report.add(1, "title", Severity.ERROR, "missing-title", "the document has no title (#)")

    first_item = item_heads[0].start if item_heads else len(lines)
    if title is None:
        preamble = _trim(lines[body_start:first_item])
    else:
        parts = [_trim(lines[body_start : title.start]), _trim(lines[title.end : first_item])]
        preamble = "\n\n".join(p for p in parts if p) or None

    items: list[Item] = []
    for index, head in enumerate(item_heads):
        end = item_heads[index + 1].start if index + 1 < len(item_heads) else len(lines)
        items.append(
            _item(
                index,
                head,
                end=end,
                section_heads=sections[head.start],
                blocks=blocks,
                lines=lines,
                report=report,
                before=items,
            )
        )

    diagnostics = sorted(report.found, key=lambda d: (d.file, d.line, d.path))
    document = Document(
        meta=meta, title=title.text if title else None, preamble=preamble, items=items
    )
    return ParseResult(document=document, diagnostics=diagnostics)


def closed_fences(text: str) -> str:
    """`text` with its code fence closed when it never is (CommonMark: it runs to the end of the
    document). The renderer writes a block before others it did not precede (review notes go
    last, spec 7.7): open, its fence would take in what follows on the next read."""
    fences = [t for t in _MARKDOWN.parse(text) if t.type == "fence" and t.level == 0]
    if not fences or fences[-1].map is None:
        return text
    last, markup = fences[-1].map, fences[-1].markup
    lines = text.split("\n")
    closing = lines[last[1] - 1].strip() if last[1] - 1 > last[0] else ""
    if closing and set(closing) == {markup[0]} and len(closing) >= len(markup):
        return text
    return f"{text}\n{markup}"


def frontmatter_block(text: str) -> str | None:
    """The frontmatter as written, its two `---` lines included; None when the text has none
    (no `---` first, or one never closed: read as content)."""
    lines = text.splitlines()
    end = _frontmatter_end(lines)
    return "\n".join(lines[: end + 1]) if end is not None else None


def frontmatter_meta(block: str) -> dict[str, Any]:
    """What a frontmatter block holds as the parser reads it ({} when it is not a mapping)."""
    return _frontmatter(block.splitlines(), _Diagnostics("", []))[0]


def unwritable(block: str) -> str | None:
    """Why that frontmatter cannot be written again from its fields without losing what it
    holds (spec 7.1): not valid YAML, not a mapping, a key written twice, a comment. None: its
    fields are all it holds (only its layout and key order would change). Rule
    `smd.frontmatter-kept-as-written`: what is refused is this list."""
    report = _Diagnostics("", [])
    _frontmatter(block.splitlines(), report)
    for d in report.found:
        if d.code in ("invalid-frontmatter", "duplicate-field"):
            return d.message.split("\n")[0]
    if _has_comment("\n".join(block.splitlines()[1:-1])):
        return "the frontmatter has a comment (#)"
    return None


def _has_comment(yaml_text: str) -> bool:
    """A `#` outside every value: YAML's scanner skips comments, so one is a `#` that no token
    of the text covers."""
    covered: list[tuple[int, int]] = []
    for token in yaml.scan(yaml_text, Loader=yaml.SafeLoader):
        covered.append((token.start_mark.index, token.end_mark.index))
    return any(
        not any(start <= i < end for start, end in covered)
        for i, char in enumerate(yaml_text)
        if char == "#"
    )


class _Loader(yaml.SafeLoader):
    """YAML's safe loader, keeping the keys a mapping writes twice (YAML keeps the last)."""

    def __init__(self, stream: str) -> None:
        super().__init__(stream)
        self.duplicates: list[str] = []

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if isinstance(key, str) and key in seen and key not in self.duplicates:
                self.duplicates.append(key)
            seen.add(key if isinstance(key, str) else id(key_node))
        return super().construct_mapping(node, deep=deep)


def _frontmatter_end(lines: list[str]) -> int | None:
    if not lines or lines[0].rstrip() != "---":
        return None
    return next((i for i in range(1, len(lines)) if lines[i].rstrip() == "---"), None)


def _frontmatter(lines: list[str], report: _Diagnostics) -> tuple[dict[str, Any], int]:
    """The YAML mapping between `---` lines at the very start, and the first line after it."""
    if not lines or lines[0].rstrip() != "---":
        report.add(
            1,
            "meta.schema",
            Severity.INFO,
            "missing-schema-field",
            "no frontmatter with `schema: <name>@<version>`: parsed, not validated",
        )
        return {}, 0
    end = _frontmatter_end(lines)
    if end is None:
        report.add(
            1,
            "meta",
            Severity.ERROR,
            "invalid-frontmatter",
            "the frontmatter is not closed by a `---` line: read as content",
        )
        return {}, 0
    loader = _Loader("\n".join(lines[1:end]))
    try:
        data = loader.get_single_data()
    except yaml.YAMLError as error:
        report.add(
            1,
            "meta",
            Severity.ERROR,
            "invalid-frontmatter",
            f"the frontmatter is not valid YAML: {error}",
        )
        return {}, end + 1
    finally:
        loader.dispose()
    data = {} if data is None else data
    if not isinstance(data, dict) or not all(isinstance(k, str) for k in data):
        report.add(
            1,
            "meta",
            Severity.ERROR,
            "invalid-frontmatter",
            "the frontmatter must be a mapping of names to values",
        )
        return {}, end + 1
    for key in loader.duplicates:
        report.add(
            1,
            f"meta.{key}",
            Severity.WARNING,
            "duplicate-field",
            f"`{key}` is written twice in the frontmatter: the last one is kept",
        )
    if "schema" not in data:
        report.add(
            1,
            "meta.schema",
            Severity.INFO,
            "missing-schema-field",
            "the frontmatter has no `schema: <name>@<version>`: parsed, not validated",
        )
    return data, end + 1


def _blocks(text: str) -> list[_Block]:
    tokens = _MARKDOWN.parse(text)
    blocks: list[_Block] = []
    for i, token in enumerate(tokens):
        if token.level != 0 or token.nesting == -1 or token.map is None:
            continue
        start, end = token.map
        if token.type == "heading_open":
            level = int(token.tag[1])
            # a heading underlined (setext) may span lines: one line, its breaks spaces
            text = _LINE_BREAK.sub(" ", tokens[i + 1].content.strip())
            blocks.append(_Block(token.type, start, end, level, text))
        elif token.type == "bullet_list_open":
            bullets = []
            for item in tokens[i + 1 :]:
                if item.level == 0:
                    break
                if item.type == "list_item_open" and item.level == 1 and item.map is not None:
                    bullets.append((item.map[0], item.map[1]))
            blocks.append(_Block(token.type, start, end, bullets=tuple(bullets)))
        else:
            blocks.append(_Block(token.type, start, end))
    return blocks


def _item(
    index: int,
    head: _Block,
    *,
    end: int,
    section_heads: list[_Block],
    blocks: list[_Block],
    lines: list[str],
    report: _Diagnostics,
    before: list[Item],
) -> Item:
    path = f"items[{index}]"
    item_slug = slug(head.text)
    if any(other.slug == item_slug for other in before):
        report.add(
            head.start + 1,
            path,
            Severity.WARNING,
            "duplicate-item-title",
            f"another item has the slug '{item_slug}': a reference to it is ambiguous",
        )

    head_end = section_heads[0].start if section_heads else end
    fields: dict[str, str | None] = {}
    field_lines: dict[str, int] = {}
    body_start = head.end
    first = next((b for b in blocks if head.end <= b.start < head_end), None)
    if first is not None and first.kind == "paragraph_open":
        matches = [FIELD.match(line) for line in lines[first.start : first.end]]
        if all(matches):
            for offset, match in enumerate(matches):
                assert match is not None
                key, value = match.group(1), (match.group(2) or "").strip() or None
                if key in fields:
                    report.add(
                        first.start + offset + 1,
                        f"{path}.fields.{key}",
                        Severity.WARNING,
                        "duplicate-field",
                        f"'{key}' is given twice: the last one is kept",
                    )
                fields[key] = value
                field_lines[key] = first.start + offset + 1
            body_start = first.end

    sections: dict[str, Section] = {}
    for i, section in enumerate(section_heads):
        section_end = section_heads[i + 1].start if i + 1 < len(section_heads) else end
        key = section_key(section.text)
        if key in sections:
            n = 2
            while f"{key}_{n}" in sections:
                n += 1
            report.add(
                section.start + 1,
                f"{path}.sections.{key}_{n}",
                Severity.WARNING,
                "duplicate-section",
                f"another section of this item is also '{key}': kept as '{key}_{n}'",
            )
            key = f"{key}_{n}"
        content = _trim(lines[section.end : section_end]) or ""
        sections[key] = Section(heading=section.text, line=section.start + 1, content=content)

    # its body is its entries when it is only one bullet list (spec 13.1)
    body_blocks = [b for b in blocks if body_start <= b.start < head_end]
    entries = None
    if len(body_blocks) == 1 and body_blocks[0].kind == "bullet_list_open":
        entries = _entries(body_blocks[0], lines, path, report)
    return Item(
        title=head.text,
        slug=item_slug,
        line=head.start + 1,
        fields=fields,
        field_lines=field_lines,
        body=None if entries is not None else _trim(lines[body_start:head_end]),
        entries=entries,
        sections=sections,
    )


def _entries(block: _Block, lines: list[str], path: str, report: _Diagnostics) -> list[Entry]:
    """Each bullet of a list (spec 13.1): its checkbox and text from its first line; under it,
    its fields (a first paragraph of `key: value` lines only), then its notes, dedented."""
    entries: list[Entry] = []
    seen: dict[str, int] = {}
    for index, (start, end) in enumerate(block.bullets):
        where = f"{path}.entries[{index}]"
        bullet = _BULLET.match(lines[start])
        content, indent = "", 2
        if bullet is not None:
            content = bullet.group(3) or ""
            spaces = len((bullet.group(2) or " ").expandtabs(4))
            indent = len(bullet.group(1)) + (spaces if spaces <= 4 else 1)
        checked: bool | None = None
        if box := CHECKBOX.match(content.strip()):
            checked = box.group(1) != " "
            content = box.group(2) or ""
        text = content.strip()
        under = [_dedent(line, indent) for line in lines[start + 1 : end]]
        paragraph = []
        for line in under:
            if not line.strip():
                break
            paragraph.append(line)
        fields: dict[str, str | None] = {}
        field_lines: dict[str, int] = {}
        matches = [FIELD.match(line) for line in paragraph]
        if paragraph and all(matches):
            for offset, match in enumerate(matches):
                assert match is not None
                key, value = match.group(1), (match.group(2) or "").strip() or None
                if key in fields:
                    report.add(
                        start + offset + 2,
                        f"{where}.fields.{key}",
                        Severity.WARNING,
                        "duplicate-field",
                        f"'{key}' is given twice: the last one is kept",
                    )
                fields[key] = value
                field_lines[key] = start + offset + 2
            under = under[len(paragraph) :]
        base = slug(text)
        seen[base] = seen.get(base, 0) + 1
        entries.append(
            Entry(
                text=text,
                slug=base if seen[base] == 1 else f"{base}-{seen[base]}",
                line=start + 1,
                checked=checked,
                fields=fields,
                field_lines=field_lines,
                notes=_trim(under),
            )
        )
    return entries


def _dedent(line: str, indent: int) -> str:
    """A line under a bullet without its content's indent (a lazy line has less, or none)."""
    spaces = len(line) - len(line.lstrip(" "))
    return line[min(spaces, indent) :]


def _trim(lines: list[str]) -> str | None:
    """Raw markdown without its blank lines at both ends; None when nothing is left."""
    start, end = 0, len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return "\n".join(lines[start:end]) or None
