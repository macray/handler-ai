"""Which sandbox runtime handlerd uses (runtime.load, runtime.choose): runtime.toml, else the
system's."""

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from handler_control import runtime, sandbox_process
from handler_control.settings import Settings


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    monkeypatch.setenv("HANDLER_CONFIG_DIR", str(tmp_path))
    yield Settings.from_env()
    sandbox_process.use(sandbox_process.DEFAULT_RUNTIME)


def test_the_system_s_runtime_unless_another_was_chosen(settings: Settings) -> None:
    assert runtime.load(settings) == ("apple" if sys.platform == "darwin" else "podman")
    (settings.config_dir / "runtime.toml").write_text('name = "other"\n')
    assert runtime.load(settings) == "other" and sandbox_process.current() == "other"
    assert sandbox_process.launcher_prefix() == "handler-sandbox-other: "


@pytest.mark.rule("runtime.changed-only-when-nothing-runs")
@pytest.mark.parametrize("content", ['name = "../x"\n', "name = 3\n", "name = \n"])
def test_a_broken_choice_is_said(settings: Settings, content: str) -> None:
    (settings.config_dir / "runtime.toml").write_text(content)
    with pytest.raises(runtime.RuntimeChoiceError, match=r"runtime\.toml"):
        runtime.load(settings)


@pytest.mark.rule("runtime.changed-only-when-nothing-runs")
def test_only_an_installed_runtime_is_chosen(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(runtime.RuntimeChoiceError, match="handler-sandbox-other"):
        runtime.choose(settings, "other")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "handler-sandbox-other").write_text("#!/bin/sh\n")
    (bin_dir / "handler-sandbox-other").chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    assert "other" in sandbox_process.installed()
    runtime.choose(settings, "other")
    assert runtime.load(settings) == "other"


@pytest.mark.parametrize("platform", ["linux", "win32", "darwin"])
def test_the_apple_runtime_is_offered_on_macos_only(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "handler-sandbox-apple").write_text("#!/bin/sh\n")
    (bin_dir / "handler-sandbox-apple").chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setattr(sandbox_process.sys, "platform", platform)
    if platform == "darwin":
        assert "apple" in sandbox_process.installed()
        runtime.choose(settings, "apple")
        assert runtime.load(settings) == "apple"
    else:
        assert "apple" not in sandbox_process.installed()
        with pytest.raises(runtime.RuntimeChoiceError, match=r"^the apple runtime is for macOS$"):
            runtime.choose(settings, "apple")


@pytest.mark.rule("runtime.proposed-by-setup-on-macos")
@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_podman_is_not_offered_on_macos(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    """A Mac starts on Apple container and is offered it or Docker, never Podman (its own VM)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "handler-sandbox-podman").write_text("#!/bin/sh\n")
    (bin_dir / "handler-sandbox-podman").chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setattr(sandbox_process.sys, "platform", platform)
    if platform == "linux":
        assert "podman" in sandbox_process.installed()
        runtime.choose(settings, "podman")
    else:
        assert "podman" not in sandbox_process.installed()
        with pytest.raises(runtime.ForAnotherSystemError, match=r"not offered on macOS$"):
            runtime.choose(settings, "podman")
