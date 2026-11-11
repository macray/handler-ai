"""handler-harness — inspect and dry-run harness adapters (contract B).

handler-harness list                     harnesses and their image (images are built by handlerd:
                                         `handler image rebuild toolbox` builds the toolbox then
                                         every harness image; `handler image list` shows their
                                         versions)
handler-harness render NAME (--account FILE | --provider FILE) [--model M]
                   [--permissions MODE]  show the HarnessLaunch of harness NAME on that account
                                         or provider (the login, keys and config file contents
                                         replaced by placeholders), for an agent in permission
                                         mode MODE (default: bypass)
"""

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from handler_contracts import Account, AgentSpec, PermissionMode, Provider

from . import catalog, images
from .render import RenderError, render


def cmd_list() -> int:
    for h in catalog.all_harnesses():
        print(f"{h.name:<14} {images.ref(h.descriptor.image, images.LATEST)}")
    return 0


def cmd_render(
    name: str,
    *,
    account_file: Path | None,
    provider_file: Path | None,
    model: str | None,
    permission_mode: PermissionMode,
) -> int:
    harness = catalog.get(name)
    try:
        if account_file is not None:
            account = Account.from_toml(account_file.read_text())
            agent = AgentSpec.resolve(name, model, account=(account_file.stem, account))
        elif provider_file is not None:
            provider = Provider.from_toml(provider_file.read_text())
            agent = AgentSpec.resolve(name, model, provider=(provider_file.stem, provider))
        else:
            raise ValueError("give --account FILE or --provider FILE")
        login = harness.descriptor.login
        if agent.account and login and login.file:  # where handler keeps it
            agent = agent.model_copy(update={"account_login": "<the account's login file>"})
        token = "<secret:account token>" if agent.account and login and login.token else None
        spec = agent.provider_spec
        key = "<secret:provider key>" if spec and spec.api_key else None
        file_placeholders = {slot: f"<content of {slot}>" for slot in (agent.files or {})}
        launch = render(
            harness.descriptor,
            agent,
            file_placeholders,
            provider_key=key,
            account_token=token,
            permission_mode=permission_mode,
        )
    except (ValidationError, RenderError, OSError, ValueError) as e:
        print(f"handler-harness: {e}", file=sys.stderr)
        return 1
    print(launch.model_dump_json(by_alias=True, exclude_none=True, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="handler-harness",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    r = sub.add_parser("render")
    r.add_argument("name")
    access = r.add_mutually_exclusive_group(required=True)
    access.add_argument("--account", type=Path, help="an account file (accounts/<name>.toml)")
    access.add_argument("--provider", type=Path, help="a provider file (providers/<name>.toml)")
    r.add_argument("--model", help="the model (default: the harness's or the provider's)")
    r.add_argument(
        "--permissions",
        choices=["ask", "accept-edits", "bypass"],
        default="bypass",
        help="the agent's permission mode",
    )
    args = parser.parse_args(argv)
    if args.cmd == "list":
        return cmd_list()
    return cmd_render(
        args.name,
        account_file=args.account,
        provider_file=args.provider,
        model=args.model,
        permission_mode=args.permissions,
    )


if __name__ == "__main__":
    sys.exit(main())
