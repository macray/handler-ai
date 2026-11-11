"""handler-sandbox-podman — contract A implementation on rootless podman."""

import sys

from handler_sandbox_kit import runtime_cli

from . import caches, check, images
from .launch import Podman


def main(argv: list[str] | None = None) -> int:
    return runtime_cli.main(
        Podman(), images=images, caches=caches, check=check.check, about=__doc__ or "", argv=argv
    )


if __name__ == "__main__":
    sys.exit(main())
