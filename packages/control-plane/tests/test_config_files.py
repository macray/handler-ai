"""Unit tests: config file sources (a provider's `files`) → contents."""

from pathlib import Path

import pytest

from handler_contracts import EnvSecret, FileContent, FileSecret
from handler_control import config_files


def test_inline_env_and_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HANDLER_T_CONFIG", 'active_model = "x"\n')
    f = tmp_path / "config.toml"
    f.write_text("[[providers]]\nname = 'local'\n")
    assert config_files.resolve(FileContent(content="a = 1")) == "a = 1"
    assert config_files.resolve(EnvSecret(env="HANDLER_T_CONFIG")) == 'active_model = "x"\n'
    assert config_files.resolve(FileSecret(file=str(f))) == f.read_text()  # whole file, not a line


def test_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("HANDLER_T_MISSING", raising=False)
    with pytest.raises(config_files.ConfigFileError, match="not set"):
        config_files.resolve(EnvSecret(env="HANDLER_T_MISSING"))
    with pytest.raises(config_files.ConfigFileError, match="cannot read"):
        config_files.resolve(FileSecret(file=str(tmp_path / "missing.toml")))
    big = tmp_path / "big.toml"
    big.write_bytes(b"x" * (config_files.MAX_BYTES + 1))
    with pytest.raises(config_files.ConfigFileError, match="larger than"):
        config_files.resolve(FileSecret(file=str(big)))
