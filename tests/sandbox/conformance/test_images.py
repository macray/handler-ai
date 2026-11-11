"""Contract A.7 conformance, every runtime: the `image` verbs (no internet needed).

The test image is FROM scratch, like an addon image: it has no shell, so `read` must not run it.
"""

import json
import subprocess
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from handler_contracts import ImageInfo, ProxyImage

from ...support.runtimes import Runtime
from ..conftest import CURL_IMAGE, popen, spec

Image = Callable[..., subprocess.CompletedProcess[str]]


@pytest.fixture
def image(runtime: Runtime) -> Image:
    """`<runtime> image ARGS…`."""

    def call(*args: str) -> subprocess.CompletedProcess[str]:
        argv = [runtime.binary, "image", *args]
        return subprocess.run(argv, capture_output=True, text=True, check=False)

    return call


@pytest.fixture
def built(image: Image, tmp_path: Path) -> Iterator[str]:
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
    image("remove", image_id)


@pytest.mark.rule("runtime.an-image-verb-says-what-it-did")
def test_build_writes_the_id_and_applies_build_args(runtime: Runtime, built: str) -> None:
    assert len(built) == 64 and not built.startswith("sha256:")
    assert runtime.image_label(built, "greeting") == "hello"


def test_a_build_step_reads_a_folder_of_its_context_left_out_of_the_image(
    image: Image, tmp_path: Path
) -> None:
    """`RUN --mount=type=bind,source=<folder of the context>`: how a system package's files reach
    its install script in the toolbox's build without staying in the image."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "f").write_text("from the context\n")
    (tmp_path / "Containerfile").write_text(
        f"FROM {CURL_IMAGE}\nUSER root\n"
        "RUN --mount=type=bind,source=pkg,target=/run/pkg cp /run/pkg/f /seen\n"
    )
    result = image("build", str(tmp_path), "--id-file", str(tmp_path / "iid"))
    assert result.returncode == 0, result.stderr
    image_id = (tmp_path / "iid").read_text().strip()
    try:
        assert image("read", image_id, "/seen").stdout == "from the context\n"
        assert image("read", image_id, "/run/pkg/f").returncode == 1
    finally:
        image("remove", image_id)


@pytest.mark.rule("runtime.an-image-verb-says-what-it-did")
def test_a_failed_build_exits_1(image: Image, tmp_path: Path) -> None:
    (tmp_path / "Containerfile").write_text("FROM scratch\nCOPY missing /missing\n")
    result = image("build", str(tmp_path), "--id-file", str(tmp_path / "iid"))
    assert result.returncode == 1
    assert not (tmp_path / "iid").exists()


@pytest.mark.rule("runtime.an-image-verb-says-what-it-did")
def test_inspect_prints_the_image_info(image: Image, built: str) -> None:
    result = image("inspect", built)
    assert result.returncode == 0, result.stderr
    info = ImageInfo.model_validate_json(result.stdout)
    assert info.id == built and info.created.tzinfo is not None
    missing = f"localhost/handler-ai-test-none-{uuid.uuid4().hex[:8]}"
    assert image("inspect", missing).returncode == 1


@pytest.mark.rule("runtime.reads-an-image-without-running-it")
def test_read_gives_a_file_without_running_the_image(image: Image, built: str) -> None:
    result = image("read", built, "/version")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "Test 1.0\nsecond line\n"
    assert image("read", built, "/missing").returncode == 1
    assert image("read", built, "/").returncode == 1  # a folder: not read


@pytest.mark.rule("runtime.an-image-verb-says-what-it-did")
def test_tag_then_remove(image: Image, built: str) -> None:
    ref = f"localhost/handler-ai-test-{uuid.uuid4().hex[:8]}:latest"
    assert image("tag", built, ref).returncode == 0
    assert json.loads(image("inspect", ref).stdout)["id"] == built
    assert image("remove", built).returncode == 0
    assert image("inspect", built).returncode == 1


@pytest.mark.rule("runtime.an-image-verb-says-what-it-did")
def test_proxy_names_the_egress_proxy_image_and_whether_it_is_built(image: Image) -> None:
    """`build-proxy` itself runs once per test session (conftest, dev_env.ensure_network_filter):
    it needs the internet, and rebuilding here would replace a proxy image other tests use."""
    result = image("proxy")
    assert result.returncode == 0, result.stderr
    found = ProxyImage.model_validate_json(result.stdout)
    assert found.ref
    assert (found.image is not None) == (image("inspect", found.ref).returncode == 0)


@pytest.mark.rule("runtime.removes-only-an-unused-image")
def test_an_image_built_on_another_outlives_it(image: Image, built: str, tmp_path: Path) -> None:
    """Removing a base (an old toolbox) leaves the images built on it whole: their layers are
    their own. The engine may remove it (Podman does) or keep it while they exist."""
    ref = f"localhost/handler-ai-test-{uuid.uuid4().hex[:8]}:latest"
    assert image("tag", built, ref).returncode == 0
    context = tmp_path / "child"
    context.mkdir()
    (context / "Containerfile").write_text(f"FROM {ref}\nLABEL child=yes\n")
    id_file = tmp_path / "child-iid"
    assert image("build", str(context), "--id-file", str(id_file)).returncode == 0
    child = id_file.read_text().strip()
    try:
        image("remove", built)
        assert image("read", child, "/version").stdout == "Test 1.0\nsecond line\n"
    finally:
        image("remove", child)
        image("remove", ref)


@pytest.mark.rule("runtime.removes-only-an-unused-image")
def test_remove_refuses_an_image_a_sandbox_runs_from(
    runtime: Runtime, image: Image, scope: Path, tmp_path: Path
) -> None:
    (tmp_path / "Containerfile").write_text(f"FROM {CURL_IMAGE}\nLABEL in-use=yes\n")
    id_file = tmp_path / "iid"
    assert image("build", str(tmp_path), "--id-file", str(id_file)).returncode == 0
    in_use = id_file.read_text().strip()
    doc = spec(scope, ["sleep", "60"], image=in_use)
    launcher = popen(runtime.binary, doc, stdin=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 20
        while not runtime.running(doc["name"]) and time.monotonic() < deadline:
            time.sleep(0.2)
        assert runtime.running(doc["name"])
        refused = image("remove", in_use)
        assert refused.returncode == 1 and refused.stderr
    finally:
        launcher.terminate()
        launcher.wait(timeout=60)
    assert image("remove", in_use).returncode == 0  # once nothing runs from it
