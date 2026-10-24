"""Unit tests: how a launch's secrets reach its sandbox (A.3): phantoms its proxy swaps back
towards their hosts, the value itself where it cannot be injected."""

import string
import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_required_hosts import settings

from handler_contracts import AddonManifest, NetworkMode
from handler_control import launcher, secrets
from handler_control.agents import AgentRecord, RunsAs

TOKEN = "sk-ant-oat01-" + "aB3-xY9_" * 10


def test_phantom_keeps_length_form_and_vendor_prefix() -> None:
    made = secrets.phantom(TOKEN)
    assert made != TOKEN and len(made) == len(TOKEN)
    assert made.startswith("sk-ant-oat01-")
    for a, b in zip(TOKEN, made, strict=True):
        for kind in (string.digits, string.ascii_lowercase, string.ascii_uppercase):
            assert (a in kind) == (b in kind)
        if not a.isalnum():
            assert a == b
    assert secrets.phantom(TOKEN) != made  # random each time


def test_short_values_keep_no_prefix() -> None:
    """What follows a prefix must stay secret: with less than 24 characters after it, none is
    kept."""
    made = secrets.phantom("ab-cdef-0123")
    assert len(made) == 12 and made[2] == "-" and made[7] == "-"


@pytest.mark.parametrize(
    ("network", "value", "hosts", "phantom", "injected"),
    [
        ("filtered", TOKEN, ["api.anthropic.com:443"], True, True),
        ("open", TOKEN, ["api.anthropic.com:443"], True, True),
        ("none", TOKEN, ["api.anthropic.com:443"], True, False),  # nothing to reach
        ("filtered", TOKEN, [], False, False),  # no host to give it to
        ("filtered", "short", ["a.test:443"], False, False),  # under 8 characters
        ("filtered", "pass word long", ["a.test:443"], False, False),  # a space
        ("filtered", TOKEN, None, False, False),  # given as it is: its addon says so
        ("none", TOKEN, None, False, False),
    ],
)
def test_delivery(
    network: NetworkMode, value: str, hosts: list[str] | None, phantom: bool, injected: bool
) -> None:
    delivery = secrets.Delivery(network)
    given = delivery.give("accounts/me/token", value, hosts)
    assert (given != value) is phantom
    assert bool(delivery.injections) is injected
    if injected:
        [i] = delivery.injections
        assert (i.name, i.phantom, i.value, i.hosts) == ("accounts/me/token", given, value, hosts)


def _keyed(tmp_path: Path) -> tuple[launcher.Settings, RunsAs]:
    s = settings(tmp_path)
    (s.providers_dir / "keyed.toml").write_text(
        'apiVersion = "handler.provider/v1"\n'
        'endpoints = { responses = "https://llm.test/v1" }\n'
        'apiKey = { secret = "providers/keyed/apiKey" }\n'
        'models = [{ id = "m" }]\n'
    )
    secrets.SecretStore(s.data_dir).put("providers/keyed/apiKey", "sk-" + "k" * 40)
    return s, RunsAs(harness="codex", provider="keyed")


@pytest.mark.parametrize("network", ["filtered", "open"])
def test_the_sandbox_holds_a_phantom_of_its_provider_key(
    tmp_path: Path, network: NetworkMode
) -> None:
    s, runs = _keyed(tmp_path)
    agent = AgentRecord(id="a1", model=runs, scope=str(tmp_path / "code" / "shop"), network=network)
    spec, launch, _ = launcher.prepare(s, agent, runs, "c1")
    [i] = spec.injections
    assert (i.name, i.value, i.hosts) == (
        "providers/keyed/apiKey",
        "sk-" + "k" * 40,
        ["llm.test:443"],
    )
    assert spec.env["OPENAI_API_KEY"] == i.phantom
    assert i.value not in spec.model_dump_json(exclude={"injections"})
    assert i.value not in launch.model_dump_json()


def test_without_network_a_phantom_and_no_injection(tmp_path: Path) -> None:
    s, runs = _keyed(tmp_path)
    agent = AgentRecord(id="a1", model=runs, scope=str(tmp_path / "code" / "shop"), network="none")
    spec, _, _ = launcher.prepare(s, agent, runs, "c1")
    assert spec.injections == []
    assert spec.env["OPENAI_API_KEY"] not in ("sk-" + "k" * 40, "")


SLOTS = """
apiVersion = "handler.addon/v1"
name = "x"
egress = ["api.x.test:443", "cdn.x.test:443"]
[secretSlots.token]
env = "X_TOKEN"
hosts = ["api.x.test:443"]
[secretSlots.signing]
env = "X_SIGNING_KEY"
delivery = "env"
[secretSlots.other]
env = "X_OTHER"
"""


def test_addon_secret_slots_say_where_their_value_goes() -> None:
    manifest = AddonManifest.model_validate(tomllib.loads(SLOTS))
    assert manifest.secret_hosts("token") == ["api.x.test:443"]
    assert manifest.secret_hosts("signing") is None  # as it is
    assert manifest.secret_hosts("other") == ["api.x.test:443", "cdn.x.test:443"]


@pytest.mark.parametrize(
    ("slot", "error"),
    [
        ('hosts = ["elsewhere.test:443"]', "hosts not in 'egress'"),
        ('hosts = ["api.x.test:443"]\ndelivery = "env"', "not 'env' delivery"),
        ('env = "SSL_CERT_FILE"', "owned by the platform"),
    ],
)
def test_addon_secret_slot_errors(slot: str, error: str) -> None:
    body = 'apiVersion = "handler.addon/v1"\nname = "x"\negress = ["api.x.test:443"]\n'
    body += "[secretSlots.s]\n" + (slot if slot.startswith("env") else f'env = "X_S"\n{slot}')
    with pytest.raises(ValidationError, match=error):
        AddonManifest.model_validate(tomllib.loads(body))
