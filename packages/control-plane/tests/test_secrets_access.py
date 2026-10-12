"""Unit tests: secret resolution (E2), an agent's harness resolved with its account or provider
(E1, access.py), account and provider status."""

from pathlib import Path

import pytest

from handler_contracts import (
    AccountLoginRequest,
    CommandSecret,
    EnvSecret,
    FileSecret,
    StoreSecret,
)
from handler_control import access, accounts, launcher, providers, secrets
from handler_control.settings import TEMPLATES, Settings, Sources
from handler_harness import catalog

STORE = secrets.SecretStore(Path("/nonexistent"))  # empty: for the other kinds of reference


def test_store_put_get_list_delete(tmp_path: Path) -> None:
    store = secrets.SecretStore(tmp_path)
    store.put("providers/or/apiKey", "sk-1", "OpenRouter key")
    store.put("apps/notes/TOKEN", "t")
    store.put("apps/notes/OTHER", "o")
    assert (tmp_path / secrets.STORE_FILE).stat().st_mode & 0o777 == 0o600
    assert store.get("providers/or/apiKey") == "sk-1"
    [notes_other, notes_token, key] = store.list()
    assert (key.path, key.description) == ("providers/or/apiKey", "OpenRouter key")
    assert notes_token.path == "apps/notes/TOKEN" and "sk-1" not in key.model_dump_json()
    store.put("providers/or/apiKey", "sk-2")  # replaced; created kept
    assert store.get("providers/or/apiKey") == "sk-2"
    assert store.list()[-1].created_at == key.created_at
    assert store.delete("apps/notes") and store.get("apps/notes/TOKEN") is None
    assert not store.delete("apps/notes")
    assert [s.path for s in store.list()] == ["providers/or/apiKey"]
    assert notes_other.path == "apps/notes/OTHER"


def test_store_secret(tmp_path: Path) -> None:
    store = secrets.SecretStore(tmp_path)
    ref = StoreSecret(secret="providers/or/apiKey")
    with pytest.raises(secrets.SecretError, match="handler secret set providers/or/apiKey"):
        secrets.resolve(ref, store)
    store.put("providers/or/apiKey", "sk-1")
    assert secrets.resolve(ref, store) == "sk-1"


def test_env_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HANDLER_T_SECRET", "v1")
    assert secrets.resolve(EnvSecret(env="HANDLER_T_SECRET"), STORE) == "v1"


def test_missing_env_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HANDLER_T_MISSING", raising=False)
    with pytest.raises(secrets.SecretError, match="not set"):
        secrets.resolve(EnvSecret(env="HANDLER_T_MISSING"), STORE)


def test_file_secret_first_line(tmp_path: Path) -> None:
    f = tmp_path / "key"
    f.write_text("  sk-123  \nsecond line\n")
    assert secrets.resolve(FileSecret(file=str(f)), STORE) == "sk-123"


def test_command_secret() -> None:
    assert secrets.resolve(CommandSecret(command=["echo", "from-cmd"]), STORE) == "from-cmd"


def test_failing_command_secret_does_not_leak_output() -> None:
    with pytest.raises(secrets.SecretError) as e:
        secrets.resolve(CommandSecret(command=["sh", "-c", "echo leaked; exit 3"]), STORE)
    assert "leaked" not in str(e.value)


ACCOUNT = """
apiVersion = "handler.account/v1"
harness = "claude-code"
"""

PROVIDER = """
apiVersion = "handler.provider/v1"
[endpoints]
anthropic = "https://api.anthropic.com"
[[models]]
id = "m1"
"""


def sources(tmp_path: Path) -> Sources:
    return Sources(tmp_path / "accounts", tmp_path / "providers")


def test_resolve_with_its_account_or_provider(tmp_path: Path) -> None:
    source = sources(tmp_path)
    for folder in (source.accounts, source.providers):
        folder.mkdir()
    (source.accounts / "claude.toml").write_text(ACCOUNT)
    (source.accounts / "nope.toml").write_text(ACCOUNT.replace("claude-code", "nope"))
    (source.providers / "api.toml").write_text(PROVIDER)
    good = access.resolve(source, "claude-code", account="claude", model="opus")
    assert (good.account, good.harness, good.account_login, good.config.model) == (
        "claude",
        "claude-code",
        None,
        "opus",
    )
    assert access.account_harness(source, "claude") == "claude-code"
    with pytest.raises(ValueError, match="unknown harness"):
        access.resolve(source, "nope-harness", account="claude")
    with pytest.raises(ValueError, match="no account 'gone'"):
        access.resolve(source, "claude-code", account="gone")
    with pytest.raises(ValueError, match="is for harness 'claude-code', not 'codex'"):
        access.resolve(source, "codex", account="claude")
    with pytest.raises(ValueError, match="unknown harness 'nope'"):
        access.account_harness(source, "nope")
    with_provider = access.resolve(source, "claude-code", provider="api")
    assert with_provider.provider_spec is not None
    assert with_provider.provider_spec.models[0].id == "m1"
    with pytest.raises(ValueError, match="no provider 'gone'"):
        access.resolve(source, "claude-code", provider="gone")


def test_a_provider_the_harness_cannot_speak_or_a_model_it_lacks_is_refused(
    tmp_path: Path,
) -> None:
    source = sources(tmp_path)
    source.providers.mkdir(parents=True)
    (source.providers / "chat.toml").write_text(
        PROVIDER.replace("anthropic =", '"openai-chat" =').replace("api.anthropic.com", "x.example")
    )
    (source.providers / "api.toml").write_text(PROVIDER)
    with pytest.raises(ValueError, match=r"speaks openai-chat, harness .claude-code. accepts"):
        access.resolve(source, "claude-code", provider="chat")
    with pytest.raises(ValueError, match="has no model 'm2' \\(it serves: m1\\)"):
        access.resolve(source, "claude-code", provider="api", model="m2")
    access.resolve(source, "claude-code", provider="api", model="m1")
    with pytest.raises(ValueError, match="accepts: openai-chat"):
        access.resolve(source, "pi", provider="api")


def test_accounts_and_their_login(tmp_path: Path) -> None:
    """D.9: an account is its harness and a description; handler keeps its login."""
    folder, credentials, store = (
        tmp_path / "accounts",
        tmp_path / "kept",
        secrets.SecretStore(tmp_path),
    )
    claude = accounts.create(folder, "perso", "claude-code", "Claude, personal")
    assert (claude.account and claude.account.description) == "Claude, personal"
    assert (folder / "perso.toml").stat().st_mode & 0o777 == 0o600
    assert not accounts.logged_in(claude, credentials, store)
    with pytest.raises(accounts.AccountError, match="exists"):
        accounts.create(folder, "perso", "claude-code", None)
    with pytest.raises(accounts.AccountError, match="is a token"):
        accounts.save_login(claude, credentials, store, AccountLoginRequest(file="{}"))
    code = AccountLoginRequest(token="QhR9xk2vL7mN#a4Bc")  # what the sign-in page shows
    with pytest.raises(accounts.AccountError, match="starts with sk-ant-oat01-"):
        accounts.save_login(claude, credentials, store, code)
    accounts.save_login(claude, credentials, store, AccountLoginRequest(token="sk-ant-oat01-x"))
    claude = accounts.get(folder, "perso")  # its file now says where its token is
    assert claude.account is not None and claude.account.token is not None
    assert accounts.logged_in(claude, credentials, store)
    [info] = store.list()
    assert info.path == "accounts/perso/token"

    codex = accounts.create(folder, "chatgpt", "codex", None)
    accounts.save_login(codex, credentials, store, AccountLoginRequest(file='{"tokens": 1}'))
    kept = accounts.credential_file(credentials, "chatgpt")
    assert kept.read_text() == '{"tokens": 1}' and kept.stat().st_mode & 0o777 == 0o600
    moved = accounts.update(folder, credentials, store, codex, name="plus", description="ChatGPT")
    assert moved.account is not None and accounts.logged_in(moved, credentials, store)
    assert not (folder / "chatgpt.toml").exists() and not kept.exists()

    renamed = accounts.update(folder, credentials, store, claude, name="mine", description=None)
    assert store.get("accounts/mine/token") == "sk-ant-oat01-x"
    assert accounts.logged_in(renamed, credentials, store)  # its reference followed
    accounts.delete(folder, credentials, store, "mine")
    assert store.list() == [] and not (folder / "mine.toml").exists()
    assert renamed.name == "mine"

    with pytest.raises(accounts.AccountError, match="unknown harness"):
        accounts.create(folder, "y", "nope-harness", None)
    assert not (folder / "y.toml").exists()


def test_a_token_by_reference_is_checked_at_launch(tmp_path: Path) -> None:
    """D.9: a token handler only knows where to find is checked when an agent starts on it."""
    settings = Settings(
        port=0,
        config_dir=tmp_path,
        state_dir=tmp_path,
        bindings_dir=tmp_path,
        allowed_origins=frozenset(),
        web_ui_dir=tmp_path,
        data_dir=tmp_path,
        accounts_dir=tmp_path / "accounts",
    )
    kept = tmp_path / "token"
    (tmp_path / "accounts").mkdir()
    (tmp_path / "accounts" / "claude.toml").write_text(ACCOUNT + f'token = {{file = "{kept}"}}\n')
    agent = access.resolve(settings.sources, "claude-code", account="claude")
    descriptor = catalog.get("claude-code").descriptor
    store = secrets.SecretStore(tmp_path)
    kept.write_text("QhR9xk2vL7mN#a4Bc\n")
    with pytest.raises(launcher.AgentStartError, match="not the token `claude setup-token`"):
        launcher.account_login(settings, agent, descriptor, store)
    kept.write_text("sk-ant-oat01-x\n")
    assert launcher.account_login(settings, agent, descriptor, store) == "sk-ant-oat01-x"


def test_an_account_names_a_harness_that_logs_in(tmp_path: Path) -> None:
    (tmp_path / "a.toml").write_text(ACCOUNT + '[login]\nauth_json = "/x"\n')
    assert "login" in (accounts.get(tmp_path, "a").error or "")  # the login is never in the file
    (tmp_path / "b.toml").write_text(ACCOUNT.replace("claude-code", "nope"))
    assert "unknown harness" in (accounts.get(tmp_path, "b").error or "")


def test_provider_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HANDLER_T_KEY", raising=False)
    (tmp_path / "p.toml").write_text('apiKey = { env = "HANDLER_T_KEY" }\n' + PROVIDER)
    provider = providers.get(tmp_path, "p").provider
    assert provider is not None
    assert [p.split(":")[0] for p in providers.problems(provider, STORE)] == ["apiKey"]
    monkeypatch.setenv("HANDLER_T_KEY", "k")
    assert providers.problems(provider, STORE) == []
    assert providers.harnesses(provider) == ["claude-code"]  # the only one speaking anthropic
    assert providers.get(tmp_path, "missing").error
    (tmp_path / "bad.toml").write_text(PROVIDER.replace("https://", "ftp://"))
    assert "http:// or https://" in (providers.get(tmp_path, "bad").error or "")


def test_provider_templates_are_valid() -> None:
    found = {t.name: t for t in providers.templates(TEMPLATES)}
    assert set(found) == {
        "anthropic-api",
        "llamacpp",
        "mistral-api",
        "ollama",
        "openai-api",
        "openrouter",
    }
    llamacpp = found["llamacpp"].files  # how Codex talks to a model it does not know
    assert llamacpp is not None and set(llamacpp["codex"]) == {"instructions_md"}
