"""The control plane's unit tests never read the user's own configuration; a stub model
provider for those calling models (llm.py, model_agent.py)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from provider_stub import Stub

from handler_control.secrets import SecretStore
from handler_control.settings import Settings
from handler_harness import catalog


@pytest.fixture(autouse=True)
def _default_toolbox(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The default toolbox (read only), in place of `~/.config/handler-ai/toolbox`."""
    monkeypatch.setenv("HANDLER_TOOLBOX_DIR", str(catalog.DEFAULT_TOOLBOX))
    yield


@pytest.fixture
def stub() -> Iterator[Stub]:
    s = Stub()
    yield s
    s.server.shutdown()


@pytest.fixture
def stub_settings(tmp_path: Path, stub: Stub) -> Settings:
    """Two providers on the stub, `chat` (openai-chat) and `claude` (anthropic), model `m`."""
    providers = tmp_path / "providers"
    providers.mkdir()
    base = f"http://host.containers.internal:{stub.port}"  # as a container sees the host
    for name, endpoint in (
        ("chat", f'openai-chat = "{base}/v1"'),
        ("claude", f'anthropic = "{base}"'),
    ):
        (providers / f"{name}.toml").write_text(
            'apiVersion = "handler.provider/v1"\n'
            f'apiKey = {{ secret = "providers/{name}/apiKey" }}\n'
            f'[endpoints]\n{endpoint}\n[[models]]\nid = "m"\n'
        )  # fmt: skip
    store = SecretStore(tmp_path / "data")
    store.put("providers/chat/apiKey", "sk-chat-secret")
    store.put("providers/claude/apiKey", "sk-claude-secret")
    return Settings(
        port=0,
        config_dir=tmp_path,
        state_dir=tmp_path,
        bindings_dir=tmp_path,
        allowed_origins=frozenset(),
        web_ui_dir=tmp_path,
        data_dir=tmp_path / "data",
        providers_dir=providers,
    )
