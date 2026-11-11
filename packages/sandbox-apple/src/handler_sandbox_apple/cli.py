"""handler-sandbox-apple — contract A implementation on Apple's `container` (a virtual machine
per sandbox, macOS 26 on Apple silicon). Experimental: written before a Mac ran it."""

import sys

from handler_sandbox_kit import runtime_cli

from . import caches, check, images
from .launch import Apple


def main(argv: list[str] | None = None) -> int:
    return runtime_cli.main(
        Apple(), images=images, caches=caches, check=check.check, about=__doc__ or "", argv=argv
    )


if __name__ == "__main__":
    sys.exit(main())
