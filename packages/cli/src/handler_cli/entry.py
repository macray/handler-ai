"""The `handler` command: `handler ask --listen` goes to listen.py before the rest of the CLI is
loaded (a quarter of a second: the recording starts first); anything else to cli.py."""

import sys


def main() -> int:
    args = sys.argv[1:]
    if args[:1] == ["ask"] and set(args[1:]) in ({"--listen"}, {"--listen", "--toggle"}):
        from .listen import run  # noqa: PLC0415

        return run(toggle="--toggle" in args, check=False)
    from .cli import main as cli  # noqa: PLC0415

    return cli()
