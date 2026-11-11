"""Talking to handlerd: the Control API (contract D) over HTTP, ACP (contract C) over WebSocket.

Discovery: `$HANDLER_URL` (default http://127.0.0.1:<DEFAULT_PORT>) and the token file
`$HANDLER_CONFIG_DIR/token` (default ~/.config/handler-ai/token), written by the daemon on first
start.
"""

import os
from pathlib import Path
from typing import Any

import httpx

from handler_contracts import DEFAULT_PORT, TOKEN_FILE_NAME


class ClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        status: int | None = None,
        title: str | None = None,
        detail: str | None = None,
        toolbox_adds: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status, self.title, self.detail = status, title, detail  # handlerd's answer, if any
        self.toolbox_adds = toolbox_adds  # 409 "toolbox changes not confirmed": to send back


def base_url() -> str:
    port = os.environ.get("HANDLER_PORT", str(DEFAULT_PORT))
    return os.environ.get("HANDLER_URL", f"http://127.0.0.1:{port}").rstrip("/")


def token_file() -> Path:
    xdg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return Path(os.environ.get("HANDLER_CONFIG_DIR", xdg / "handler-ai")) / TOKEN_FILE_NAME


def read_token() -> str:
    try:
        return token_file().read_text().strip()
    except FileNotFoundError:
        raise ClientError(
            f"no token at {token_file()}: is handlerd installed and started?"
        ) from None


class Daemon:
    def __init__(self) -> None:
        self.url = base_url()
        self.token = read_token()
        self.http = httpx.Client(
            base_url=self.url, headers={"Authorization": f"Bearer {self.token}"}, timeout=60
        )

    def call(self, method: str, path: str, json: Any = None, timeout: float | None = None) -> Any:
        r = self.request(method, path, json, timeout)
        return r.json() if r.content else None

    def text(self, path: str) -> str:
        """A GET answering plain text (a log, a file)."""
        return self.request("GET", path).text

    def request(
        self,
        method: str,
        path: str,
        json: Any = None,
        timeout: float | None = None,
        content: bytes | None = None,  # a file sent as the body (an app file, H.15)
    ) -> httpx.Response:
        try:
            r = self.http.request(
                method, path, json=json, content=content, timeout=timeout or self.http.timeout
            )
        except httpx.ConnectError:
            raise ClientError(
                f"handlerd is not reachable at {self.url} (handler daemon status)"
            ) from None
        if r.status_code >= 400:
            try:
                problem = r.json()
            except ValueError:
                raise ClientError(f"{r.status_code} {r.text}", r.status_code) from None
            title, detail = problem.get("title"), problem.get("detail")
            message = f"{r.status_code} {title}: {detail or ''}".rstrip(": ")
            raise ClientError(message, r.status_code, title, detail, problem.get("toolboxAdds"))
        return r
