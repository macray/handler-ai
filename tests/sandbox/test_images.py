"""Contract A.7 conformance: the `image` verbs of handler-sandbox-podman (no internet needed).

The test image is FROM scratch, like an addon image: it has no shell, so `read` must not run it.
"""

import json
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from handler_contracts import ImageInfo, ProxyImage

from .conftest import requires_podman

BIN = "handler-sandbox-podman"

pytestmark = requires_podman


def image(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([BIN, "image", *args], capture_output=True, text=True, check=False)


@pytest.fixture
def built(tmp_path: Path) -> Iterator[str]:
    """An untagged FROM scratch image holding /version, built by `image build`; its id."""
    context = tmp_path / "context"
    context.mkdir()
    (context / "version").write_text("Test 1.0\nsecond line\n")
    (context / "Containerfile").write_text(
        "ARG GREETING\nFROM scratch\nARG GREETING\nCOPY version /version\n"
        'LABEL greeting="${GREETING}"\n'
    )
    id_file = tmp_path / "iid"
    result = image(
        "build", str(context), "--id-file", str(id_file),
        "--build-arg", "GREETING=hello", "--no-cache", "--no-intermediate",
    )  # fmt: skip
    assert result.returncode == 0, result.stderr
    image_id = id_file.read_text().strip()
    yield image_id
    subprocess.run(["podman", "image", "rm", "--force", image_id], capture_output=True, check=False)


def test_build_writes_the_id_and_applies_build_args(built: str) -> None:
    assert len(built) == 64 and not built.startswith("sha256:")
    label = subprocess.run(
        ["podman", "image", "inspect", "--format", "{{.Labels.greeting}}", built],
        capture_output=True, text=True, check=True,
    ).stdout.strip()  # fmt: skip
    assert label == "hello"


def test_a_failed_build_exits_1(tmp_path: Path) -> None:
    (tmp_path / "Containerfile").write_text("FROM scratch\nCOPY missing /missing\n")
    result = image("build", str(tmp_path), "--id-file", str(tmp_path / "iid"))
    assert result.returncode == 1
    assert not (tmp_path / "iid").exists()


def test_inspect_prints_the_image_info(built: str) -> None:
    result = image("inspect", built)
    assert result.returncode == 0, result.stderr
    info = ImageInfo.model_validate_json(result.stdout)
    assert info.id == built and info.created.tzinfo is not None
    missing = f"localhost/handler-ai-test-none-{uuid.uuid4().hex[:8]}"
    assert image("inspect", missing).returncode == 1


def test_read_gives_a_file_without_running_the_image(built: str) -> None:
    result = image("read", built, "/version")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "Test 1.0\nsecond line\n"
    assert image("read", built, "/missing").returncode == 1
    assert image("read", built, "/").returncode == 1  # a folder: not read


def test_tag_then_remove(built: str) -> None:
    ref = f"localhost/handler-ai-test-{uuid.uuid4().hex[:8]}:latest"
    assert image("tag", built, ref).returncode == 0
    assert json.loads(image("inspect", ref).stdout)["id"] == built
    assert image("remove", built).returncode == 0
    assert image("inspect", built).returncode == 1


def test_remove_refuses_an_image_a_container_mounts(built: str) -> None:
    """A6: podman would remove an image a container only mounts; the runtime does not."""
    container = subprocess.run(
        ["podman", "create", "--label", f"handler.image-mount.{built}=/opt/x",
         "--entrypoint", "/none", built],
        capture_output=True, text=True, check=True,
    ).stdout.strip()  # fmt: skip
    try:
        result = image("remove", built)
        assert result.returncode == 1 and "in use" in result.stderr
        assert image("inspect", built).returncode == 0
    finally:
        subprocess.run(["podman", "rm", "--force", container], capture_output=True, check=False)


def test_proxy_names_the_egress_proxy_image_and_whether_it_is_built() -> None:
    """`build-proxy` itself runs once per test session (conftest, dev_env.ensure_network_filter):
    it needs the internet, and rebuilding here would replace a proxy image other tests use."""
    result = image("proxy")
    assert result.returncode == 0, result.stderr
    found = ProxyImage.model_validate_json(result.stdout)
    assert found.ref.startswith("localhost/handler-ai-proxy:")
    present = subprocess.run(["podman", "image", "exists", found.ref], check=False)
    assert (found.image is not None) == (present.returncode == 0)
