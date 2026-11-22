"""The knowledge tool (D.29, G.1): its image built from the context handlerd writes (a copy of
Handler's own `handler_smd`, its dependencies pinned), then its command run the way an agent
gets it: the image's files read-only at /opt/tools/knowledge, its `bin/` on PATH, the agent's
schemas at `$SMD_SCHEMAS`, in the toolbox.

Needs podman, the toolbox image and the internet (the build installs the dependencies from
PyPI)."""

import functools
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from handler_control import knowledge_tool
from handler_harness import addons

from ..sandbox.conftest import requires_internet
from ..support import dev_env

TOOLBOX = "localhost/handler-ai-toolbox:latest"
IMAGE = "localhost/handler-ai-tool-knowledge:test"
SCHEMA = '{"$id": "contacts@1", "title": "Contacts", "item": {"fields": {"email": {"type": "string", "missing": "warning"}}}}'
DOCUMENT = '{"meta": {"schema": "contacts@1"}, "title": "People", "items": [{"title": "Ada", "fields": {"email": null}}]}'


@functools.cache  # asked by every file importing it, on every worker: podman is slow under load
def toolbox_built() -> bool:
    try:
        return subprocess.run(["podman", "image", "exists", TOOLBOX], check=False).returncode == 0
    except OSError:
        return False


pytestmark = [
    pytest.mark.shared_images,
    pytest.mark.skipif(not toolbox_built(), reason=f"{TOOLBOX} missing"),
    pytest.mark.timeout(dev_env.IMAGE_TIMEOUT),
    requires_internet,
]


@pytest.fixture(scope="module")
def tool(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """The image's files, as handlerd extracts a tool's folder."""
    state = tmp_path_factory.mktemp("state")
    context = knowledge_tool.write_context(state, addons.get("knowledge").directory)
    build = ["podman", "build", "-q", "--build-arg", f"TOOLBOX_IMAGE={TOOLBOX}"]
    build += ["--build-arg", "HANDLER_VERSION=test", "-t", IMAGE, str(context)]
    built = subprocess.run(build, capture_output=True, text=True, check=False)
    assert built.returncode == 0, built.stderr
    out = tmp_path_factory.mktemp("tool")
    container = subprocess.run(
        ["podman", "create", IMAGE, "true"], capture_output=True, text=True, check=True
    ).stdout.strip()
    try:
        subprocess.run(["podman", "cp", f"{container}:/", str(out)], check=True)
    finally:
        subprocess.run(["podman", "rm", container], capture_output=True, check=False)
        subprocess.run(["podman", "rmi", IMAGE], capture_output=True, check=False)
    yield out


def run(tool: Path, schemas: Path, notes: Path, script: str) -> subprocess.CompletedProcess[str]:
    argv = ["podman", "run", "--rm", "-i", "-v", f"{tool}:/opt/tools/knowledge:ro"]
    argv += ["-v", f"{schemas}:/schemas:ro", "-v", f"{notes}:/notes", "-e", "SMD_SCHEMAS=/schemas"]
    argv += ["-e", "PATH=/usr/bin:/bin:/opt/tools/knowledge/bin", TOOLBOX, "sh", "-c", script]
    return subprocess.run(argv, input=DOCUMENT, capture_output=True, text=True, check=False)


@pytest.mark.rule("knowledge.schemas-read-only")
def test_the_tool_writes_a_document_against_the_schemas_it_is_given(
    tool: Path, tmp_path: Path
) -> None:
    """If this fails: an agent with a knowledge use has no command to write its documents, or
    the tool's python shadows the toolbox's."""
    assert sorted(p.name for p in (tool / "bin").iterdir()) == ["handler-smd", "smd"]
    assert (tool / "version").read_text() == "handler-smd test\n"
    schemas, notes = tmp_path / "schemas", tmp_path / "notes"
    schemas.mkdir()
    notes.mkdir()
    (schemas / "contacts@1.schema.json").write_text(SCHEMA)
    done = run(tool, schemas, notes, "command -v python; smd write /notes/people.md")
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines()[0] == "/usr/bin/python"  # the toolbox's
    assert "email is missing" in done.stdout
    assert (notes / "people.md").read_text() == (
        "---\nschema: contacts@1\n---\n\n# People\n\n## Ada\nemail:\n"
    )
