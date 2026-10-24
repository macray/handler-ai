"""Sources (D.26) for tests: a folder committed as a git repository; the made-up source the test
daemon reads as the official one (HANDLER_OFFICIAL_SOURCE); Handler's real registry, opt-in."""

import os
import shutil
from pathlib import Path

import pytest
from dulwich import porcelain

TEST_SOURCE = Path(__file__).resolve().parents[1] / "fixtures" / "source"
# A checkout of Handler's registry, for the tests of its own items (Planner, shopify): opt-in,
# as it is not in this repository and changes without notice.
REGISTRY = Path(r) if (r := os.environ.get("HANDLER_TEST_REGISTRY")) else None
requires_registry = pytest.mark.skipif(REGISTRY is None, reason="HANDLER_TEST_REGISTRY not set")


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
