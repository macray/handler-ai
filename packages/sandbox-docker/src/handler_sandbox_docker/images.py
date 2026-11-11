"""The `image` verbs (contract A.7): build, inspect, read, extract, tag, remove and pull images;
the egress proxy's own image, whose recipe and name are this runtime's (`proxy`, `build-proxy`).

Exit 0 when done, 1 otherwise (no such image or file, an image still in use, a failed build or
pull), with the reason on stderr. The builds and `pull` pass Docker's output through, BuildKit's
steps as the contract's `STEP n/m: …` lines.
"""

import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime
from importlib import resources
from pathlib import Path, PurePosixPath

from handler_contracts import ImageInfo, ProxyImage
from handler_sandbox_kit import egress, image_archive
from handler_sandbox_kit.launcher import LAUNCHER_LABEL, MANAGED_LABEL, launcher_label

from .docker import (
    HEX_ID,
    PROXY_IMAGE,
    DockerError,
    docker,
    quiet,
    reference,
)

MAX_READ_BYTES = 1024 * 1024
BUILD_BASE = "localhost/handler-ai-build-base"  # an image id given to a build, named (build)
RECIPE = "Containerfile"  # every recipe's name (A.7); Docker looks for a Dockerfile
STEP = re.compile(r"^#\d+ \[\s*(?:\S+\s+)?(\d+)/(\d+)\]\s*(.*)")  # "#5 [2/4] RUN …"


def _fail(message: str) -> int:
    print(f"handler-sandbox-docker: {message}", file=sys.stderr)
    return 1


def _build(argv: list[str]) -> int:
    """Run `docker build`, BuildKit's progress turned into the contract's STEP lines (A.7)."""
    proc = subprocess.Popen(
        ["docker", "build", "--progress", "plain", *argv],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )  # fmt: skip
    assert proc.stdout is not None
    seen: set[tuple[str, str]] = set()
    for line in proc.stdout:
        if (m := STEP.search(line)) and (m[1], m[2]) not in seen:
            seen.add((m[1], m[2]))
            print(f"STEP {m[1]}/{m[2]}: {m[3].strip()}", flush=True)
        else:
            print(line, end="", flush=True)
    return proc.wait()


def build(
    context: Path,
    id_file: Path,
    *,
    build_args: list[str],
    pull: bool,
    no_cache: bool,
    no_intermediate: bool,
) -> int:
    """Build `context`'s Containerfile, untagged; its id goes to `id_file` (hex, no prefix).
    `no_intermediate` changes nothing: BuildKit keeps no image of a multi-stage build's stages.
    An image id given as a build argument (a harness's TOOLBOX_IMAGE) is named for the build:
    BuildKit's FROM takes names only, it looks `sha256:<id>` up on Docker Hub. The name stays:
    it is the only one of an image not switched to yet (removing it would remove the image), and
    `remove` takes it with the image."""
    del no_intermediate
    with tempfile.TemporaryDirectory() as tmp:
        iidfile = Path(tmp) / "iid"
        argv = [f"--iidfile={iidfile}", "--file", str(context / RECIPE)]
        argv += ["--pull"] if pull else []
        argv += ["--no-cache"] if no_cache else []
        try:
            for arg in build_args:
                name, _, value = arg.partition("=")
                if HEX_ID.match(hex_id := value.removeprefix("sha256:")):
                    docker("tag", reference(hex_id), value := f"{BUILD_BASE}:{hex_id}")
                argv += ["--build-arg", f"{name}={value}"]
        except DockerError as e:
            return _fail(str(e))
        code = _build([*argv, str(context)])
        if code != 0:
            return _fail(f"build failed (docker exit code {code})")
        id_file.write_text(iidfile.read_text().strip().removeprefix("sha256:") + "\n")
    return 0


_NANOS = re.compile(r"(\.\d{6})\d+")


def _parse_created(value: str) -> datetime:
    """Go's RFC 3339 with nanoseconds ("…T06:12:51.286668556Z") → an aware datetime."""
    return datetime.fromisoformat(_NANOS.sub(r"\1", value).replace("Z", "+00:00"))


def _info(ref: str) -> ImageInfo | None:
    try:
        data = json.loads(docker("image", "inspect", reference(ref)))[0]
    except DockerError:
        return None
    # the id as Podman gives it, and the build's id file: hex, without "sha256:"
    image_id = data["Id"].removeprefix("sha256:")
    return ImageInfo(id=image_id, created=_parse_created(data["Created"]))


def inspect(ref: str) -> int:
    info = _info(ref)
    if info is None:
        return _fail(f"no image {ref}")
    print(info.model_dump_json(by_alias=True))
    return 0


def proxy() -> int:
    """The egress proxy's image (A.3), built or not."""
    found = ProxyImage(ref=PROXY_IMAGE, image=_info(PROXY_IMAGE))
    print(found.model_dump_json(by_alias=True, exclude_none=True))
    return 0


def build_proxy() -> int:
    """Build the egress proxy's image from the recipe shipped in the kit (proxy/): its base
    pulled again and no cache, for their security updates; it must start before it is tagged.
    The image it replaces is removed unless a running proxy still uses it."""
    context = egress.proxy_dir()
    with tempfile.TemporaryDirectory() as tmp, resources.as_file(context) as path:
        iidfile = Path(tmp) / "iid"
        argv = [f"--iidfile={iidfile}", "--pull", "--no-cache", "--file", str(path / RECIPE)]
        code = _build([*argv, str(path)])
        if code != 0:
            return _fail(f"build failed (docker exit code {code})")
        image_id = iidfile.read_text().strip()
    started = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "--label", f"{MANAGED_LABEL}=1",
         "--label", f"{LAUNCHER_LABEL}={launcher_label()}", image_id, "--version"],
        capture_output=True, text=True, check=False, timeout=120,
    )  # fmt: skip
    if started.returncode != 0:
        quiet("image", "rm", image_id)
        return _fail(f"the new image does not start: {started.stderr.strip() or started.stdout}")
    print(started.stdout.strip().splitlines()[0], flush=True)  # "Mitmproxy: 12.2.3"
    old = _info(PROXY_IMAGE)
    try:
        docker("tag", image_id, PROXY_IMAGE)
    except DockerError as e:
        return _fail(str(e))
    if old and old.id != image_id:
        quiet("image", "rm", old.id)
    print(f"{PROXY_IMAGE} switched to {image_id.removeprefix('sha256:')[:12]}")
    return 0


def _created(ref: str) -> str:
    """A container of `ref`, never started (an addon image is FROM scratch: no shell), labelled
    so that `sweep` removes it if we die. Raises DockerError."""
    return docker(
        "create", "--label", f"{MANAGED_LABEL}=1",
        "--label", f"{LAUNCHER_LABEL}={launcher_label()}",
        "--entrypoint", "/none", reference(ref),
    )  # fmt: skip


def read_bytes(ref: str, path: str) -> bytes:
    """The regular file `path` of image `ref`, without running anything in it. Raises
    DockerError: no such image or file, not a regular file, too large."""
    container = _created(ref)
    try:
        return _copy_out(container, ref, path)
    finally:
        quiet("rm", "--force", container)


def _copy_out(container: str, ref: str, path: str) -> bytes:
    """`docker cp` streams a tar archive: for a regular file, one member named as the file;
    anything else (a folder, possibly the whole image) is refused at its first member."""
    cp = subprocess.Popen(
        ["docker", "cp", f"{container}:{path}", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    assert cp.stdout is not None
    try:
        with tarfile.open(fileobj=cp.stdout, mode="r|") as archive:
            member = archive.next()
            name = PurePosixPath(path).name
            if member is None or member.name != name or not member.isfile():
                raise DockerError(f"{path} in {ref} is not a regular file")
            if member.size > MAX_READ_BYTES:
                raise DockerError(f"{path} in {ref} is larger than {MAX_READ_BYTES} bytes")
            content = archive.extractfile(member)
            assert content is not None
            return content.read()
    except tarfile.ReadError:  # no archive: docker found no such path
        raise DockerError(f"no file {path} in {ref}") from None
    finally:
        cp.kill()
        cp.wait()


def read(ref: str, path: str) -> int:
    """Write the file `path` of image `ref` to stdout."""
    try:
        data = read_bytes(ref, path)
    except DockerError as e:
        return _fail(str(e) if " in " in str(e) else f"no image {ref}")
    sys.stdout.buffer.write(data)
    return 0


def extract(ref: str, path: str, folder: Path) -> int:
    """Copy the folder `path` of image `ref` to `folder` (made here: it must not exist), its
    files the host user's, from its layers without running it (the kit's image_archive): a copy
    out of a container would add what Docker puts in every one (`/.dockerenv`, `/dev`…)."""
    if folder.exists() or not folder.parent.is_dir():
        return _fail(f"{folder} exists, or its parent folder does not")
    with tempfile.TemporaryDirectory() as tmp:
        saved = Path(tmp) / "image.tar"
        try:
            docker("image", "save", "--output", str(saved), reference(ref), timeout=1800)
        except DockerError:
            return _fail(f"no image {ref}")
        folder.mkdir()
        try:
            image_archive.unpack(saved, path, folder)
        except image_archive.ImageArchiveError as e:
            shutil.rmtree(folder, ignore_errors=True)
            return _fail(str(e))
    if not any(folder.iterdir()):
        folder.rmdir()
        return _fail(f"no folder {path} in {ref}")
    return 0


def tag(source: str, target: str) -> int:
    try:
        docker("tag", reference(source), target)
    except DockerError as e:
        return _fail(str(e))
    return 0


def remove(image_id: str) -> int:
    """Remove an image nothing uses (Docker refuses while a container runs from it)."""
    try:
        docker("image", "rm", reference(image_id))
    except DockerError as e:
        return _fail(str(e))
    return 0


def pull(ref: str) -> int:
    code = subprocess.run(["docker", "pull", "-q", ref], check=False).returncode
    return _fail(f"cannot pull {ref} (docker exit code {code})") if code else 0
