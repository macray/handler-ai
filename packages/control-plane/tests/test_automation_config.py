"""Unit tests: automations as configured (I.1, I.7): folders, problems, the state,
the shipped examples."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from handler_control import automation_config as config
from handler_control.secrets import SecretStore

PROVIDER = """
apiVersion = "handler.provider/v1"
[endpoints]
openai-chat = "http://127.0.0.1:9/v1"
[[models]]
id = "small"
"""
ONLY_RESPONSES = PROVIDER.replace("openai-chat", "responses")


@pytest.fixture
def env(tmp_path: Path) -> dict[str, Path]:
    providers = tmp_path / "providers"
    providers.mkdir()
    (providers / "local.toml").write_text(PROVIDER)
    (providers / "resp.toml").write_text(ONLY_RESPONSES)
    root = tmp_path / "knowledge"
    (root / "handler").mkdir(parents=True)
    return {"providers": providers, "root": root, "automations": tmp_path / "automations"}


def write(env: dict[str, Path], name: str, text: str) -> config.Loaded:
    folder = env["automations"] / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "automation.toml").write_text(text)
    return config.load(folder)


def problems(env: dict[str, Path], loaded: config.Loaded) -> list[str]:
    return config.problems(
        loaded,
        providers_dir=env["providers"],
        store=SecretStore(env["root"].parent / "data"),
        knowledge_root=env["root"],
    )


GOOD = """
apiVersion = "handler.automation/v1"
when = "session.stopped"
only = { project = ["shop"], agent = ["dev"] }
run = "python3 extract.py"
services = { llm = ["local/small"] }
[[append]]
from = "note.md"
to = "handler/env-issues.md"
"""


@pytest.mark.rule("automation.with-problems-never-runs")
def test_a_good_automation_has_no_problems(env: dict[str, Path]) -> None:
    loaded = write(env, "env", GOOD)
    assert loaded.definition is not None and problems(env, loaded) == []


@pytest.mark.rule("automation.with-problems-never-runs", "llm.only-the-models-it-names")
@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (("local/small", "nope/small"), "services.llm nope/small: no provider 'nope'"),
        (("local/small", "local/big"), "not a model of provider local"),
        (("local/small", "resp/small"), "has no openai-chat or anthropic endpoint"),
        (("handler/env-issues.md", "missing/x.md"), "its folder does not exist"),
        (("handler/env-issues.md", "../x.md"), "outside the notes root"),
        (("handler/env-issues.md", "handler/x.txt"), "not a markdown note"),
        (('when = "session.stopped"', 'when = "nope"'), "automation.toml: when"),
        (("run =", "runs ="), "automation.toml"),
        (("[[append]]", "[[append"), "automation.toml"),  # TOML syntax
    ],
)
def test_problems(env: dict[str, Path], change: tuple[str, str], problem: str) -> None:
    (env["root"] / "handler" / "x.txt").write_text("")
    found = problems(env, write(env, "env", GOOD.replace(*change)))
    assert len(found) == 1 and problem in found[0], found


@pytest.mark.rule("automation.a-folder-of-yours")
def test_names_and_files(env: dict[str, Path]) -> None:
    write(env, "env", GOOD)
    bad = env["automations"] / "Bad_Name"
    bad.mkdir()
    (env["automations"] / "empty").mkdir()
    (env["automations"] / ".hidden").mkdir()
    loaded = {a.name: a for a in config.load_all(env["automations"])}
    assert sorted(loaded) == ["Bad_Name", "empty", "env"]
    assert "invalid name" in (loaded["Bad_Name"].error or "")
    assert "no automation.toml" in (loaded["empty"].error or "")
    folder = env["automations"] / "env"
    (folder / "lib").mkdir()
    (folder / "lib" / "a.py").write_text("x")
    (folder / "__pycache__").mkdir()
    (folder / "__pycache__" / "a.pyc").write_text("x")
    (folder / ".secret").write_text("x")
    assert config.files(folder) == ["automation.toml", "lib/a.py"]
    assert config.read_file(folder, "lib/a.py") == "x"
    for outside in ("../env/../../providers/local.toml", "/etc/passwd", "lib", "nope"):
        with pytest.raises(config.AutomationConfigError):
            config.read_file(folder, outside)
    assert config.get(env["automations"], "nope") is None
    assert config.get(env["automations"], "../providers") is None


def test_state_round_trip(tmp_path: Path) -> None:
    assert config.read_state(tmp_path, "x") == config.State()
    since = datetime(2026, 10, 6, tzinfo=UTC)
    state = config.State(enabled=True, since=since, cursors={"s_1": 12}, last_slot=since)
    config.write_state(tmp_path, "x", state)
    assert config.read_state(tmp_path, "x") == state
    assert (config.state_dir(tmp_path, "x") / "state.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.rule("automation.a-folder-of-yours", "automation.off-until-you-turn-it-on")
def test_the_shipped_examples_are_valid_and_copied_off(env: dict[str, Path]) -> None:
    assert "env-issues" in [e.name for e in config.examples()]
    for example in config.load_all(config.EXAMPLES):
        assert example.definition is not None, example.error
    target = config.copy_example(env["automations"], "mine", "env-issues")
    assert (target / "extract.py").is_file() and config.load(target).definition is not None
    with pytest.raises(config.AutomationExistsError):
        config.copy_example(env["automations"], "mine", "env-issues")
    with pytest.raises(config.AutomationConfigError, match="no example"):
        config.copy_example(env["automations"], "other", "../env-issues")
