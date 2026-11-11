"""Daemon settings: where things live and how it listens. All overridable by environment.

HANDLER_PORT                  listening port on 127.0.0.1 (default 7430)
HANDLER_CONFIG_DIR            token file (default ~/.config/handler-ai)
HANDLER_STATE_DIR             agents, sessions, apps (default ~/.local/state/handler-ai)
HANDLER_DATA_DIR              the secret store, apps' versions, data
                              (default ~/.local/share/handler-ai)
HANDLER_ACCOUNTS_DIR          accounts (harness logins and keys) (default <config>/accounts)
HANDLER_PROVIDERS_DIR         providers (endpoints, keys, models) (default <config>/providers)
HANDLER_CONNECTIONS_DIR       connections (tool + instance + credentials) (default <config>/connections)
HANDLER_CACHE_DIR             the toolbox's global caches (default ~/.cache/handler-ai)
HANDLER_RUNTIME_DIR           app backends' sockets
                              (default $XDG_RUNTIME_DIR/handler-ai, else <state>)
HANDLER_NOTES_DIR             notes root: folders agents can be given; when unset, the root
                              set from the web UI (<config>/notes.toml), else <data>/notes
HANDLER_ALLOWED_ORIGINS       extra browser origins, comma-separated (the daemon's own is allowed)
HANDLER_SESSION_IDLE_TIMEOUT  seconds before an unattached, idle session is stopped (default 1800)
HANDLER_SESSION_MAX_ATTACH    clients attached to one session at once; beyond, the oldest is
                              closed (default 8)
HANDLER_APP_IDLE_TIMEOUT      seconds before an unused app's backend is stopped (default 600)
HANDLER_RUN_WAIT_TIMEOUT      seconds a job's run waits for its agent's run in progress before it
                              fails (default 1800)
HANDLER_OFFICIAL_SOURCE       the official source's repository (D.26): its https:// URL, or a local
                              git repository, to try one before it is published (default
                              OFFICIAL_SOURCE_URL)
HANDLER_TERMINAL              the terminal an account's login window opens in, a command line the
                              command is appended to (default: Terminal.app on a Mac, else
                              the first found of terminal.TERMINALS)
"""

import os
from dataclasses import dataclass
from pathlib import Path

from handler_contracts import DEFAULT_PORT, TOKEN_FILE_NAME

HOST = "127.0.0.1"  # invariant 5: loopback only
TEMPLATES = Path(__file__).resolve().parent / "data" / "templates"  # platform data, read-only
# the official source (D.26): the git repository of the apps, agents and addons Handler offers
OFFICIAL_SOURCE_URL = "https://github.com/macray/handler-ai-registry"
# the built web UI (scripts/build-web-ui.sh writes it here; the wheel ships it)
WEB_UI = Path(__file__).resolve().parent / "web-ui"


@dataclass(frozen=True)
class Sources:
    """The folders an agent's account (accounts/<name>.toml) or provider
    (providers/<name>.toml) is read from, and where accounts' login files are kept."""

    accounts: Path
    providers: Path
    credentials: Path  # <data>/accounts


@dataclass(frozen=True)
class Settings:
    port: int
    config_dir: Path
    state_dir: Path
    bindings_dir: Path
    allowed_origins: frozenset[str]
    web_ui_dir: Path
    session_idle_timeout: float = 1800.0
    session_max_attach: int = 8
    data_dir: Path = Path.home() / ".local" / "share" / "handler-ai"
    app_idle_timeout: float = 600.0
    run_wait_timeout: float = 1800.0
    knowledge_dir: Path | None = None  # forced by HANDLER_NOTES_DIR; see knowledge.root
    accounts_dir: Path = Path.home() / ".config" / "handler-ai" / "accounts"
    providers_dir: Path = Path.home() / ".config" / "handler-ai" / "providers"
    skills_dir: Path = Path.home() / ".config" / "handler-ai" / "skills"  # skill library (D.17)
    automations_dir: Path = Path.home() / ".config" / "handler-ai" / "automations"  # I.1
    cache_dir: Path = Path.home() / ".cache" / "handler-ai"  # the toolbox's global caches
    # sockets: short paths, tmpfs
    runtime_dir: Path = Path.home() / ".local" / "state" / "handler-ai"
    official_source: str = OFFICIAL_SOURCE_URL

    @property
    def host(self) -> str:
        return HOST

    @property
    def sources(self) -> Sources:
        """Where an agent's account or provider is looked for."""
        return Sources(self.accounts_dir, self.providers_dir, self.data_dir / "accounts")

    @property
    def token_file(self) -> Path:
        return self.config_dir / TOKEN_FILE_NAME

    @property
    def base_url(self) -> str:
        return f"http://{HOST}:{self.port}"

    @classmethod
    def from_env(cls) -> "Settings":
        home = Path.home()
        xdg_config = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
        xdg_state = Path(os.environ.get("XDG_STATE_HOME", home / ".local" / "state"))
        xdg_data = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))
        xdg_cache = Path(os.environ.get("XDG_CACHE_HOME", home / ".cache"))
        config_dir = Path(os.environ.get("HANDLER_CONFIG_DIR", xdg_config / "handler-ai"))
        port = int(os.environ.get("HANDLER_PORT", DEFAULT_PORT))
        state_dir = Path(os.environ.get("HANDLER_STATE_DIR", xdg_state / "handler-ai"))
        xdg_runtime = os.environ.get("XDG_RUNTIME_DIR")
        runtime_dir = Path(xdg_runtime) / "handler-ai" if xdg_runtime else state_dir
        own = {f"http://{HOST}:{port}", f"http://localhost:{port}"}
        extra = {
            o.strip() for o in os.environ.get("HANDLER_ALLOWED_ORIGINS", "").split(",") if o.strip()
        }
        return cls(
            port=port,
            config_dir=config_dir,
            state_dir=state_dir,
            bindings_dir=Path(
                os.environ.get("HANDLER_CONNECTIONS_DIR", config_dir / "connections")
            ),
            accounts_dir=Path(os.environ.get("HANDLER_ACCOUNTS_DIR", config_dir / "accounts")),
            providers_dir=Path(os.environ.get("HANDLER_PROVIDERS_DIR", config_dir / "providers")),
            skills_dir=config_dir / "skills",
            automations_dir=config_dir / "automations",
            allowed_origins=frozenset(own | extra),
            web_ui_dir=WEB_UI,
            session_idle_timeout=float(os.environ.get("HANDLER_SESSION_IDLE_TIMEOUT", "1800")),
            session_max_attach=max(1, int(os.environ.get("HANDLER_SESSION_MAX_ATTACH", "8"))),
            data_dir=Path(os.environ.get("HANDLER_DATA_DIR", xdg_data / "handler-ai")),
            cache_dir=Path(os.environ.get("HANDLER_CACHE_DIR", xdg_cache / "handler-ai")),
            runtime_dir=Path(os.environ.get("HANDLER_RUNTIME_DIR", runtime_dir)),
            app_idle_timeout=float(os.environ.get("HANDLER_APP_IDLE_TIMEOUT", "600")),
            run_wait_timeout=float(os.environ.get("HANDLER_RUN_WAIT_TIMEOUT", "1800")),
            knowledge_dir=Path(forced) if (forced := os.environ.get("HANDLER_NOTES_DIR")) else None,
            official_source=os.environ.get("HANDLER_OFFICIAL_SOURCE", OFFICIAL_SOURCE_URL),
        )
