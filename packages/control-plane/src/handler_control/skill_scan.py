"""What handlerd finds in a skill's files, no model involved (D.17): what a model reading the skill
cannot be talked out of. Shown on the skill's page and given to the agents reviewing it (D.18).

    executables   files with the executable bit
    binaries      files that are not UTF-8 text
    hosts         URLs in its text, by host
    hiddenText    invisible or bidirectional Unicode (format characters: zero-width, bidi
                  controls, tags), which can hide instructions from a reader
    blobs         long base64 or hex runs, which can hide a payload
"""

import re
import unicodedata
from pathlib import Path

from handler_contracts import ScanHit, SkillScan

from . import skills

MAX_HITS = 100  # per kind
URL = re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://([^/\s\"'<>()\[\]`]+)")
BLOB = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}|\b[0-9a-fA-F]{128,}\b")
BOM = "\ufeff"  # a byte order mark at the start of a file is not hidden text


def scan(folder: Path) -> SkillScan:
    """The scan of a skill's SKILL.md and other files (the ones agents get: no hidden files, no
    symbolic links)."""
    executables, binaries = [], []
    hosts: list[ScanHit] = []
    hidden: list[ScanHit] = []
    blobs: list[ScanHit] = []
    for f in [skills.SkillFile(skills.SKILL_FILE, 0, False), *skills.files_of(folder)]:
        path = folder / f.path
        if f.executable or skills.executable(path.stat().st_mode):
            executables.append(f.path)
        try:
            text = path.read_bytes().decode()
        except UnicodeDecodeError:
            binaries.append(f.path)
            continue
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for match in URL.finditer(line):
                host = match.group(1).rsplit("@", 1)[-1].lower()
                hosts.append(ScanHit(path=f.path, line=number, text=host))
            if any(_hidden(c) for c in line.lstrip(BOM) if c not in "\t"):
                hidden.append(ScanHit(path=f.path, line=number, text=_shown(line)))
            if (blob := BLOB.search(line)) is not None:
                blobs.append(ScanHit(path=f.path, line=number, text=blob.group()[:40] + "…"))
    return SkillScan(
        executables=executables[:MAX_HITS],
        binaries=binaries[:MAX_HITS],
        hosts=hosts[:MAX_HITS],
        hidden_text=hidden[:MAX_HITS],
        blobs=blobs[:MAX_HITS],
    )


def _hidden(c: str) -> bool:
    return unicodedata.category(c) == "Cf"


def _shown(line: str) -> str:
    """The line with its hidden characters made visible (U+200B → ⟨U+200B⟩), shortened."""
    shown = "".join(f"⟨U+{ord(c):04X}⟩" if _hidden(c) else c for c in line)
    return shown if len(shown) <= 200 else shown[:199] + "…"


def notes(found: SkillScan) -> str:
    """The scan, for the agents reviewing the skill (D.18): what to look at first."""
    lines = ["What handler found in its files, without a model (check these):"]
    if found.executables:
        lines.append(f"- executable files: {', '.join(found.executables)}")
    if found.binaries:
        lines.append(f"- binary files: {', '.join(found.binaries)}")
    for name, hits in (
        ("URLs (host)", found.hosts),
        ("invisible or bidirectional characters", found.hidden_text),
        ("long base64 or hex runs", found.blobs),
    ):
        if hits:
            where = ", ".join(f"{h.path}:{h.line} {h.text}" for h in hits[:30])
            lines.append(f"- {name}: {where}")
    if len(lines) == 1:
        lines.append("- nothing: no executable, binary, URL, hidden character or blob")
    return "\n".join(lines)
