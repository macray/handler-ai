import tomllib
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from handler_contracts import (
    AbsolutePath,
    Account,
    AddonManifest,
    AgentSpec,
    Automation,
    Binding,
    CacheDeclaration,
    CacheFolder,
    EgressEntry,
    FileSecret,
    HarnessDescriptor,
    HostPath,
    PersonName,
    Provider,
    SandboxSpec,
    SystemPackageManifest,
    ToolboxManifest,
    cache_name,
    check_binding,
    is_within,
)
from handler_contracts.schemas import DEFAULT_OUT_DIR, render

FIXTURES = Path(__file__).parent / "fixtures"


# ── common ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("p", ["/", "/home/you/code", "/a/b.c"])
def test_absolute_path_accepts(p: str) -> None:
    TypeAdapter(AbsolutePath).validate_python(p)


@pytest.mark.parametrize("p", ["relative", "/a/../b", "/a/./b", "/a//b", "/a/"])
def test_absolute_path_rejects(p: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(AbsolutePath).validate_python(p)


@pytest.mark.parametrize(
    ("p", "expanded"),
    [
        ("~", "/home/u"),
        ("~/code", "/home/u/code"),
        ("/abs", "/abs"),
        ("~other", None),
        ("~/a/../b", None),
        ("relative", None),
    ],
)
def test_host_path_expands_home(
    monkeypatch: pytest.MonkeyPatch, p: str, expanded: str | None
) -> None:
    monkeypatch.setenv("HOME", "/home/u")
    if expanded is None:
        with pytest.raises(ValidationError):
            TypeAdapter(HostPath).validate_python(p)
    else:
        assert TypeAdapter(HostPath).validate_python(p) == expanded


@pytest.mark.rule("network.an-entry-is-a-host-and-its-port")
@pytest.mark.parametrize(
    "e", ["api.anthropic.com:443", "*.crates.io:443", "example.org:80", "h.internal:65535"]
)
def test_egress_entry_accepts(e: str) -> None:
    TypeAdapter(EgressEntry).validate_python(e)


@pytest.mark.rule("network.an-entry-is-a-host-and-its-port")
@pytest.mark.parametrize(
    "e",
    [
        "api.anthropic.com",  # no default port (A.3)
        "*:443",
        "https://x.com:443",
        "API.x.com:443",
        "x:443",
        "*.*.x.com:443",
        "1.2.3:80",
        "x.com:",
        "x.com:0",
        "x.com:65536",
        "x.com:080",
        "x.com:443:1",
        "x.com:https",
    ],
)
def test_egress_entry_rejects(e: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(EgressEntry).validate_python(e)


@pytest.mark.parametrize("p", ["owner", "alice", "anne-marie", "jean_luc", "kid2"])
def test_person_name_accepts(p: str) -> None:
    TypeAdapter(PersonName).validate_python(p)


@pytest.mark.parametrize("p", ["", "Alice", "_alice", "2kids", "jean luc", "é", "a" * 31])
def test_person_name_rejects(p: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(PersonName).validate_python(p)


def test_is_within() -> None:
    assert is_within("/home/you/code", "/home/you/code")
    assert is_within("/home/you/code/x", "/home/you/code")
    assert not is_within("/home/you/codex", "/home/you/code")
    assert is_within("/anything", "/")


# ── E: what an agent runs as ────────────────────────────────────────────

ACCOUNT = {"apiVersion": "handler.account/v1", "harness": "claude-code"}


@pytest.mark.rule("access.one-account-or-one-provider", "access.keys-are-references")
def test_an_account_is_its_harness_and_a_description() -> None:
    account = Account.model_validate(ACCOUNT | {"plan": "max"})
    assert account.connectors is False  # decision 1: off unless the account says so
    with pytest.raises(ValidationError, match="login"):  # the login is handler's, never in the file
        Account.model_validate({"apiVersion": "handler.account/v1", "harness": "x", "login": {}})
    # a token login's token: a reference (E2), never the value
    pasted = Account.model_validate(ACCOUNT | {"token": {"secret": "accounts/perso/token"}})
    assert pasted.token is not None
    with pytest.raises(ValidationError):
        Account.model_validate(ACCOUNT | {"token": "sk-ant-oat01-x"})
    spec = AgentSpec.resolve("claude-code", "opus", account=("perso", account))
    assert (spec.account, spec.account_plan, spec.config.model) == ("perso", "max", "opus")
    assert spec.account_login is None and spec.config.account_connectors is False
    linked = AgentSpec.resolve(
        "claude-code", account=("w", Account.model_validate(ACCOUNT | {"connectors": True}))
    )
    assert linked.config.account_connectors is True
    with pytest.raises(ValueError, match="is for harness 'claude-code', not 'pi'"):
        AgentSpec.resolve("pi", account=("perso", account))


@pytest.mark.rule("provider.its-files-go-to-their-harness")
def test_resolve_with_a_provider_keeps_its_spec_and_its_files_for_the_harness() -> None:
    files = {"codex": {"instructions_md": {"content": "You are…"}}}
    provider = Provider.model_validate(PROVIDER | {"files": files})
    spec = AgentSpec.resolve("codex", "qwen", provider=("api", provider))
    assert spec.provider_spec is not None and spec.provider_spec.models[0].id == "qwen"
    assert spec.files is not None and set(spec.files) == {"instructions_md"}
    assert AgentSpec.resolve("pi", provider=("api", provider)).files is None  # codex's only


@pytest.mark.rule("access.one-account-or-one-provider")
def test_an_agent_runs_on_an_account_or_a_provider_not_both_nor_none() -> None:
    AgentSpec(harness="codex", provider="llamacpp")
    for both_or_none in ({"provider": "llamacpp", "account": "a"}, {}):
        with pytest.raises(ValidationError, match="exactly one"):
            AgentSpec.model_validate({"harness": "codex"} | both_or_none)


def test_provider_file_sources_expand_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/home/u")
    files = {"vibe": {"a": {"file": "~/x.toml"}, "b": {"env": "X"}, "c": {"content": "x=1"}}}
    provider = Provider.model_validate(PROVIDER | {"files": files})
    assert provider.files is not None
    assert provider.files["vibe"]["a"] == FileSecret(file="/home/u/x.toml")
    with pytest.raises(ValidationError):
        Provider.model_validate(PROVIDER | {"files": {"vibe": {"a": "inline without a key"}}})


@pytest.mark.rule("access.keys-are-references")
def test_e2_literal_secret_rejected() -> None:
    with pytest.raises(ValidationError):
        Provider.model_validate(PROVIDER | {"apiKey": "sk-ant-literal"})
    with pytest.raises(ValidationError):  # an account has no secrets at all
        Account.model_validate(ACCOUNT | {"secrets": {"api_key": {"env": "X"}}})


@pytest.mark.rule("access.keys-are-references", "secrets.set-by-their-owner")
def test_e2_secret_references_accepted() -> None:
    for ref in (
        {"env": "X"},
        {"file": "/run/secret"},
        {"command": ["pass", "x"]},
        {"secret": "a/b"},
    ):
        Provider.model_validate(PROVIDER | {"apiKey": ref})
    for path in ("../x", "a/.b", "a//b", ""):
        with pytest.raises(ValidationError):
            Provider.model_validate(PROVIDER | {"apiKey": {"secret": path}})


def test_unknown_keys_are_errors() -> None:
    with pytest.raises(ValidationError):
        Account.model_validate(ACCOUNT | {"permisions": {"mode": "ask"}})


# ── E: Provider ─────────────────────────────────────────────────────────

PROVIDER: dict[str, Any] = {
    "apiVersion": "handler.provider/v1",
    "endpoints": {
        "openai-chat": "http://127.0.0.1:3000/v1",
        "responses": "http://127.0.0.1:3000/v1",
    },
    "models": [{"id": "qwen", "contextWindow": 200000, "reasoning": True}],
}


def test_provider_picks_the_first_protocol_it_has_an_endpoint_for() -> None:
    p = Provider.model_validate(PROVIDER)
    assert p.endpoint_for(["anthropic", "responses"]) == ("responses", "http://127.0.0.1:3000/v1")
    assert p.endpoint_for(["openai-chat", "responses"])[0] == "openai-chat"  # ty: ignore
    assert p.endpoint_for(["anthropic"]) is None
    assert p.model_named("qwen") is not None and p.model_named("other") is None


@pytest.mark.rule("access.keys-are-references", "provider.its-endpoints-and-models-are-checked")
@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"endpoints": {}}, "at least 1"),
        ({"endpoints": {"gopher": "http://x"}}, "openai-chat"),
        ({"endpoints": {"anthropic": "ftp://x.com"}}, "http:// or https://"),
        ({"endpoints": {"anthropic": "https://u:p@x.com"}}, "credentials"),
        ({"models": []}, "at least 1"),
        ({"models": [{"id": "a"}, {"id": "a"}]}, "two models have the id a"),
        ({"apiKey": "sk-literal"}, "apiKey"),
        ({"key": "x"}, "key"),
    ],
)
def test_invalid_providers(change: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Provider.model_validate(PROVIDER | change)


SPEECH = {"id": "voxtral", "speech": True}


@pytest.mark.rule("provider.its-endpoints-and-models-are-checked")
def test_a_speech_model_needs_a_transcriptions_endpoint() -> None:
    """If this fails: voice notes are sent to an endpoint that does not write down speech, and
    fail with the provider's error."""
    with pytest.raises(ValidationError, match="a speech model needs a transcriptions endpoint"):
        Provider.model_validate(PROVIDER | {"models": [*PROVIDER["models"], SPEECH]})
    endpoints = PROVIDER["endpoints"] | {"transcriptions": "http://127.0.0.1:3000/v1"}
    Provider.model_validate(
        PROVIDER | {"endpoints": endpoints, "models": [*PROVIDER["models"], SPEECH]}
    )  # with one, valid


def test_a_provider_key_is_a_reference() -> None:
    p = Provider.model_validate(PROVIDER | {"apiKey": {"env": "KEY"}})
    assert p.api_key is not None


# ── B: HarnessDescriptor ────────────────────────────────────────────────

CLAUDE_CODE: dict[str, Any] = {
    "apiVersion": "handler.harness/v1",
    "name": "claude-code",
    "product": "Claude Code",
    "image": "localhost/handler-ai-claude-code",
    "acpCommand": ["claude-agent-acp"],
    "home": "/home/agent",
    "stateSlots": {
        "config_dir": {"target": "~/.claude", "kind": "dir", "required": False},
        "config_json": {"target": "~/.claude.json", "kind": "file", "required": False},
    },
    "login": {
        "subscription": "Claude Pro or Max",
        "unattended": "refused",
        "terms": "https://www.anthropic.com/legal/consumer-terms",
        "token": "CLAUDE_CODE_OAUTH_TOKEN",
        "tokenCommand": "claude setup-token",
        "hosts": ["api.anthropic.com:443"],
    },
    "providerProtocols": ["anthropic"],
    "permissions": {
        "ask": {"sessionMode": "default"},
        "accept-edits": {"sessionMode": "acceptEdits"},
        "bypass": {"sessionMode": "bypassPermissions"},
    },
    "env": {"NODE_USE_ENV_PROXY": "1"},
    "accountConnectors": {"offEnv": {"ENABLE_CLAUDEAI_MCP_SERVERS": "false"}},
}


def test_reference_claude_code_descriptor() -> None:
    d = HarnessDescriptor.model_validate(CLAUDE_CODE)
    assert d.permissions["bypass"].session_mode == "bypassPermissions"
    assert d.account_connectors is not None
    assert d.account_connectors.off_env == {"ENABLE_CLAUDEAI_MCP_SERVERS": "false"}


@pytest.mark.parametrize(
    "image", ["localhost:5000/handler-x", "docker.io/library/alpine", "handler-x"]
)
def test_b6_descriptor_image_untagged_accepted(image: str) -> None:
    assert HarnessDescriptor.model_validate(CLAUDE_CODE | {"image": image}).image == image


@pytest.mark.parametrize(
    "image", ["localhost/handler-ai-x:0.81.1", "handler-x:latest", "handler-x@sha256:ab"]
)
def test_b6_descriptor_image_tag_rejected(image: str) -> None:
    with pytest.raises(ValidationError, match="tag or digest"):
        HarnessDescriptor.model_validate(CLAUDE_CODE | {"image": image})


# ── B.6, B.7: the toolbox ───────────────────────────────────────────────


@pytest.mark.parametrize(
    ("target", "name"),
    [
        ("~/.m2", "m2"),
        ("~/.cache", "cache"),
        ("~/go", "go"),
        ("~/.local/share/containers/storage", "local-share-containers-storage"),
        ("/opt/Thing", "opt-thing"),
    ],
)
def test_a_cache_folder_is_named_from_its_target(target: str, name: str) -> None:
    assert cache_name(target) == name


def test_caches_declared_together_never_share_a_folder() -> None:
    def toolbox(*targets: str) -> ToolboxManifest:
        caches = [{"target": t, "about": "x"} for t in targets]
        return ToolboxManifest.model_validate({"distro": "fedora", "caches": caches})

    assert [c.target for c in toolbox("~/.m2", "~/.local").caches] == ["~/.m2", "~/.local"]
    for refused, message in (
        (("~/.m2", "~/.m2"), "two caches at ~/.m2"),
        (("~/.m2", "~/m2"), "share the folder"),
        (("~",), "whole home"),
        (("/",), "whole disk"),
    ):
        with pytest.raises(ValidationError, match=message):
            toolbox(*refused)
    with pytest.raises(ValidationError, match="about"):  # what it holds is said
        ToolboxManifest.model_validate({"distro": "fedora", "caches": [{"target": "~/.m2"}]})


def test_a_cache_may_put_a_folder_of_its_own_on_path() -> None:
    def cache(bin_: str) -> CacheDeclaration:
        return CacheDeclaration.model_validate({"target": "~/.cargo", "about": "x", "bin": bin_})

    assert cache("bin").bin == "bin"
    assert cache("tools/bin").bin == "tools/bin"
    for outside in ("/usr/bin", "../bin", "bin/../..", ".", "bin/", ""):
        with pytest.raises(ValidationError, match="not a folder inside the cache"):
            cache(outside)


def test_a_cache_folder_s_commands_are_in_it() -> None:
    CacheFolder(source="/h/bun", target="/home/agent/.bun", path="/home/agent/.bun/bin")
    with pytest.raises(ValidationError, match="its commands' folder is in it"):
        CacheFolder(source="/h/bun", target="/home/agent/.bun", path="/usr/bin")


def test_a_system_package_says_what_it_provides() -> None:
    package = {
        "apiVersion": "handler.system-package/v1",
        "name": "podman",
        "version": 1,
        "description": "Podman",
        "provides": ["podman"],
        "caches": [{"target": "~/.local/share/containers/storage", "about": "Images"}],
    }
    assert SystemPackageManifest.model_validate(package).depends_on == []
    for wrong in ({"provides": []}, {"version": 0}, {"dependsOn": ["podman"]}, {"setcap": 1}):
        with pytest.raises(ValidationError):
            SystemPackageManifest.model_validate(package | wrong)


def test_the_harnesses_say_what_they_need_from_the_toolbox() -> None:
    d = HarnessDescriptor.model_validate(CLAUDE_CODE | {"needs": ["node", "g++", "wl-paste"]})
    assert d.needs == ["node", "g++", "wl-paste"]
    with pytest.raises(ValidationError):
        HarnessDescriptor.model_validate(CLAUDE_CODE | {"needs": ["rm -rf"]})


def test_a_credential_slot_is_a_file() -> None:
    slots = CLAUDE_CODE["stateSlots"]
    login = {"target": "~/.a", "kind": "file", "required": False, "credential": True}
    HarnessDescriptor.model_validate(CLAUDE_CODE | {"stateSlots": slots | {"auth": login}})
    for wrong in ({"kind": "dir"}, {"perSession": True}):
        with pytest.raises(ValidationError, match="a credential is a file"):
            HarnessDescriptor.model_validate(
                CLAUDE_CODE | {"stateSlots": slots | {"auth": login | wrong}}
            )


def test_a_login_leaves_a_token_or_a_credential_file() -> None:
    d = HarnessDescriptor.model_validate(CLAUDE_CODE)
    assert d.login is not None and d.login.kind == "token"
    login = CLAUDE_CODE["login"]
    with pytest.raises(ValidationError, match="exactly one"):
        HarnessDescriptor.model_validate(CLAUDE_CODE | {"login": login | {"file": "auth"}})
    # handler runs no token login: the person runs `tokenCommand` and gives the token (D.9)
    with pytest.raises(ValidationError, match="tokenCommand"):
        HarnessDescriptor.model_validate(
            CLAUDE_CODE | {"login": {k: v for k, v in login.items() if k != "tokenCommand"}}
        )
    with pytest.raises(ValidationError, match="no 'command'"):
        HarnessDescriptor.model_validate(CLAUDE_CODE | {"login": login | {"command": ["x"]}})
    by_file = {k: v for k, v in login.items() if k not in ("token", "tokenCommand")}
    by_file |= {"file": "config_dir", "command": ["a", "login"], "env": {"A_HOME": "{dir}"}}
    with pytest.raises(ValidationError, match="for a token login"):
        HarnessDescriptor.model_validate(
            CLAUDE_CODE | {"login": by_file | {"file": "auth", "tokenPrefix": "sk-"}}
        )
    with pytest.raises(ValidationError, match="not a credential state slot"):
        HarnessDescriptor.model_validate(CLAUDE_CODE | {"login": by_file})
    auth = {"target": "~/.a", "kind": "file", "required": False, "credential": True}
    slots = CLAUDE_CODE["stateSlots"] | {"auth": auth}
    by_file |= {"file": "auth"}
    d = HarnessDescriptor.model_validate(CLAUDE_CODE | {"stateSlots": slots, "login": by_file})
    assert d.login is not None and d.login.kind == "file"
    # else handler cannot find it
    with pytest.raises(ValidationError, match="writes its file into"):
        HarnessDescriptor.model_validate(
            CLAUDE_CODE | {"stateSlots": slots, "login": by_file | {"env": {}}}
        )
    with pytest.raises(ValidationError, match="has the 'command'"):
        HarnessDescriptor.model_validate(
            CLAUDE_CODE
            | {"stateSlots": slots, "login": {k: v for k, v in by_file.items() if k != "command"}}
        )


def test_a_login_s_plans_and_their_env_go_together() -> None:
    login = CLAUDE_CODE["login"]
    plans = {"plans": ["pro", "max"], "planEnv": "CLAUDE_CODE_SUBSCRIPTION_TYPE"}
    d = HarnessDescriptor.model_validate(CLAUDE_CODE | {"login": login | plans})
    assert d.login is not None and d.login.plans == ["pro", "max"]
    for half in ({"plans": ["pro"]}, {"planEnv": "X"}):
        with pytest.raises(ValidationError, match="go together"):
            HarnessDescriptor.model_validate(CLAUDE_CODE | {"login": login | half})


def test_permission_modes_may_be_left_out_but_not_all() -> None:
    partial = {k: v for k, v in CLAUDE_CODE["permissions"].items() if k == "bypass"}
    d = HarnessDescriptor.model_validate(CLAUDE_CODE | {"permissions": partial})
    assert list(d.permissions) == ["bypass"]
    with pytest.raises(ValidationError, match="at least one"):
        HarnessDescriptor.model_validate(CLAUDE_CODE | {"permissions": {}})


def test_initial_content_is_for_a_file_of_the_agent_s_state() -> None:
    slots = CLAUDE_CODE["stateSlots"]
    onboarded = slots["config_json"] | {"initial": "{}"}
    d = HarnessDescriptor.model_validate(
        CLAUDE_CODE | {"stateSlots": slots | {"config_json": onboarded}}
    )
    assert d.state_slots["config_json"].initial == "{}"
    for wrong in ({"kind": "dir"}, {"credential": True}, {"perSession": True}, {"readOnly": True}):
        with pytest.raises(ValidationError, match="'initial'"):
            HarnessDescriptor.model_validate(
                CLAUDE_CODE | {"stateSlots": slots | {"config_json": onboarded | wrong}}
            )


def test_terminal_maps_the_same_permission_modes() -> None:
    """D.16: the terminal program honours exactly the modes the ACP adapter does."""
    flags = {"ask": [], "accept-edits": ["--edits"], "bypass": ["--yolo"]}
    terminal = {"command": ["claude"], "permissions": flags, "modelFlag": "--model"}
    d = HarnessDescriptor.model_validate(CLAUDE_CODE | {"terminal": terminal})
    assert d.terminal is not None and d.terminal.permissions["ask"] == []
    with pytest.raises(ValidationError, match="same modes"):
        partial = terminal | {"permissions": {"bypass": ["--yolo"]}}
        HarnessDescriptor.model_validate(CLAUDE_CODE | {"terminal": partial})
    with pytest.raises(ValidationError, match="not both"):
        both = terminal | {"modelEnv": "MODEL"}
        HarnessDescriptor.model_validate(CLAUDE_CODE | {"terminal": both})


# ── A: SandboxSpec ──────────────────────────────────────────────────────

SPEC: dict[str, Any] = {
    "apiVersion": "handler.sandbox/v2",
    "name": "handler-run1-conn1",
    "image": "localhost/handler-ai-claude-code:latest",
    "argv": ["claude-agent-acp"],
    "env": {},
    "workdir": "/home/you/code/foo",
    "home": "/home/agent",
    "workFolder": {"path": "/home/you/code/foo"},
    "network": {"mode": "filtered", "allow": ["api.anthropic.com:443"], "enforcement": "enforce"},
}


def test_valid_spec() -> None:
    spec = SandboxSpec.model_validate(SPEC)
    assert spec.network.mode == "filtered"


@pytest.mark.rule("sandbox.an-invalid-spec-is-refused")
def test_workdir_in_the_work_folder_or_a_folder() -> None:
    with pytest.raises(ValidationError, match="workdir"):
        SandboxSpec.model_validate(SPEC | {"workdir": "/etc"})
    folder = {"source": "/srv/definition", "target": "/srv/definition", "writable": False}
    SandboxSpec.model_validate(SPEC | {"workdir": "/srv/definition", "folders": [folder]})


@pytest.mark.rule("sandbox.an-invalid-spec-is-refused")
def test_a_file_is_in_the_home() -> None:
    """A.1: a file Handler gives and a kept file are in the home, anywhere in it."""
    given = {"target": "/home/agent/.vibe/config.toml", "content": "x", "mode": "0600"}
    kept = {"source": "/data/auth/auth", "target": "/home/agent/.codex/auth.json"}
    SandboxSpec.model_validate(SPEC | {"files": [given | {"writable": True}], "keptFiles": [kept]})
    for files, kept_files in (([given | {"target": "/etc/x.toml"}], []),
                              ([], [kept | {"target": "/etc/auth.json"}])):  # fmt: skip
        with pytest.raises(ValidationError, match="a file is in the home"):
            SandboxSpec.model_validate(SPEC | {"files": files, "keptFiles": kept_files})


@pytest.mark.rule("sandbox.an-invalid-spec-is-refused")
def test_a_tool_is_in_handler_s_folders() -> None:
    tool = {"target": "/opt/handler/bin/handler-sandbox-env", "content": "#!/bin/sh\n"}
    SandboxSpec.model_validate(SPEC | {"tools": [tool]})
    for elsewhere in ("/usr/bin/x", "/opt/handler", "/run/handlerx/x"):
        with pytest.raises(ValidationError, match="Handler's folders"):
            SandboxSpec.model_validate(SPEC | {"tools": [tool | {"target": elsewhere}]})


@pytest.mark.rule("sandbox.an-invalid-spec-is-refused")
def test_filtered_requires_enforcement() -> None:
    with pytest.raises(ValidationError):
        SandboxSpec.model_validate(SPEC | {"network": {"mode": "filtered", "allow": []}})


@pytest.mark.rule("sandbox.an-invalid-spec-is-refused")
def test_duplicate_targets_rejected() -> None:
    dup = {"source": "/tmp/x", "target": "/home/you/code/foo", "writable": False}
    with pytest.raises(ValidationError, match="duplicate"):
        SandboxSpec.model_validate(SPEC | {"folders": [dup]})


def test_an_addon_s_commands_are_in_its_files() -> None:
    addon = {"source": "/data/addons/x/abc", "target": "/opt/tools/x"}
    spec = SandboxSpec.model_validate(SPEC | {"addons": [addon | {"path": "/opt/tools/x/bin"}]})
    assert spec.abilities() == set()  # a read-only folder: every runtime gives it
    with pytest.raises(ValidationError, match="its commands' folder"):
        SandboxSpec.model_validate(SPEC | {"addons": [addon | {"path": "/usr/bin"}]})


@pytest.mark.rule("sandbox.an-invalid-spec-is-refused")
def test_an_addon_s_target_must_be_unique() -> None:
    dup = {"source": "/data/addons/x/abc", "target": "/home/you/code/foo"}
    with pytest.raises(ValidationError, match="duplicate"):
        SandboxSpec.model_validate(SPEC | {"addons": [dup]})


@pytest.mark.rule("sandbox.an-invalid-spec-is-refused")
def test_a7_display_env_belongs_to_the_implementation() -> None:
    assert SandboxSpec.model_validate(SPEC | {"display": True}).abilities() == {"display"}
    with pytest.raises(ValidationError, match="display is set by the implementation"):
        SandboxSpec.model_validate(SPEC | {"display": True, "env": {"XDG_RUNTIME_DIR": "/x"}})
    SandboxSpec.model_validate(SPEC | {"env": {"XDG_RUNTIME_DIR": "/x"}})


@pytest.mark.rule("sandbox.an-invalid-spec-is-refused")
def test_path_is_the_runtime_s() -> None:
    with pytest.raises(ValidationError, match="PATH is the runtime's"):
        SandboxSpec.model_validate(SPEC | {"env": {"PATH": "/x"}})


@pytest.mark.rule(
    "secrets.an-open-sandbox-gets-a-filter-for-them", "secrets.a-phantom-is-as-long-as-its-value"
)
def test_injections_are_the_network_s() -> None:
    """A.3: secrets in an open or filtered network; none can be given without one."""
    secret = {"name": "k", "phantom": "p" * 8, "value": "v" * 8, "hosts": ["api.x.com:443"]}
    open_one = SandboxSpec.model_validate(
        SPEC | {"network": {"mode": "open", "injections": [secret]}}
    )
    assert open_one.injections[0].name == "k"
    assert (
        SandboxSpec.model_validate(
            SPEC | {"network": {"mode": "none", "injections": [secret]}}
        ).injections
        == []
    )
    with pytest.raises(ValidationError, match="unique"):
        SandboxSpec.model_validate(SPEC | {"network": {"mode": "open", "injections": [secret] * 2}})


# ── G: Addon and Binding ────────────────────────────────────────────────

ADDON: dict[str, Any] = {
    "apiVersion": "handler.tool/v1",
    "name": "shopify",
    "image": "localhost/handler-ai-tool-shopify",
    "commands": ["shopify"],
    "check": ["shopify", "version"],
    "settings": {"store": {"env": "SHOPIFY_FLAG_STORE", "required": True}},
    "secretSlots": {"theme_token": {"env": "SHOPIFY_CLI_THEME_TOKEN"}},
    "egress": ["*.myshopify.com:443"],
}


def binding(**fields: Any) -> Binding:
    return Binding.model_validate(
        {"apiVersion": "handler.connection/v1", "tool": "shopify"} | fields
    )


def test_addon_manifest() -> None:
    addon = AddonManifest.model_validate(ADDON)
    assert addon.mount_target == "/opt/tools/shopify"
    assert addon.bin_dir == "/opt/tools/shopify/bin"


@pytest.mark.rule("tool.its-manifest-holds-together")
def test_addon_needs_and_caches() -> None:
    addon = AddonManifest.model_validate(
        ADDON
        | {
            "needs": ["node"],
            "caches": [{"target": "~/.config/shopify", "about": "Shopify CLI's sessions"}],
        }
    )
    assert addon.needs == ["node"]
    assert [c.target for c in addon.caches] == ["~/.config/shopify"]
    with pytest.raises(ValidationError, match="its own commands: shopify"):
        AddonManifest.model_validate(ADDON | {"needs": ["shopify"]})
    twice = [{"target": "~/.m2", "about": "x"}, {"target": "~/.m2", "about": "y"}]
    with pytest.raises(ValidationError, match="two caches"):
        AddonManifest.model_validate(ADDON | {"caches": twice})


@pytest.mark.rule("tool.its-manifest-holds-together")
def test_addon_without_image_has_no_commands() -> None:
    AddonManifest.model_validate(
        {"apiVersion": "handler.tool/v1", "name": "logs", "egress": ["x.io:443"]}
    )
    with pytest.raises(ValidationError, match="need an 'image'"):
        AddonManifest.model_validate(ADDON | {"image": None})


@pytest.mark.rule("tool.its-manifest-holds-together")
def test_addon_mcp_server_starts_from_its_own_commands() -> None:
    addon = AddonManifest.model_validate(ADDON | {"mcp": {"command": ["shopify", "mcp"]}})
    assert addon.mcp is not None and addon.mcp.command == ["shopify", "mcp"]
    with pytest.raises(ValidationError, match="must start with one of the tool's 'commands'"):
        AddonManifest.model_validate(ADDON | {"mcp": {"command": ["npx", "some-mcp"]}})


@pytest.mark.rule("tool.its-manifest-holds-together")
def test_addon_image_needs_commands_and_no_tag() -> None:
    with pytest.raises(ValidationError, match="commands"):
        AddonManifest.model_validate(ADDON | {"commands": []})
    with pytest.raises(ValidationError):
        AddonManifest.model_validate(ADDON | {"image": "localhost/handler-ai-tool-shopify:latest"})


@pytest.mark.rule("tool.never-sets-what-handler-owns")
@pytest.mark.parametrize(
    "change",
    [
        {"env": {"PATH": "/x"}},  # owned by the platform
        {"env": {"SHOPIFY_FLAG_STORE": "x"}},  # already a setting's env var
        {"secretSlots": {"store": {"env": "OTHER"}}},  # slot name used twice
    ],
)
def test_addon_env_conflicts_rejected(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        AddonManifest.model_validate(ADDON | change)


@pytest.mark.rule("access.keys-are-references")
def test_binding_is_strict_and_references_secrets() -> None:
    b = binding(settings={"store": "s.myshopify.com"}, secrets={"theme_token": {"env": "T"}})
    check_binding(b, AddonManifest.model_validate(ADDON))
    with pytest.raises(ValidationError):
        binding(secrets={"theme_token": "shptka_literal"})  # E2: never a value
    with pytest.raises(ValidationError):
        binding(extra="typo")


@pytest.mark.rule("connection.fills-its-tool-s-slots")
def test_g1_binding_slots_checked_against_addon() -> None:
    addon = AddonManifest.model_validate(ADDON)
    with pytest.raises(ValueError, match="required setting store"):
        check_binding(binding(), addon)
    with pytest.raises(ValueError, match="not declared"):
        check_binding(binding(settings={"store": "s", "shop": "t"}), addon)


# ── generated JSON Schemas ──────────────────────────────────────────────


def test_committed_schemas_up_to_date() -> None:
    for name, content in render().items():
        assert (DEFAULT_OUT_DIR / name).read_text() == content, f"{name} is stale"


@pytest.mark.rule("network.an-entry-is-a-host-and-its-port")
def test_egress_entry_accepts_ipv4() -> None:
    TypeAdapter(EgressEntry).validate_python("192.168.1.20:11434")
    for bad in ("256.1.1.1:80", "1.2.3:80", "192.168.1.20"):
        with pytest.raises(ValidationError):
            TypeAdapter(EgressEntry).validate_python(bad)


# ── I: automations ──────────────────────────────────────────────────────

AUTOMATION_TOML = """
apiVersion = "handler.automation/v1"
description = "What my agents lacked in their environment"
when = "session.stopped"
only = { project = ["my-app"] }

run = "python3 extract.py"
services = { llm = ["mistral/mistral-large"] }

[[append]]
from = "note.md"
to = "handler/env-issues.md"
"""


def test_i1_the_example_automation_validates() -> None:
    automation = Automation.from_toml(AUTOMATION_TOML)
    assert automation.only is not None and automation.only.project == ["my-app"]
    assert automation.services is not None and automation.services.llm == ["mistral/mistral-large"]
    assert automation.append[0].from_ == "note.md" and automation.timeout_sec is None
    assert automation.script == "python3 extract.py" and automation.schedule is None
    assert automation.model_dump(by_alias=True, exclude_none=True)["append"] == [
        {"from": "note.md", "to": "handler/env-issues.md"}
    ]


@pytest.mark.parametrize(
    "change",
    [
        {"when": "session.started"},  # the only event of v1
        {"timeoutSec": 3601},
        {"servics": {"llm": ["a/b"]}},  # unknown keys are errors
        {"services": {"llm": ["mistral-large"]}},  # "provider/model"
        {"append": [{"from": "/etc/passwd", "to": "x.md"}]},
        {"append": [{"from": "../x", "to": "x.md"}]},
    ],
)
def test_i1_automation_rejects(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Automation.model_validate(tomllib.loads(AUTOMATION_TOML) | change)


SCHEDULED = {"apiVersion": "handler.automation/v1", "when": {"every": "1h"}}


def test_i1_a_scheduled_agent_run_and_app_call() -> None:
    agent = Automation.model_validate(
        SCHEDULED
        | {"run": {"agent": "reviewer", "project": "handler", "input": {"fields": {"a": 1}}}}
    )
    assert agent.schedule is not None and agent.schedule.every_minutes == 60
    assert agent.agent_run is not None and agent.agent_run.input.fields == {"a": 1}
    assert agent.script is None and agent.app_call is None
    app = Automation.model_validate(
        {"apiVersion": "handler.automation/v1", "when": {"at": "08:30", "days": ["mon", "fri"]}}
        | {"run": {"app": "coach", "call": "POST /api/cron/morning"}}
    )
    assert app.schedule is not None and app.schedule.label == "at 08:30 mon,fri"
    assert app.app_call is not None and app.app_call.app == "coach"


@pytest.mark.parametrize(
    "change",
    [
        {"when": {"every": "4m"}},  # at least 5m
        {"when": {"every": "1h", "at": "08:00"}},  # one rule
        {"when": {"every": "1h", "days": ["mon"]}},  # days go with at
        {"when": {"at": "08:00", "days": []}},
        {"when": {"at": "25:00"}},
        {"only": {"project": ["x"]}},  # only goes with a session that stopped
        {"run": {"agent": "a"}, "append": [{"from": "x.md", "to": "x.md"}]},  # a script's
        {"run": {"agent": "a"}, "timeoutSec": 60},
        {"run": {"agent": "a", "input": {"field": {}}}},  # unknown key
        {"run": {"app": "coach", "call": "GET /api/x"}},  # POST /api/… only
    ],
)
def test_i1_schedule_and_runs_reject(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Automation.model_validate(SCHEDULED | {"run": "true"} | change)
