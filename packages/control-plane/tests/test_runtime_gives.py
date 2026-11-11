"""A.8: an agent asking for what the sandbox runtime cannot give on this computer is refused when
it is saved (save_rules.check_runtime_gives), not when it starts."""

import pytest

from handler_contracts import AgentSettings, RuntimeCheck, RuntimeSupports
from handler_control import runtime, save_rules


def settings(**changes: object) -> AgentSettings:
    return AgentSettings.model_validate({"model": {"account": "fake"}} | changes)


@pytest.fixture
def strict_only(monkeypatch: pytest.MonkeyPatch) -> None:
    gives = RuntimeSupports(isolation="a virtual machine", abilities=[], limits=True)
    monkeypatch.setattr(runtime, "supports", lambda: gives)


@pytest.mark.rule("runtime.an-agent-needing-more-is-refused-when-saved")
@pytest.mark.usefixtures("strict_only")
def test_what_the_runtime_cannot_give_is_refused() -> None:
    save_rules.check_runtime_gives(settings())
    with pytest.raises(save_rules.ConflictError, match="sandboxes that run containers"):
        save_rules.check_runtime_gives(settings(confinement="nested"))
    with pytest.raises(save_rules.ConflictError, match="windows on your screen"):
        save_rules.check_runtime_gives(settings(display=True))


@pytest.mark.rule("runtime.an-agent-needing-more-is-refused-when-saved")
def test_nothing_is_refused_when_the_runtime_cannot_say(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime, "supports", lambda: None)
    save_rules.check_runtime_gives(settings(confinement="privileged", display=True))


@pytest.mark.rule("runtime.an-agent-needing-more-is-refused-when-saved")
def test_a_save_uses_a_check_at_most_five_minutes_old(monkeypatch: pytest.MonkeyPatch) -> None:
    """A check runs `podman info`: saves within CHECK_TTL use the last one, a later save runs
    another (a display gone since is seen then)."""
    now = [1000.0]
    checks: list[float] = []
    host = [RuntimeSupports(isolation="a container", abilities=["display"], limits=True)]

    def check() -> RuntimeCheck:
        checks.append(now[0])
        found = RuntimeCheck(runtime="podman 6", ok=True, items=[], supports=host[0])
        runtime._last_check[:] = [(now[0], found)]
        return found

    monkeypatch.setattr(runtime, "check", check)
    monkeypatch.setattr(runtime.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(runtime, "_last_check", [])
    save_rules.check_runtime_gives(settings(display=True))
    now[0] += runtime.CHECK_TTL - 1
    host[0] = host[0].model_copy(update={"abilities": []})  # the display went: not seen yet
    save_rules.check_runtime_gives(settings(display=True))
    assert checks == [1000.0]
    now[0] += 2
    with pytest.raises(save_rules.ConflictError, match="windows on your screen"):
        save_rules.check_runtime_gives(settings(display=True))
    assert len(checks) == 2


@pytest.mark.parametrize(
    ("ok", "detail", "said"),
    [
        (
            False,
            "not running: `container system start`",
            "Apple container 1.7.1: container service",
        ),
        (True, "running", None),
    ],
)
def test_not_ready_is_the_host_check_s_first_failing_required_item(
    monkeypatch: pytest.MonkeyPatch, ok: bool, detail: str, said: str | None
) -> None:
    found = RuntimeCheck.model_validate(
        {
            "runtime": "Apple container 1.7.1",
            "ok": ok,
            "items": [
                {"name": "experimental", "ok": True, "required": False, "detail": "-"},
                {"name": "container service", "ok": ok, "required": True, "detail": detail},
            ],
        }
    )
    monkeypatch.setattr(runtime, "check_of", lambda name: found)
    why = runtime.not_ready()
    assert why == (f"{said}: {detail}" if said else None)
