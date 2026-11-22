"""The knowledge tool's build context (D.29, G.4): the built-in tool's folder, a copy of the
`handler_smd` handlerd runs (a release's or a checkout's: the same command agents get), and its
dependencies at the versions handlerd itself runs with (the lock's, in a checkout as in a
release). Its image is built FROM the toolbox like any tool's, from this context instead of the
tool's own folder; it is rebuilt with every tool after a Handler upgrade (image_updates).

    <state>/tool-contexts/knowledge/   written before each build of it
"""

import shutil
from importlib import metadata
from pathlib import Path

import handler_smd

from .agents import KNOWLEDGE_TOOL

NAME = KNOWLEDGE_TOOL
CONTEXTS_DIR = "tool-contexts"
# handler_smd's own dependencies (packages/smd's pyproject), by their distribution names
DEPENDENCIES = ("pydantic", "markdown-it-py", "PyYAML")


def write_context(state_dir: Path, tool_dir: Path) -> Path:
    """The context, made again; returns its folder."""
    folder = state_dir / CONTEXTS_DIR / NAME
    shutil.rmtree(folder, ignore_errors=True)
    shutil.copytree(tool_dir, folder)
    package = Path(handler_smd.__file__).parent
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(package, folder / "handler_smd", ignore=ignore)
    pinned = "".join(f"{name}=={metadata.version(name)}\n" for name in DEPENDENCIES)
    (folder / "requirements.txt").write_text(pinned)
    return folder
