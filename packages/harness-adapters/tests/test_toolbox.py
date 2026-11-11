"""The toolbox's parts and its generated recipe (B.7): the built-in system packages, the user's,
the order of their layers, the golden Containerfile."""

import tomllib
from pathlib import Path

import pytest

from handler_contracts import ToolboxManifest
from handler_harness import catalog, toolbox

FIXTURES = Path(__file__).parent / "fixtures"


def manifest(*packages: str) -> ToolboxManifest:
    return ToolboxManifest.model_validate(
        {"distro": "fedora", "systemPackages": {p: {} for p in packages}}
    )


def package(root: Path, name: str, **fields: list[str]) -> None:
    folder = root / name
    folder.mkdir(parents=True)
    lists = "".join(f"{k} = {v!r}\n".replace("'", '"') for k, v in fields.items())
    (folder / "package.toml").write_text(
        'apiVersion = "handler.system-package/v1"\n'
        f'name = "{name}"\nversion = 1\ndescription = "{name}"\nprovides = ["{name}"]\n{lists}'
    )
    (folder / "install-fedora.sh").write_text(f"echo {name}\n")
    (folder / "check.sh").write_text(f"command -v {name}\n")


def test_the_builtin_system_packages_load() -> None:
    assert toolbox.names() == ["chromium", "docker", "gcc", "podman", "wl-clipboard"]
    for name in toolbox.names():
        found = toolbox.get(name)
        assert found.builtin and found.distros == ["fedora"] and found.check
    podman = toolbox.get("podman").manifest
    assert podman.provides == ["podman"]
    assert [c.target for c in podman.caches] == ["~/.local/share/containers/storage"]
    docker = toolbox.get("docker").manifest
    assert docker.provides == ["docker", "dockerd-rootless.sh"]
    assert docker.caches == []  # its daemon's state is the sandbox's own (/tmp)
    assert [(d.command, d.abilities) for d in docker.daemons] == [
        ("handler-dockerd", ["nested", "privileged"])
    ]


def test_the_default_toolbox_turns_on_the_engine_of_nested_sandboxes() -> None:
    """podman, and the display's clipboard (B.6: what `nested` and `display` need)."""
    text = (catalog.DEFAULT_TOOLBOX / "toolbox.toml").read_text()
    default = ToolboxManifest.model_validate(tomllib.loads(text))
    assert default.distro == "fedora"
    assert list(default.system_packages) == ["podman", "wl-clipboard"]


@pytest.mark.rule("toolbox.made-of-its-three-parts")
def test_the_golden_containerfile() -> None:
    """Handler's base, the system packages in their order, the user's lines last. Update the
    fixture deliberately."""
    text = toolbox.containerfile(manifest("gcc", "chromium", "podman"), "RUN dnf -y install zig\n")
    assert text == (FIXTURES / "toolbox.Containerfile").read_text()


def test_no_lines_no_section() -> None:
    assert "# your lines" not in toolbox.containerfile(manifest(), "  \n")


def test_the_build_context_holds_the_packages_folders(tmp_path: Path) -> None:
    context = tmp_path / "context"
    (context / "stale").mkdir(parents=True)
    toolbox.write_context(context, manifest("podman"), "")
    assert sorted(p.name for p in context.iterdir()) == ["Containerfile", "system-packages"]
    podman = context / "system-packages" / "podman"
    assert (podman / "files" / "storage.conf").is_file()
    assert "source=system-packages/podman" in (context / "Containerfile").read_text()


@pytest.mark.rule("toolbox.made-of-its-three-parts")
def test_layers_follow_the_order_added_moved_after_what_they_need(
    no_users_packages: Path,
) -> None:
    package(no_users_packages, "a")
    package(no_users_packages, "b", dependsOn=["a"])
    package(no_users_packages, "c", installsAfter=["d", "gcc"])
    package(no_users_packages, "d")
    order = [p.name for p in toolbox.ordered(manifest("b", "c", "a", "d"))]
    assert order == ["a", "b", "d", "c"]  # gcc is not on: nothing to wait for
    assert [p.name for p in toolbox.ordered(manifest("c", "a"))] == ["c", "a"]
    assert toolbox.with_dependencies(["c", "b"]) == ["c", "b", "a"]


@pytest.mark.rule("toolbox.made-of-its-three-parts")
def test_what_cannot_be_generated_says_why(no_users_packages: Path) -> None:
    package(no_users_packages, "a", dependsOn=["b"])
    package(no_users_packages, "b", installsAfter=["a"])
    with pytest.raises(toolbox.ToolboxError, match="needs b: turn it on"):
        toolbox.ordered(manifest("a"))
    with pytest.raises(toolbox.ToolboxError, match="each come after another"):
        toolbox.ordered(manifest("a", "b"))
    with pytest.raises(toolbox.ToolboxError, match="unknown system package 'nope'"):
        toolbox.ordered(manifest("nope"))
    with pytest.raises(toolbox.ToolboxError, match="unknown distro 'arch'"):
        toolbox.containerfile(ToolboxManifest(distro="arch"), "")
    (no_users_packages / "b" / "install-fedora.sh").rename(
        no_users_packages / "b" / "install-arch.sh"
    )
    with pytest.raises(toolbox.ToolboxError, match="no install script for fedora"):
        toolbox.ordered(manifest("b"))


def test_a_users_system_package_replaces_a_builtin_one(no_users_packages: Path) -> None:
    package(no_users_packages, "gcc")
    mine = toolbox.get("gcc")
    assert mine.overrides_builtin and not mine.builtin and mine.manifest.provides == ["gcc"]
    assert toolbox.names().count("gcc") == 1


def test_invalid_system_packages_say_what_is_wrong(no_users_packages: Path) -> None:
    package(no_users_packages, "x")
    (no_users_packages / "x" / "check.sh").unlink()
    with pytest.raises(toolbox.InvalidSystemPackageError, match=r"no check\.sh"):
        toolbox.get("x")
    package(no_users_packages, "y")
    (no_users_packages / "y" / "install-fedora.sh").unlink()
    with pytest.raises(toolbox.InvalidSystemPackageError, match=r"no install-<distro>\.sh"):
        toolbox.get("y")
    package(no_users_packages, "z")
    (no_users_packages / "z" / "package.toml").write_text('name = "z"\n')
    with pytest.raises(toolbox.InvalidSystemPackageError, match="apiVersion"):
        toolbox.get("z")


def test_every_cache_with_who_declares_it(no_users_packages: Path) -> None:
    mine = ToolboxManifest.model_validate(
        {
            "distro": "fedora",
            "systemPackages": {"podman": {}},
            "caches": [{"target": "~/.zig", "about": "Zig's packages"}],
        }
    )
    found = [(c.target, by) for c, by in toolbox.caches(mine)]
    assert found[:2] == [("~/.npm", "base"), ("~/.cache", "base")]
    assert ("~/.local/share/containers/storage", "system-package:podman") in found
    assert found[-1] == ("~/.zig", "user")
