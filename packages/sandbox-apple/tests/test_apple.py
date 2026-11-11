"""handler-sandbox-apple without a Mac: what it asks `container` for, what it refuses (A1), how it
reads `container`'s output. Run where `container` is: the conformance suite (as `[apple]`)."""

import gzip
import hashlib
import io
import json
import os
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from handler_contracts import HostFolder, SandboxSpec
from handler_sandbox_apple import check, container, images, launch
from handler_sandbox_kit import given_files
from handler_sandbox_kit.launch import Instance, UnenforceableError, check_enforceable
from handler_sandbox_kit.launcher import launcher_label


def spec(scope: Path, **overrides: Any) -> SandboxSpec:
    doc: dict[str, Any] = {
        "apiVersion": "handler.sandbox/v2",
        "name": "handler-test-apple",
        "image": "localhost/handler-ai-toolbox:latest",
        "argv": ["claude-agent-acp"],
        "env": {"A": "1"},
        "workdir": str(scope),
        "home": "/home/agent",
        "workFolder": {"path": str(scope)},
        "files": [{"target": "/home/agent/.app/conf.toml", "content": "a = 1\n", "mode": "0444"}],
        "network": {
            "mode": "filtered",
            "allow": ["api.anthropic.com:443"],
            "enforcement": "enforce",
        },
    }
    return SandboxSpec.model_validate(doc | overrides)


class Sandbox:
    """An Instance with its folders under tmp_path, and Apple's methods for it."""

    def __init__(self, spec: SandboxSpec) -> None:
        self.instance = Instance(spec)
        self.instance.dir.mkdir(parents=True, exist_ok=True)
        self.apple = launch.Apple()

    @property
    def spec(self) -> SandboxSpec:
        return self.instance.spec

    @property
    def dir(self) -> Path:
        return self.instance.dir

    def args(self) -> list[str]:
        """What the kit gives `container create`, its filter not started."""
        i, apple, spec = self.instance, self.apple, self.spec
        start = [*apple.host_user(i), *apple.isolation(i), *apple.network_args(i)]
        needs = [
            *apple.work_folder(spec.work_folder, i),
            *(a for n in spec.folders for a in apple.folder(n, i)),
            *(a for n in spec.caches for a in apple.cache(n, i)),
            *(a for n in spec.kept_files for a in apple.kept_file(n, i)),
            *(a for n in spec.files for a in apple.file(n, i)),
            *(a for n in spec.tools for a in apple.tool(n, i)),
        ]
        return [*start, *apple.home(i), *needs, *apple.resources(i)]


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Sandbox:
    """A filtered sandbox, the image's entrypoint none."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    monkeypatch.setattr(launch, "image_info", lambda ref: {"config": {"Entrypoint": None}})
    launch.relay_dir().mkdir(parents=True)
    (launch.relay_dir() / "handler-relay").touch()  # exported by `image build-proxy`
    scope = tmp_path / "scope"
    scope.mkdir()
    one = Sandbox(spec(scope))
    one.instance.filter_dir.mkdir()
    return one


def test_a_filtered_sandbox_has_no_network_and_runs_through_the_relay(sandbox: Sandbox) -> None:
    args = sandbox.args()
    for expected in (
        ["--network", "none", "--no-dns"],  # loopback only
        ["--read-only", "--cap-drop", "ALL"],  # A3
        ["--uid", "0", "--gid", "0"],  # the relay becomes the user
        ["--kernel-arg", "sysctl.user.max_user_namespaces=0"],  # no capabilities regained
        ["--kernel-arg", "sysctl.kernel.unprivileged_bpf_disabled=1"],
        ["--kernel-arg", "sysctl.kernel.io_uring_disabled=2"],
        ["--kernel-arg", "sysctl.kernel.dmesg_restrict=1"],
        ["--kernel-arg", "sysctl.kernel.kptr_restrict=2"],
        ["--volume", f"{launch.socket_path(sandbox.spec.name, 'relay')}:{launch.HOST_SOCKET}"],
        ["--tmpfs", "/tmp"],
    ):
        assert any(args[i : i + len(expected)] == expected for i in range(len(args))), expected
    assert f"type=bind,source={launch.relay_dir()},target={launch.RELAY_BIN},readonly" in args
    added = [args[i + 1] for i, a in enumerate(args) if a == "--cap-add"]
    assert sorted(added) == sorted(launch.RELAY_CAPS)  # for the relay to drop them
    assert "--publish-socket" not in args
    # a read-only file: in the instance's read-only folder, and a link to it in the home, a
    # folder of the instance (`container` mounts folders only)
    run = sandbox.dir / "own" / "0"
    assert f"type=bind,source={run},target={launch.HANDLER_RUN},readonly" in args
    assert (run / "files" / "0" / "conf.toml").read_text() == "a = 1\n"
    assert not (sandbox.dir / "own" / "1").exists()  # /opt/handler: nothing in it
    home = sandbox.dir / "home"
    assert f"type=bind,source={home},target=/home/agent" in args
    link = home / ".app" / "conf.toml"
    assert os.readlink(link) == f"{launch.FILES}/0/conf.toml"
    assert not [a for a in args if "conf.toml" in a]  # no mount of its own
    scope = sandbox.spec.workdir
    assert f"type=bind,source={scope},target={scope}" in args  # the same path (A2)
    command = sandbox.apple.command(sandbox.spec)
    assert command[:3] == ["--entrypoint", f"{launch.RELAY_BIN}/handler-relay", sandbox.spec.image]
    assert command[-2:] == ["--", "claude-agent-acp"]
    assert f"tcp:{launch.EGRESS_ADDRESS}=egress" in command
    uid = f"{os.getuid()}:{os.getgid()}"
    assert command[3:7] == ["--user", uid, "--host", launch.HOST_SOCKET]


def test_an_open_sandbox_without_secrets_has_the_relay_only_become_the_user(
    sandbox: Sandbox,
) -> None:
    open_one = Sandbox(
        spec(Path(sandbox.spec.workdir), name="handler-test-open", network={"mode": "open"})
    )
    assert not open_one.instance.filtered
    open_one.apple.host_user(open_one.instance)
    assert open_one.apple.network_args(open_one.instance) == []
    relay = f"{launch.RELAY_BIN}/handler-relay"
    uid = f"{os.getuid()}:{os.getgid()}"
    assert open_one.apple.command(open_one.spec) == [
        "--entrypoint", relay, open_one.spec.image, "--user", uid, "--", "claude-agent-acp"
    ]  # fmt: skip


def test_a_sandbox_of_an_image_id_runs_it_by_its_name(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A build writes an id, and handlerd checks what it built in sandboxes of that id;
    `container` refuses an id as a reference, so the image is given by one of its names."""
    image_id = "ab" * 32
    listed = [
        {
            "id": image_id,
            "configuration": {"name": "localhost/handler-ai-build:1"},
            # a label of its base (curlimages/curl's), no name of the image
            "variants": [{"config": {"config": {"Labels": {"name": "curl-linux-arm64:8.11.1"}}}}],
        }
    ]
    monkeypatch.setattr(container, "container", lambda *args, **kwargs: json.dumps(listed))
    assert container.names(image_id) == ["localhost/handler-ai-build:1"]
    by_id = Sandbox(spec(Path(sandbox.spec.workdir), name="handler-test-id", image=image_id))
    by_id.apple.host_user(by_id.instance)
    assert by_id.apple.command(by_id.spec)[2] == "localhost/handler-ai-build:1"


@pytest.mark.parametrize(
    ("status", "seen"),
    [  # `inspect`'s `status`, recorded on 1.7.1
        ({"networks": [], "state": "stopped"}, "waiting"),  # created, not started
        ({"networks": [], "startedDate": "2026-11-09T09:37:21Z", "state": "running"}, "running"),
        ({"networks": [], "startedDate": "2026-11-09T09:37:21Z", "state": "stopped"}, "running"),
        (None, "gone"),
    ],
)
def test_an_ended_sandbox_is_not_one_waiting_for_its_attach(
    monkeypatch: pytest.MonkeyPatch, status: dict[str, Any] | None, seen: str
) -> None:
    """Both are `stopped`: a `tty` process ending before the launcher looked would have it wait
    for an `attach` that already came, then fail (66)."""
    doc = "" if status is None else json.dumps([{"id": "x", "status": status}])
    monkeypatch.setattr(launch, "container", lambda *args, **kwargs: doc)
    assert launch.Apple().status("x") == seen


def test_a_terminal_s_exit_code_is_the_one_its_attach_got(
    monkeypatch: pytest.MonkeyPatch, sandbox: Sandbox
) -> None:
    """`inspect` keeps no exit code: `attach` leaves it in the instance folder."""
    ended = {"startedDate": "2026-11-09T09:37:21Z", "state": "stopped"}
    monkeypatch.setattr(launch, "container", lambda *a, **k: json.dumps([{"status": ended}]))
    sandbox.apple.attached(sandbox.dir, 5)
    assert sandbox.apple.wait(sandbox.instance) == 5


@pytest.mark.rule("runtime.removes-only-an-unused-image")
@pytest.mark.parametrize(("state", "refused"), [("running", True), ("stopped", False)])
def test_remove_refuses_an_image_a_running_container_runs_from(
    monkeypatch: pytest.MonkeyPatch, state: str, refused: bool
) -> None:
    """`container image delete` would only delete its names: refused before."""
    image_id = "cd" * 32
    listed = {
        "image": [{"id": image_id, "configuration": {"name": "localhost/handler-ai-build:2"}}],
        "list": [
            {
                "configuration": {"image": {"descriptor": {"digest": f"sha256:{image_id}"}}},
                "status": {"state": state},
            }
        ],
    }
    deleted: list[tuple[str, ...]] = []

    def run(*args: str, **kwargs: Any) -> str:
        if args[:2] == ("image", "delete"):
            deleted.append(args[2:])
        return json.dumps(listed.get(args[0], []))

    monkeypatch.setattr(container, "container", run)
    monkeypatch.setattr(images, "container", run)
    assert images.remove(image_id) == (1 if refused else 0)
    assert deleted == ([] if refused else [("localhost/handler-ai-build:2",)])


@pytest.mark.rule("runtime.a-limit-is-applied-or-said")
@pytest.mark.parametrize(
    ("asked", "given", "said"),
    [("64m", "200m", True), ("1000k", "200m", True), ("200m", "200m", False), ("1g", "1g", False)],
)
def test_a_memory_limit_below_the_minimum_is_raised_to_it(
    capsys: pytest.CaptureFixture[str], asked: str, given: str, said: bool
) -> None:
    """`container` refuses a virtual machine under 200 MiB: the sandbox would not start."""
    assert launch.memory_arg(asked) == given
    assert ("raised to 200m" in capsys.readouterr().err) == said


def test_handler_s_own_folders_hold_their_files_and_mount_points(sandbox: Sandbox) -> None:
    """The paste helper and handler-sandbox-env at their paths, the paste folder's mount point:
    no image has these folders, the instance's are mounted read-only before what is in them."""
    paste = Path(sandbox.spec.workdir).parent / "paste"
    paste.mkdir()
    tools = [
        {"target": "/run/handler/bin/xclip", "content": "#!/bin/sh\n"},
        {"target": "/opt/handler/bin/handler-sandbox-env", "content": "#!/bin/sh\n"},
    ]
    folders = [{"source": str(paste), "target": "/run/handler/paste", "writable": False}]
    one = Sandbox(spec(Path(sandbox.spec.workdir), name="handler-test-own", tools=tools,
                       folders=folders))  # fmt: skip
    args = one.args()
    run, opt = one.dir / "own" / "0", one.dir / "own" / "1"
    assert (run / "bin" / "xclip").read_text() == "#!/bin/sh\n"
    assert (opt / "bin" / "handler-sandbox-env").stat().st_mode & 0o777 == 0o555
    assert (run / "paste").is_dir()
    order = [a for a in args if a.startswith("type=bind")]
    assert order.index(f"type=bind,source={run},target=/run/handler,readonly") < order.index(
        f"type=bind,source={paste},target=/run/handler/paste,readonly"
    )
    assert f"type=bind,source={opt},target=/opt/handler,readonly" in order


def test_a_kept_file_must_be_alone_in_its_folder(tmp_path: Path) -> None:
    """U2b: its folder is mounted, so it must hold nothing else (A.1), else refused (A1)."""
    (tmp_path / "login").mkdir()
    login = tmp_path / "login" / "credential"
    login.write_text("{}")
    kept = [{"source": str(login), "target": "/home/agent/.x/auth.json"}]
    check_enforceable(launch.Apple(), spec(tmp_path, keptFiles=kept))
    (tmp_path / "login" / "other").write_text("not the sandbox's")
    with pytest.raises(UnenforceableError, match="not alone in its folder"):
        check_enforceable(launch.Apple(), spec(tmp_path, keptFiles=kept))


def test_a_kept_file_is_its_folder_mounted_and_a_link(sandbox: Sandbox) -> None:
    folder = Path(sandbox.spec.workdir).parent / "config_json"
    folder.mkdir()
    (folder / "config_json").write_text("{}")
    kept = [{"source": str(folder / "config_json"), "target": "/home/agent/.claude.json"}]
    one = Sandbox(spec(Path(sandbox.spec.workdir), name="handler-test-kept", keptFiles=kept))
    args = one.args()
    assert f"type=bind,source={folder},target={launch.STATE}/0" in args
    assert (one.dir / "own" / "0" / "state" / "0").is_dir()  # its mount point
    link = one.dir / "home" / ".claude.json"
    assert os.readlink(link) == f"{launch.STATE}/0/config_json"
    assert not [a for a in args if a.endswith("target=/home/agent/.claude.json")]


@pytest.mark.rule("runtime.declares-only-what-it-gives")
@pytest.mark.parametrize(
    ("change", "said"),
    [
        ({"isolation": "nested"}, ": nested "),
        ({"isolation": "privileged"}, ": privileged "),
        ({"display": True}, ": display "),
    ],
)
def test_what_it_cannot_give_yet_is_refused(
    tmp_path: Path, change: dict[str, Any], said: str
) -> None:
    with pytest.raises(UnenforceableError, match=said):
        check_enforceable(launch.Apple(), spec(tmp_path, **change))


@pytest.mark.rule("runtime.an-image-verb-says-what-it-did")
def test_buildkit_progress_becomes_steps(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    lines = [
        "#1 [internal] load build definition\n",
        "#5 [2/3] RUN pacman -Syu\n",
        "#5 0.2 resolving dependencies...\n",
        "#5 3.1 [ 1/33] curl-0:8.18.0-14.fc44.aarch64 100%\n",  # dnf's own progress
        "#6 [stage-1 3/3] COPY bin /bin\n",
        "#7 [linux/arm64 1/3] FROM docker.io/library/fedora:latest\n",
    ]

    class Proc:
        stdout = iter(lines)

        def wait(self) -> int:
            return 0

    monkeypatch.setattr(images.subprocess, "Popen", lambda *a, **k: Proc())
    assert images._build(["."]) == 0
    out = capsys.readouterr().out.splitlines()
    assert "STEP 2/3: RUN pacman -Syu" in out and "STEP 3/3: COPY bin /bin" in out
    assert "STEP 1/3: FROM docker.io/library/fedora:latest" in out
    assert "#5 0.2 resolving dependencies..." in out
    assert not [line for line in out if line.startswith("STEP 1/33")]


def oci_archive(path: Path, layers: list[dict[str, bytes]]) -> None:
    """An OCI image archive as `image save` writes it: index → manifest → gzipped layers."""
    blobs: dict[str, bytes] = {}

    def add(data: bytes) -> str:
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        blobs[digest] = data
        return digest

    layer_digests = []
    for files in layers:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as t:
            for name, data in files.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                t.addfile(info, io.BytesIO(data))
        layer_digests.append(add(gzip.compress(buf.getvalue())))
    manifest = add(json.dumps({"layers": [{"digest": d} for d in layer_digests]}).encode())
    index = json.dumps({"manifests": [{"digest": manifest}]}).encode()
    with tarfile.open(path, "w") as out:
        for name, data in [("index.json", index)] + [
            (f"blobs/{d.replace(':', '/')}", b) for d, b in blobs.items()
        ]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            out.addfile(info, io.BytesIO(data))


@pytest.mark.rule("runtime.reads-an-image-without-running-it")
def test_read_takes_a_file_from_the_topmost_layer_having_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    def save(*args: str, **_: Any) -> str:
        oci_archive(Path(args[-1]), [{"version": b"1\n", "other": b"x"}, {"./version": b"2\n"}])
        return ""

    monkeypatch.setattr(images, "container", save)
    assert images.read("localhost/addon:1", "/version") == 0
    assert capsysbinary.readouterr().out == b"2\n"
    assert images.read("localhost/addon:1", "/missing") == 1


# `container`'s documents as 1.7.1 writes them (their layout is not documented), one test
# per field this runtime reads; re-recorded on each release (personal paths replaced)
RECORDED = Path(__file__).parent / "recorded" / "1.7.1"
PI_ID = "0f78ff7803d2e63667ce85416cc480846aade0ba5bb5196893702e66a8bc4723"


def recorded(name: str) -> Any:
    return json.loads((RECORDED / name).read_text())


def answering(
    monkeypatch: pytest.MonkeyPatch, module: Any, docs: dict[tuple[str, ...], str]
) -> None:
    """`container ARGS…` answers the recorded document named for its first arguments."""

    def run(*args: str, **kwargs: Any) -> str:
        name = next((n for prefix, n in docs.items() if args[: len(prefix)] == prefix), None)
        return (RECORDED / name).read_text() if name else ""

    monkeypatch.setattr(module, "container", run)


def test_a_sandbox_s_labels_are_read_from_list() -> None:
    """sweep's labels: which launcher made it, its sandbox."""
    filt, agent = recorded("list.json")
    assert container.labels_of(agent)[launch.SANDBOX_LABEL] == agent["configuration"]["id"]
    assert container.labels_of(filt)[launch.MANAGED_LABEL] == "1"
    assert container.labels_of(filt)[launch.LAUNCHER_LABEL].startswith("13087:")


def test_the_image_a_running_container_runs_from_is_read_from_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answering(monkeypatch, container, {("list",): "list.json"})
    assert container.running_from(PI_ID)
    assert not container.running_from("ab" * 32)


@pytest.mark.parametrize(
    ("doc", "seen"),
    [
        ("inspect-created.json", "waiting"),
        ("inspect-running.json", "running"),
        ("inspect-ended.json", "running"),  # ended: as Docker's `exited`
    ],
)
def test_a_sandbox_s_state_is_read_from_inspect(
    monkeypatch: pytest.MonkeyPatch, doc: str, seen: str
) -> None:
    answering(monkeypatch, launch, {("inspect",): doc})
    assert launch.Apple().status("x") == seen


def test_an_image_s_id_names_and_creation_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """The id is the one `image list` gives, by which `container` names it."""
    info = recorded("image-inspect.json")[0]
    assert container.image_id(info) == PI_ID
    assert images._created(info).isoformat() == "2026-11-09T12:55:47.240735+00:00"
    answering(monkeypatch, container, {("image", "list"): "image-list.json"})
    assert sorted(container.names(PI_ID)) == [
        "localhost/handler-ai-build:0d67d927f6cc",
        "localhost/handler-ai-pi:latest",
    ]


@pytest.mark.parametrize(
    ("doc", "path", "entrypoint"),
    [
        ("image-inspect.json", "/home/agent/.local/bin:/usr/local/bin:/usr/bin:/usr/sbin", []),
        (
            "image-inspect-pulled.json",
            "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            ["/entrypoint.sh"],
        ),
    ],
)
def test_an_image_s_env_and_entrypoint_are_this_mac_s_variant(
    monkeypatch: pytest.MonkeyPatch, doc: str, path: str, entrypoint: list[str]
) -> None:
    """A pulled image lists every platform's config, linux/386's first: linux/arm64's is read."""
    info = recorded(doc)[0]
    assert container.variant(info)["platform"] == {"architecture": "arm64", "os": "linux"}
    assert container.image_env(info)["PATH"] == path
    monkeypatch.setattr(launch, "image_info", lambda ref: info)
    assert launch.Apple()._entrypoint("x") == entrypoint


def test_the_mac_s_address_is_read_from_the_default_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc = recorded("network-inspect.json")
    doc[0]["status"]["ipv4Gateway"] = "192.168.70.1"  # another subnet than the default
    monkeypatch.setattr(launch, "container", lambda *args, **kwargs: json.dumps(doc))
    assert launch.host_address() == "192.168.70.1"


def test_sockets_have_short_paths() -> None:
    """macOS: a Unix socket's path is at most 104 bytes."""
    path = container.socket_path("handler-" + "a" * 40 + "-" + "b" * 8, "filter")
    assert len(str(path)) < 104


def test_a_socket_path_too_long_is_said(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Apple's relay would fail to it only in its log; the launcher says it."""
    monkeypatch.setattr(container, "short_dir", lambda: tmp_path / ("d" * 100))
    with pytest.raises(container.ContainerError, match="too long for a socket"):
        container.socket_path("handler-x", "relay")


@pytest.mark.parametrize(
    ("macos", "machine", "ok", "says"),
    [
        ("26.6.2", "arm64", True, None),
        ("15.7.1", "arm64", False, "needs macOS 26: update macOS, or use Docker Desktop"),
        ("26.1", "x86_64", False, "needs a Mac with Apple silicon; use Docker Desktop"),
    ],
)
def test_check_says_what_to_do_on_a_mac_apple_container_cannot_use(
    macos: str, machine: str, ok: bool, says: str | None
) -> None:
    """macOS 15 (or an Intel Mac) is refused with what to do, Docker as the other way."""
    item = check.macos_item(macos, machine)
    assert item.ok is ok and item.required
    assert (says or "") in item.detail and ("handler runtime use docker" in item.detail) is not ok


@pytest.mark.rule("runtime.removes-only-an-unused-image")
def test_a_later_build_prunes_old_unused_images_only_a_build_tag_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On 1.7.1 an image without a name is deleted, so each build keeps its tag; one
    left with only that tag (replaced while a sandbox ran from it, its builder killed) goes at a
    later build, once a day old, never while used, nor another builder's recent one."""
    now = datetime(2026, 11, 9, 12, tzinfo=UTC)

    def image(id_: str, name: str, created: datetime) -> dict[str, Any]:
        return {"id": id_, "configuration": {"name": name, "creationDate": created.isoformat()}}

    old, recent = now - timedelta(days=2), now - timedelta(hours=1)
    listed = [
        image("a" * 64, "localhost/handler-ai-build:1", old),  # pruned
        image("b" * 64, "localhost/handler-ai-build:2", old),  # a sandbox runs from it
        image("c" * 64, "localhost/handler-ai-build:3", recent),  # another builder's, unswitched
        image("d" * 64, "localhost/handler-ai-build:4", old),  # the current one
        image("d" * 64, "localhost/handler-ai-pi:latest", old),
        image("e" * 64, "localhost/handler-ai-build:5", old),  # just built (cached: old)
        image("f" * 64, "quay.io/curl/curl:8.11.1", old),
    ]
    deleted: list[tuple[str, ...]] = []

    def run(*args: str, **kwargs: Any) -> str:
        return json.dumps(listed) if args[:2] == ("image", "list") else ""

    monkeypatch.setattr(images, "container", run)
    monkeypatch.setattr(images, "quiet", lambda *args: deleted.append(args))
    monkeypatch.setattr(images, "running_from", lambda image_id: image_id == "b" * 64)
    images.prune_builds(keep="e" * 64, now=now)
    assert deleted == [("image", "delete", "localhost/handler-ai-build:1")]


def test_a_folder_in_a_place_macos_protects_is_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Apple container's helper waits for macOS's dialog about it, then fails once refused."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    icloud = tmp_path / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "notes"
    for folder in (icloud, tmp_path / "Documents" / "site", tmp_path / "code" / "app"):
        folder.mkdir(parents=True)
    (tmp_path / "code" / "linked").symlink_to(tmp_path / "Documents" / "site")
    doc = spec(tmp_path / "code" / "app")
    doc = doc.model_copy(
        update={
            "folders": [
                HostFolder(source=str(icloud), target="/notes", writable=False),
                HostFolder(source=str(tmp_path / "code" / "linked"), target="/l", writable=True),
            ]
        }
    )
    assert launch.protected(doc) == [
        (str(icloud), "iCloud Drive"),
        (str(tmp_path / "code" / "linked"), "Documents"),
    ]
    assert launch.protected(spec(tmp_path / "code" / "app")) == []


@pytest.mark.parametrize(
    ("in_icloud", "status", "says"),
    [(True, "waiting", True), (True, "running", False), (False, "waiting", False)],
)
def test_a_start_refused_a_protected_folder_says_what_to_do(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    in_icloud: bool,
    status: str,
    says: bool,
) -> None:
    """Refused, the start fails at once with Apple's words, naming no folder: the launcher names
    it, and where to allow it. A sandbox that ran, or no such folder: its own exit code."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    folder = tmp_path / ("Library/Mobile Documents/com~apple~CloudDocs" if in_icloud else "code")
    folder.mkdir(parents=True)
    apple = launch.Apple()
    monkeypatch.setattr(apple, "status", lambda name: status)
    monkeypatch.setattr(launch, "service_running", lambda: True)
    why = apple.start_failed(Instance(spec(folder)))
    assert (why is not None) is says
    if why:
        assert str(folder) in why and "iCloud Drive" in why and "Files & Folders" in why


@pytest.mark.parametrize("ran", [True, False])
def test_a_sandbox_apple_s_service_stopped_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ran: bool
) -> None:
    """`container system stop` ends every VM, the agent's code 137: said, before it started or
    after (a session it ended), with how to start the service again."""
    monkeypatch.setattr(launch, "service_running", lambda: False)
    apple = launch.Apple()
    monkeypatch.setattr(apple, "status", lambda name: "running" if ran else "waiting")
    why = apple.start_failed(Instance(spec(tmp_path)))
    assert why is not None and "container system start" in why


@pytest.mark.rule("sandbox.sweep-spares-live-launchers")
def test_a_launch_first_sweeps_what_dead_launchers_left(
    monkeypatch: pytest.MonkeyPatch, sandbox: Sandbox
) -> None:
    """A sandbox Apple's stopped service kept its launcher from deleting is gone at the next
    launch, not only at handlerd's next start; a live launcher's is kept."""
    listed = [
        {"configuration": {"labels": {
            launch.MANAGED_LABEL: "1", launch.SANDBOX_LABEL: name, launch.LAUNCHER_LABEL: owner,
        }}}
        for name, owner in (("handler-dead", "1:0"), ("handler-live", launcher_label()))
    ]  # fmt: skip
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(launch, "containers", lambda: listed)
    monkeypatch.setattr(launch, "quiet", lambda *args: calls.append(args))
    monkeypatch.setattr(launch, "container", lambda *args, **kwargs: calls.append(args) or "")
    monkeypatch.setattr(launch, "protected", lambda spec: [])
    sandbox.apple.host_user(sandbox.instance)
    sandbox.apple.create(sandbox.instance, [])
    assert calls[:2] == [
        ("delete", "--force", "handler-dead"),
        ("delete", "--force", "handler-dead-proxy"),
    ]
    assert calls[2][0] == "create" and not any("handler-live" in c for c in calls)


@pytest.mark.rule("sandbox.its-sockets-cross-as-declared")
def test_a_socket_folder_is_the_vm_s_own_its_sockets_through_the_relay(
    sandbox: Sandbox, tmp_path: Path
) -> None:
    """A socket in a shared folder reaches neither side on Apple: the folder is a tmpfs of the
    VM's, each socket a relay listener (reached) or a socket the launcher serves (served), with
    or without network (`none` too).
    If this fails: no app's backend runs on Apple container, or it reaches what it never named."""
    source = tmp_path / "run"
    folder = {
        "source": str(source), "target": "/run/handler-app",
        "serves": ["app.sock"], "reaches": ["handler.sock"],
    }  # fmt: skip
    scope = Path(sandbox.spec.workdir)
    one = Sandbox(
        spec(scope, name="handler-test-sockets", network={"mode": "none"}, socketFolders=[folder])
    )
    i, apple = one.instance, one.apple
    apple.host_user(i)
    args = [*apple.network_args(i), *apple.socket_folder(one.spec.socket_folders[0], i)]
    assert args[:2] == ["--network", "none"]
    host = launch.socket_path(one.spec.name, "relay")
    assert ["--volume", f"{host}:{launch.HOST_SOCKET}", "--tmpfs", "/run/handler-app"] == args[3:]
    assert not [a for a in args if str(source) in a]  # never mounted
    command = apple.command(one.spec)
    assert "unix:/run/handler-app/handler.sock=s0/handler.sock" in command
    assert "unix:/run/handler-app/app.sock=s0/app.sock" in command
    assert command[command.index("unix:/run/handler-app/app.sock=s0/app.sock") - 1] == "--serve"
    assert apple.relay_targets == {"s0/handler.sock": str(source / "handler.sock")}
    assert apple.relay_serves == {"s0/app.sock": source / "app.sock"}


def test_a_socket_folder_whose_paths_are_too_long_for_macos_is_refused(tmp_path: Path) -> None:
    """If this fails: the launcher's listener cannot be made, and the sandbox starts unreachable."""
    deep = tmp_path / ("x" * 100)
    folder = {"source": str(deep), "target": "/run/handler-app", "serves": ["app.sock"]}
    with pytest.raises(UnenforceableError, match="too long for a socket"):
        launch.Apple().refuse(spec(tmp_path, socketFolders=[folder]))


@pytest.mark.parametrize(
    "case",
    [
        pytest.param((True, "current", True), id="both-current"),
        pytest.param((False, None, False), id="relay-missing"),
        pytest.param((True, None, False), id="relay-of-an-earlier-handler"),
        pytest.param((True, "other", False), id="relay-of-other-sources"),
    ],
)
def test_the_filter_counts_as_built_only_with_its_current_relay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: tuple[bool, str | None, bool],
) -> None:
    """The image is per account, the relay per HOME, and a relay from an earlier Handler may
    lack a flag the launcher gives it (`--serve`): either missing, handlerd builds both (D.4).
    If this fails: every session fails with "handler-relay is missing", or an app with
    "flag provided but not defined"."""
    relay_file, digest, built = case
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(
        images, "info_of", lambda ref: {"id": "a" * 64, "created": "2026-11-10T00:00:00Z"}
    )
    launch.relay_dir().mkdir(parents=True)
    if relay_file:
        (launch.relay_dir() / "handler-relay").touch()
    if digest is not None:
        value = images.relay_source_digest() if digest == "current" else "0" * 64
        (launch.relay_dir() / images.RELAY_SOURCE).write_text(value + "\n")
    images.proxy()
    assert (json.loads(capsys.readouterr().out).get("image") is not None) is built


@pytest.mark.rule("sandbox.sees-only-what-it-is-given")
def test_a_file_is_given_by_a_link_in_a_folder_holding_only_it(
    sandbox: Sandbox, tmp_path: Path
) -> None:
    """`container` mounts folders only: a file need's file is linked (the same file, not a
    copy) into a folder of the instance's, mounted at the file's folder, read-only when the
    file is.
    If this fails: an app sees what is next to the file you gave, or works on a copy."""
    mine = tmp_path / "mine"
    mine.mkdir()
    (mine / "agenda.md").write_text("a\n")
    (mine / "secret.txt").write_text("s\n")
    given = {
        "source": str(mine / "agenda.md"),
        "target": str(mine / "agenda.md"),
        "writable": False,
    }
    one = Sandbox(spec(Path(sandbox.spec.workdir), name="handler-test-file", folders=[given]))
    args = one.apple.folder(one.spec.folders[0], one.instance)
    linked = one.dir / "given" / "0"
    assert args == launch.bind(linked, str(mine), read_only=True)
    assert [p.name for p in linked.iterdir()] == ["agenda.md"]
    assert (linked / "agenda.md").stat().st_ino == (mine / "agenda.md").stat().st_ino
    assert launch.protected(one.spec) == []  # Apple's helper never reads where it is


def test_removing_a_sandbox_given_a_file_leaves_the_file(sandbox: Sandbox, tmp_path: Path) -> None:
    """Its folder is made read-only (no file replaced nor added in it), then removed with the
    instance: the link goes, the file stays, its mode untouched.
    If this fails: stopping an app deletes or changes the file you gave it."""
    from handler_sandbox_kit.launch import _remove_instance_dir  # noqa: PLC0415

    mine = tmp_path / "mine"
    mine.mkdir()
    (mine / "notes.md").write_text("n\n")
    (mine / "notes.md").chmod(0o640)
    given = {"source": str(mine / "notes.md"), "target": str(mine / "notes.md"), "writable": True}
    one = Sandbox(spec(Path(sandbox.spec.workdir), name="handler-test-file-rm", folders=[given]))
    one.apple.folder(one.spec.folders[0], one.instance)
    for linked in one.apple.linked_files.folders.values():  # as `create` does
        linked.chmod(0o555)
    assert _remove_instance_dir(one.dir) is None
    assert not one.dir.exists()
    assert (mine / "notes.md").read_text() == "n\n"
    assert oct((mine / "notes.md").stat().st_mode & 0o777) == oct(0o640)


@pytest.mark.rule("sandbox.refuses-what-it-cannot-enforce")
@pytest.mark.parametrize("case", ["folder-around", "modes-mixed", "other-volume"])
def test_a_file_that_cannot_be_given_alone_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """If this fails: a file need is given with what is around it, a read-only file becomes
    writable, or the launch fails late with a link error."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    mine = tmp_path / "mine"
    mine.mkdir()
    for name in ("a.md", "b.md"):
        (mine / name).write_text("x\n")

    def file(name: str, writable: bool = False) -> dict[str, Any]:
        path = str(mine / name)
        return {"source": path, "target": path, "writable": writable}

    folders = [file("a.md")]
    if case == "folder-around":
        (tmp_path / "other").mkdir()
        folders.append({"source": str(tmp_path / "other"), "target": str(mine), "writable": False})
    elif case == "modes-mixed":
        folders.append(file("b.md", writable=True))
    else:
        real_stat = os.stat

        def elsewhere(p: Any, *a: Any, **k: Any) -> os.stat_result:
            found = real_stat(p, *a, **k)
            if str(p).endswith("a.md"):  # its volume another
                return os.stat_result((*found[:2], found.st_dev + 1, *found[3:10]))
            return found

        monkeypatch.setattr(launch.os, "stat", elsewhere)
    with pytest.raises(UnenforceableError):
        launch.Apple().refuse(spec(tmp_path, folders=folders))


def test_a_file_in_a_folder_holding_another_mount_gets_its_mount_point_parents_first(
    sandbox: Sandbox, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file right in the home (`~/todo.md`) while the app's data folder is in it too
    (`~/.local/share/…`): the linked folder holds the data folder's mount point, and is mounted
    before it.
    If this fails: a file in a folder holding the app's data is refused, or hides that data."""
    monkeypatch.setattr(launch, "container", lambda *a, **k: "")
    monkeypatch.setattr(launch.Apple, "sweep", lambda self: set())
    home = tmp_path / "me"
    (home / "data").mkdir(parents=True)
    (home / "todo.md").write_text("t\n")
    given = {"source": str(home / "todo.md"), "target": str(home / "todo.md"), "writable": False}
    one = Sandbox(spec(home / "data", name="handler-test-file-home", folders=[given]))
    launch.Apple().refuse(one.spec)  # not refused
    apple, i = one.apple, one.instance
    apple.host_user(i)
    args = [*apple.work_folder(one.spec.work_folder, i), *apple.folder(one.spec.folders[0], i)]
    ordered = given_files.parents_first(args)
    assert given_files.mount_targets(ordered) == [str(home), str(home / "data")]
    apple.create(i, args)
    linked = one.dir / "given" / "0"
    assert sorted(p.name for p in linked.iterdir()) == ["data", "todo.md"]  # its mount point
    assert not any((linked / "data").iterdir())
