"""`handler account …` — accounts (contract D.9): a subscription one harness logs in with.

A token login (Claude Code): you run its sign-in yourself (`claude setup-token`, Anthropic's own,
in your browser) and give handler the token it prints, or tell handler where you keep it; handler
never runs that sign-in nor reads its output. A file login (Codex, Vibe): handler runs the harness's
login here and keeps the credential file it leaves.

handler account list                 accounts, their harness, plan, login and contexts
handler account add NAME HARNESS [--description TEXT] [--plan PLAN] [--context CONTEXT …]
                [--token | --token-env VAR | --token-file PATH | --token-command CMD]
                                     PLAN: its subscription's (e.g. pro, max for claude-code),
                                     told to the harness, which cannot learn it from a token.
                                     --context: the project contexts it is made for (Work,
                                     Personal…, or any; none: it runs nowhere a project has one)
                                     --token…: its token login at once (as `handler account token`)
handler account token NAME [--env VAR | --file PATH | --command CMD]
                                     a token login: the token your own sign-in printed (asked
                                     for, or read from stdin), kept in handler's secret store; or
                                     where you keep it: an env var of handlerd, a file (its first
                                     line), a command printing it (e.g. 'pass show claude-pro')
handler account login NAME [--keep-open] a file login: its harness's own login runs here, on this
                                     computer (npx or uvx fetches it), its state in a folder of
                                     its own; handler keeps the file it leaves. --keep-open: wait
                                     for Enter at the end (a window the web UI opened for it)
handler account import NAME FILE     or give a file login done elsewhere: the credential file it
                                     left (e.g. ~/.codex/auth.json after `codex login`)
handler account rm NAME              it and its login (refused while an agent uses it)
"""

import argparse
import contextlib
import fcntl
import getpass
import os
import pty
import pwd
import select
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import tty
from pathlib import Path
from typing import Any

from .client import ClientError, Daemon
from .output import table


def add_parser(sub: Any) -> None:
    account = sub.add_parser("account", help="accounts", description=__doc__,
                             formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    a = account.add_subparsers(dest="account_cmd", required=True)
    a.add_parser("list")
    add = a.add_parser("add")
    add.add_argument("name")
    add.add_argument("harness")
    add.add_argument("--description")
    add.add_argument("--plan")
    add.add_argument(
        "--context",
        action="append",
        metavar="CONTEXT",
        default=[],
        help="a project context it is made for (Work, any…); repeatable",
    )
    given = add.add_mutually_exclusive_group()
    given.add_argument("--token", action="store_true", help="ask for the token now")
    given.add_argument("--token-env", metavar="VAR")
    given.add_argument("--token-file", metavar="PATH")
    given.add_argument("--token-command", metavar="CMD")
    token = a.add_parser("token")
    token.add_argument("name")
    where = token.add_mutually_exclusive_group()
    where.add_argument("--env", metavar="VAR")
    where.add_argument("--file", metavar="PATH")
    where.add_argument("--command", metavar="CMD")
    log_in = a.add_parser("login")
    log_in.add_argument("name")
    log_in.add_argument("--keep-open", action="store_true", help="wait for Enter at the end")
    imp = a.add_parser("import")
    imp.add_argument("name")
    imp.add_argument("file", type=Path)
    a.add_parser("rm").add_argument("name")


def dispatch(args: argparse.Namespace) -> int:
    d = Daemon()
    if args.account_cmd == "list":
        rows = [["NAME", "HARNESS", "PLAN", "LOGIN", "CONTEXTS", "AGENTS"]]
        for a in d.call("GET", "/v1/accounts"):
            harness, plan = a.get("harness") or "?", a.get("plan") or "-"
            contexts = ", ".join(a.get("contexts", [])) or "-"
            rows.append([a["name"], harness, plan, login_status(a), contexts,
                         ", ".join(a["agents"])])  # fmt: skip
        table(rows) if len(rows) > 1 else print("no account")
        return 0
    if args.account_cmd == "add":
        return add(d, args)
    if args.account_cmd == "token":
        return give_token(d, args.name, token_body(args.name, args.env, args.file, args.command))
    if args.account_cmd == "import":
        return import_login(d, args.name, args.file)
    if args.account_cmd == "login":
        return login_window(d, args.name, keep_open=args.keep_open)
    d.call("DELETE", f"/v1/accounts/{args.name}")
    print(f"{args.name}: removed")
    return 0


def login_window(d: Daemon, name: str, *, keep_open: bool) -> int:
    """`handler account login`, its errors said in its own terminal (a window may close at once)."""
    try:
        return login(d, name)
    except ClientError as e:
        print(f"handler: {e}")
        return 1
    finally:
        if keep_open:
            with contextlib.suppress(EOFError, KeyboardInterrupt):
                input("\nPress Enter to close this window.")


def login_status(a: dict[str, Any]) -> str:
    """Its login as `handler account list` says it: logged in (and how), or what is missing."""
    if a["status"] == "invalid":
        return a.get("error") or "invalid"
    if a["status"] != "ready":
        return "; ".join(a.get("problems") or ["not logged in"])
    where = {"secret": "token in handler", "env": "token from an env var",
             "file": "token from a file",
             "command": "token from a command"}.get(a.get("token") or "", "logged in")  # fmt: skip
    expires = a.get("expiresAt")
    return f"{where}, until {expires[:10]}" if expires else where


def add(d: Daemon, args: argparse.Namespace) -> int:
    body = {
        "name": args.name,
        "harness": args.harness,
        "description": args.description,
        "contexts": args.context,
    }
    body |= {"plan": args.plan} if args.plan else {}
    made = d.call("POST", "/v1/accounts", body)
    print(f"{args.name}: created")
    if args.token or args.token_env or args.token_file or args.token_command:
        given = token_body(args.name, args.token_env, args.token_file, args.token_command)
        return give_token(d, args.name, given)
    if made.get("login") == "token":
        print(f"log it in: run `{token_command(d, args.harness)}`, then: handler account token "
              f"{args.name}")  # fmt: skip
    elif made.get("login") == "file":
        print(f"log it in: handler account login {args.name}")
    return 0


def token_command(d: Daemon, harness: str) -> str:
    found = next((h for h in d.call("GET", "/v1/harnesses") if h["name"] == harness), None)
    return ((found or {}).get("login") or {}).get("tokenCommand") or "its sign-in"


def token_body(name: str, env: str | None, file: str | None, command: str | None) -> dict[str, Any]:
    """`PUT …/login`'s body: a reference to where the token is kept, else the token, asked for."""
    if env:
        return {"tokenRef": {"env": env}}
    if file:
        return {"tokenRef": {"file": str(Path(file).expanduser().resolve())}}
    if command:
        return {"tokenRef": {"command": shlex.split(command)}}
    return {"token": ask_token(name)}


def give_token(d: Daemon, name: str, body: dict[str, Any]) -> int:
    if not body.get("tokenRef") and not body.get("token"):
        raise ClientError(f"no token given for {name}")
    return save(d, name, body)


def import_login(d: Daemon, name: str, file: Path) -> int:
    account = next((a for a in d.call("GET", "/v1/accounts") if a["name"] == name), None)
    if account is None:
        raise ClientError(f"no account '{name}' (handler account list)")
    if account.get("login") != "file":
        raise ClientError(f"the login of '{name}' is a token: handler account token {name}")
    return save(d, name, {"file": file.read_text()})


def ask_token(name: str, what: str = "token") -> str:
    prompt = f"{what} for {name}: "
    return (getpass.getpass(prompt) if sys.stdin.isatty() else sys.stdin.readline()).strip()


def save(d: Daemon, name: str, body: dict[str, Any]) -> int:
    made = d.call("PUT", f"/v1/accounts/{name}/login", body)
    logged_in = made["status"] == "ready"
    print(f"{name}: {'logged in' if logged_in else login_status(made)}")
    return 0 if logged_in else 1


def login(d: Daemon, name: str) -> int:
    """A file login (D.9) on this computer, on a terminal of its own relayed to this one: its
    state in a folder given as `{dir}`, then the file it leaves there becomes the account's
    login. A token login is the person's own to run: said, not run."""
    account = next((a for a in d.call("GET", "/v1/accounts") if a["name"] == name), None)
    if account is None:
        raise ClientError(f"no account '{name}' (handler account list)")
    harness = next(
        (h for h in d.call("GET", "/v1/harnesses") if h["name"] == account.get("harness")), None
    )
    recipe = harness and harness.get("login")
    if not recipe:
        raise ClientError(f"'{name}': {account.get('error') or 'its harness has no login'}")
    if recipe.get("tokenCommand"):
        raise ClientError(
            f"'{name}' logs in with a token you make: run `{recipe['tokenCommand']}`, "
            f"then: handler account token {name}"
        )
    if not harness.get("loginFile"):  # a handlerd older than this handler
        raise ClientError("handlerd does not say where the login leaves its file: restart it")
    path = search_path(recipe["command"][0], account["harness"])
    argv = [str(shutil.which(recipe["command"][0], path=path)), *recipe["command"][1:]]
    if recipe.get("help"):
        print(recipe["help"])
    with tempfile.TemporaryDirectory(prefix="handler-login-") as folder:
        env = (
            dict(os.environ)
            | {"PATH": path}
            | {k: v.replace("{dir}", folder) for k, v in (recipe.get("env") or {}).items()}
        )
        code = on_terminal(argv, env, folder)
        file = Path(folder) / harness["loginFile"]
        if not file.is_file() or not file.read_text(errors="replace").strip():
            print(f"\n{name}: not logged in: it left no {file.name} (exit {code})")
            return 1
        return save(d, name, {"file": file.read_text()})


def search_path(program: str, harness: str) -> str:
    """The PATH the login runs with: this one when it has the program, else the person's login
    shell's (a window handlerd opened has handlerd's, a systemd service's: without ~/.local/bin…),
    where what the program needs (node for npx) is too."""
    for path in (os.environ.get("PATH", ""), login_path()):
        if shutil.which(program, path=path):
            return path
    raise ClientError(
        f"the {harness} login runs {program} on this computer: install it "
        "(npx: Node.js and npm; uvx: uv)"
    )


def login_path() -> str:
    shell = pwd.getpwuid(os.getuid()).pw_shell or "/bin/sh"
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        printed = subprocess.run(
            [shell, "-lc", "printenv PATH"],
            capture_output=True,
            text=True,
            timeout=10,
            stdin=subprocess.DEVNULL,
            check=False,
        ).stdout.strip()
        if printed:
            return printed.splitlines()[-1]  # after what its shell profile may print
    return ""


def on_terminal(argv: list[str], env: dict[str, str], cwd: str) -> int:
    """Run `argv` on a terminal of its own, relayed to this one (raw while it runs, resized with
    it): its exit code."""
    pid, master = pty.fork()
    if pid == 0:  # the child, on the new terminal
        os.chdir(cwd)
        os.execve(argv[0], argv, env)
    interactive = sys.stdin.isatty()
    saved = termios.tcgetattr(0) if interactive else None

    def resize(*_: object) -> None:
        cols, rows = shutil.get_terminal_size()
        fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    resize()
    inputs = [0, master]
    try:
        if interactive:
            tty.setraw(0)
            signal.signal(signal.SIGWINCH, resize)
        while True:
            ready, _, _ = select.select(inputs, [], [])
            if master in ready:
                try:
                    data = os.read(master, 65536)
                except OSError:  # EIO: the command and all it started are gone
                    data = b""
                if not data:
                    break
                os.write(1, data)
            if 0 in ready:
                data = os.read(0, 4096)
                if data:
                    os.write(master, data)
                else:  # stdin ended (piped): the command goes on without it
                    inputs.remove(0)
    finally:
        if saved is not None:
            termios.tcsetattr(0, termios.TCSADRAIN, saved)
            signal.signal(signal.SIGWINCH, signal.SIG_DFL)
        os.close(master)
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status)
