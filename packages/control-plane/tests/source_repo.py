"""Sources (D.26) for unit tests: a folder committed as a git repository; the made-up source the
tests read as the official one (`tests/fixtures/source/`)."""

import shutil
from pathlib import Path

from dulwich import porcelain

TEST_SOURCE = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "source"


def git_repo(folder: Path, target: Path) -> Path:
    """`folder`'s files (not its .git, nor node_modules) committed in a new repository."""
    target = target.resolve()
    shutil.copytree(
        folder, target, symlinks=True, ignore=shutil.ignore_patterns(".git", "node_modules")
    )
    with porcelain.init(str(target)) as repo:
        porcelain.add(repo, [str(p) for p in target.rglob("*") if ".git" not in p.parts])
        porcelain.commit(repo, b"source", author=b"t <t@t>", committer=b"t <t@t>")
    return target
