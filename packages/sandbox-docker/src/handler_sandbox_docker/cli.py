"""handler-sandbox-docker — contract A implementation on Docker."""

import sys

from handler_sandbox_kit import runtime_cli

from . import caches, check, images
from .launch import Docker


def main(argv: list[str] | None = None) -> int:
    return runtime_cli.main(
        Docker(), images=images, caches=caches, check=check.check, about=__doc__ or "", argv=argv
    )


if __name__ == "__main__":
    sys.exit(main())
