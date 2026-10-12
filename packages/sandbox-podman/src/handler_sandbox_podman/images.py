"""The `image` verbs (contract A.7): build, inspect, read, tag, remove and pull images; the
egress proxy's own image, whose recipe and name are this runtime's (`proxy`, `build-proxy`).

Exit 0 when done, 1 otherwise (no such image or file, an image still in use, a failed build or
pull), with the reason on stderr. The builds and `pull` pass podman's output through.
"""

import json
import re
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime
from importlib import resources
from pathlib import Path, PurePosixPath

from handler_contracts import ImageInfo, ProxyImage

from .podman import (
    IMAGE_MOUNT_LABEL_PREFIX,
    LAUNCHER_LABEL,
    MANAGED_LABEL,
    PROXY_IMAGE,
    PodmanError,
    launcher_label,
    podman,
    quiet,
)

MAX_READ_BYTES = 1024 * 1024


def _fail(message: str) -> int:
    print(f"handler-sandbox-podman: {message}", file=sys.stderr)
    return 1


def build(
    context: Path,
    id_file: Path,
    *,
    build_args: list[str],
    pull: bool,
    no_cache: bool,
    no_intermediate: bool,
) -> int:
    """Build `context`'s Containerfile, untagged; its id goes to `id_file` (hex, no prefix)."""
    with tempfile.TemporaryDirectory() as tmp:
        iidfile = Path(tmp) / "iid"
        argv = ["podman", "build", f"--iidfile={iidfile}"]
        argv += ["--pull=always"] if pull else []
        argv += ["--no-cache"] if no_cache else []
        # a multi-stage build's stages would otherwise stay behind as untagged images
        argv += ["--layers=false"] if no_intermediate else []
        for arg in build_args:
            argv += ["--build-arg", arg]
        code = subprocess.run([*argv, str(context)], check=False).returncode
        if code != 0:
            return _fail(f"build failed (podman exit code {code})")
        id_file.write_text(iidfile.read_text().strip().removeprefix("sha256:") + "\n")
    return 0


_NANOS = re.compile(r"(\.\d{6})\d+")


def _parse_created(value: str) -> datetime:
    """Go's RFC 3339 with nanoseconds ("…T06:12:51.286668556Z") → an aware datetime."""
    return datetime.fromisoformat(_NANOS.sub(r"\1", value).replace("Z", "+00:00"))


def _info(ref: str) -> ImageInfo | None:
    try:
        data = json.loads(podman("image", "inspect", ref))[0]
    except PodmanError:
        return None
    return ImageInfo(id=data["Id"], created=_parse_created(data["Created"]))


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
    """Build the egress proxy's image from the recipe shipped here (proxy/): its base pulled
    again and no cache, for their security updates; it must start before it is tagged. The image
    it replaces is removed unless a running proxy still uses it."""
    context = resources.files("handler_sandbox_podman") / "proxy"
    with tempfile.TemporaryDirectory() as tmp, resources.as_file(context) as path:
        iidfile = Path(tmp) / "iid"
        argv = ["podman", "build", f"--iidfile={iidfile}", "--pull=always", "--no-cache"]
        code = subprocess.run([*argv, str(path)], check=False).returncode
        if code != 0:
            return _fail(f"build failed (podman exit code {code})")
        image_id = iidfile.read_text().strip().removeprefix("sha256:")
    started = subprocess.run(
        ["podman", "run", "--rm", "--network", "none", "--label", f"{MANAGED_LABEL}=1",
         "--label", f"{LAUNCHER_LABEL}={launcher_label()}", image_id, "--version"],
        capture_output=True, text=True, check=False, timeout=120,
    )  # fmt: skip
    if started.returncode != 0:
        quiet("image", "rm", image_id)
        return _fail(f"the new image does not start: {started.stderr.strip() or started.stdout}")
    print(started.stdout.strip().splitlines()[0], flush=True)  # "Mitmproxy: 12.2.3"
    old = _info(PROXY_IMAGE)
    try:
        podman("tag", image_id, PROXY_IMAGE)
    except PodmanError as e:
        return _fail(str(e))
    if old and old.id != image_id:
        quiet("image", "rm", old.id)
    print(f"{PROXY_IMAGE} switched to {image_id[:12]}")
    return 0


def read(ref: str, path: str) -> int:
    """Write the file `path` of image `ref` to stdout, without running anything in the image (an
    addon image is FROM scratch: no shell, no `cat`)."""
    try:
        container = podman(
            "create", "--label", f"{MANAGED_LABEL}=1",
            "--label", f"{LAUNCHER_LABEL}={launcher_label()}",  # sweep removes it if we die
            "--entrypoint", "/none", ref,
        )  # fmt: skip
    except PodmanError:
        return _fail(f"no image {ref}")
    try:
        return _copy_out(container, ref, path)
    finally:
        quiet("rm", "--force", container)


def _copy_out(container: str, ref: str, path: str) -> int:
    """`podman cp` streams a tar archive: for a regular file, one member named as the file;
    anything else (a folder, possibly the whole image: its members, without an entry for `/`) is
    refused at its first member, not read."""
    cp = subprocess.Popen(["podman", "cp", f"{container}:{path}", "-"], stdout=subprocess.PIPE)
    assert cp.stdout is not None
    try:
        with tarfile.open(fileobj=cp.stdout, mode="r|") as archive:
            member = archive.next()
            name = PurePosixPath(path).name
            if member is None or member.name != name or not member.isfile():
                return _fail(f"{path} in {ref} is not a regular file")
            if member.size > MAX_READ_BYTES:
                return _fail(f"{path} in {ref} is larger than {MAX_READ_BYTES} bytes")
            content = archive.extractfile(member)
            assert content is not None
            data = content.read()
    except tarfile.ReadError:  # no archive: podman found no such path
        return _fail(f"no file {path} in {ref}")
    finally:
        cp.kill()
        cp.wait()
    sys.stdout.buffer.write(data)
    return 0


def tag(source: str, target: str) -> int:
    try:
        podman("tag", source, target)
    except PodmanError as e:
        return _fail(str(e))
    return 0


def remove(image_id: str) -> int:
    """Remove an image nothing uses. Podman refuses while a container runs from it, not while one
    only mounts it (A6): that is told by the instance's label."""
    try:
        mounted = podman(
            "ps", "-a", "-q", "--filter", f"label={IMAGE_MOUNT_LABEL_PREFIX}{image_id}"
        )
    except PodmanError as e:
        return _fail(str(e))
    if mounted:
        return _fail(f"{image_id[:12]} is in use: a container mounts it")
    try:
        podman("image", "rm", image_id)
    except PodmanError as e:
        return _fail(str(e))
    return 0


def pull(ref: str) -> int:
    code = subprocess.run(["podman", "pull", "-q", ref], check=False).returncode
    return _fail(f"cannot pull {ref} (podman exit code {code})") if code else 0
