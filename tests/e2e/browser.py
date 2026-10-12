"""A real browser for the e2e tests: Chromium in Playwright's container image (`--network host`),
used as a remote browser server, so no browser or system libraries are needed on the host.
`HANDLER_TEST_CHROMIUM=/usr/bin/chromium` uses a local Chromium instead (no image to pull)."""

import os
import socket
import subprocess
import time
import uuid
from collections.abc import Iterator

from playwright.sync_api import Browser, sync_playwright

PW_VERSION = "1.63.0"
PW_IMAGE = f"mcr.microsoft.com/playwright:v{PW_VERSION}-noble"


def image_present() -> bool:
    if os.environ.get("HANDLER_TEST_CHROMIUM"):
        return True
    try:
        return subprocess.run(["podman", "image", "exists", PW_IMAGE], check=False).returncode == 0
    except FileNotFoundError:
        return False


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def browser_server() -> Iterator[Browser]:
    if local := os.environ.get("HANDLER_TEST_CHROMIUM"):
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=local, args=["--no-sandbox"])
            yield b
            b.close()
        return
    port, name = free_port(), f"handler-pw-{uuid.uuid4().hex[:8]}"
    server = ["npx", "-y", f"playwright@{PW_VERSION}", "run-server", "--port", str(port)]
    podman = ["podman", "run", "-d", "--rm", "--init", "--name", name, "--network", "host"]
    subprocess.run(
        [*podman, PW_IMAGE, *server, "--host", "127.0.0.1"], check=True, capture_output=True
    )
    try:
        with sync_playwright() as p:
            deadline = time.monotonic() + 90
            while True:
                try:
                    b = p.chromium.connect(f"ws://127.0.0.1:{port}/")
                    break
                except Exception:
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(1)
            yield b
            b.close()
    finally:
        subprocess.run(["podman", "rm", "-f", name], check=False, capture_output=True)
