"""handlerd — the control plane daemon (loopback only).

    handlerd        serve on 127.0.0.1:$HANDLER_PORT (default 7430); see settings.py for paths

On start: bring the user's files to the current format (migrations/), create the token file if
needed, give the user a toolbox folder (the default's copy) if
they have none, sweep leftovers of crashed sandboxes, serve.
"""

import logging
import shutil
import subprocess
import sys

import uvicorn

from handler_contracts import DEFAULT_MAX_MESSAGE_BYTES
from handler_harness import catalog

from . import migrations, sandbox_process
from .api import create_app
from .settings import Settings

log = logging.getLogger("handler.daemon")


def sweep() -> None:
    """Best effort: remove containers/networks left by sandboxes whose launcher died."""
    binary = sandbox_process.binary()
    if shutil.which(binary) or binary.startswith("/"):
        subprocess.run([binary, "sweep"], check=False, capture_output=True, timeout=120)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # the remote connector's polls
    settings = Settings.from_env()
    try:
        migrations.run(settings)
    except migrations.MigrationError as e:
        log.error("cannot start: %s", e)
        return 1
    app = create_app(settings)
    log.info("token file: %s", settings.token_file)
    log.info("accounts:   %s", settings.accounts_dir)
    if catalog.seed_toolbox():
        log.info("toolbox:    %s (copied from the default: yours to edit)", catalog.toolbox_dir())
    try:
        sweep()
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("sweep failed: %s", e)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        ws_max_size=DEFAULT_MAX_MESSAGE_BYTES,
        ws_ping_interval=None,  # clients send their own heartbeats ($/ping, P5)
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
