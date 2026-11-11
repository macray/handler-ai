"""`handler setup`: from an installed handler to a working one, safe to run again.

1. handlerd as a user service (`handler daemon install`: systemd, launchd on macOS), started;
   on its first start it writes the token and the default toolbox.toml in
   ~/.config/handler-ai/toolbox/ (the system packages on: podman, wl-clipboard). Without a
   systemd user session: the handlerd already running, else only step 2, through a handlerd
   started for it
2. on macOS, before the first build: where agents run, among the runtime in use (Apple container
   by default) and each other installed one whose check passes (Docker), the one in use first
   (`--runtime`, else asked; kept with --yes). Linux: only with `--runtime`
3. what the container runtime finds missing on this machine (GET /v1/runtime, A.8)
4. the network filter (D.4), when it is not built: handlerd builds it as it starts, this follows
   that build (or starts it)
5. the images, when the toolbox or no agent program is built yet: first the engine agents
   that run containers use (podman by default, or docker: `--engine`, else asked), the agent
   program to build first (`--program`, else asked; the first one listed with --yes), then the toolbox and
   that program's image, each checked (`handler image rebuild toolbox`, then NAME), one line per
   image and the log in a file (--verbose: the log here); skipped with --no-build. The other
   agent programs are built when an agent needs one (Prepare now) or from Settings → Sandboxes
6. where the web UI is (`handler ui`)
"""

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from handler_contracts import ABILITY_NEEDS

from . import daemon_commands, image_commands, runtime_commands
from .client import ClientError, Daemon, base_url

START_TIMEOUT = 60.0


def add_parser(sub: Any) -> None:
    s = sub.add_parser("setup", help="install and start handlerd, check this machine, build images")
    s.add_argument("--no-build", action="store_true", help="do not build the images now")
    s.add_argument("--yes", action="store_true", help="build the images without asking")
    s.add_argument(
        "--program",
        metavar="NAME",
        help="the agent program to build first (`handler image list` names them; with --yes, "
        "the first one): the others are built when an agent needs one",
    )
    image_commands.verbose_flag(s)
    s.add_argument(
        "--runtime",
        metavar="NAME",
        help="where agents run (`handler runtime list` names them): on macOS apple (the default) "
        "or docker; not the engine agents run containers with (--engine)",
    )
    s.add_argument(
        "--engine",
        metavar="PACKAGE",
        help="what agents that run containers use, inside their sandbox, before the first build: "
        "a system package giving an engine (podman, the default, or docker)",
    )


def _daemon(started: subprocess.Popen[bytes] | None = None) -> Daemon:
    """handlerd, once it answers (it writes its token on its first start); `started`: the one
    started here, which may stop first."""
    deadline = time.monotonic() + START_TIMEOUT
    while True:
        try:
            d = Daemon()
            d.call("GET", "/v1/health")
            return d
        except ClientError:
            if started and started.poll() is not None:
                raise ClientError("handlerd stopped: its output is above") from None
            if time.monotonic() > deadline:
                raise ClientError(
                    f"handlerd did not start within {START_TIMEOUT:.0f} s: "
                    "`handler daemon log` shows why"
                ) from None
            time.sleep(1)


def _offer(runtime: dict[str, Any]) -> str:
    """A runtime offered, with what each sandbox is there, or why it cannot run sandboxes yet."""
    check = runtime["check"] or {}
    if supports := check.get("supports"):
        return f"{runtime['name']}: each sandbox is {supports['isolation']}"
    failing = [i["detail"] for i in check.get("items", []) if i["required"] and not i["ok"]]
    return f"{runtime['name']}: not ready here ({'; '.join(failing) or 'it cannot say why'})"


def _choose_runtime(d: Daemon, args: argparse.Namespace) -> None:
    """Where agents run (D.2), chosen before the first build: the flag's, else on macOS asked on
    a terminal among the one in use (first: Enter keeps it) and each other installed one whose
    check passes; one alone is not asked."""
    choice = args.runtime
    if choice is None:
        if not daemon_commands.macos() or args.yes or not sys.stdin.isatty():
            return
        if d.call("GET", "/v1/toolbox")["imagePresent"]:
            return  # built: `handler runtime use` changes it
        runtimes = d.call("GET", "/v1/runtimes")
        offered = [r for r in runtimes if r["current"]]
        offered += [r for r in runtimes if not r["current"] and (r["check"] or {}).get("ok")]
        if len(offered) < 2:
            return
        names = [r["name"] for r in offered]
        print("\nWhere should agents run? Each runtime builds its own images.")
        for r in offered:
            print(f"  {_offer(r)}")
        answer = input(f"[{'/'.join(names)}] ({names[0]}) ").strip().lower()
        choice = answer or names[0]
        if choice not in names:
            raise ClientError(f"'{choice}' is not offered here: one of {', '.join(names)}")
    _use_runtime(d, choice)


def _use_runtime(d: Daemon, name: str) -> None:
    """Switch to runtime `name`, after any build running in the one in use: handlerd builds the
    network filter as it starts (a runtime changes only while nothing runs, D.2)."""
    waiting = False
    while True:
        try:
            d.call("PUT", "/v1/runtime", {"name": name})
            return
        except ClientError as e:
            building = any(b["state"] == "running" for b in d.call("GET", "/v1/builds"))
            if e.status != 409 or not building:
                raise
        if not waiting:
            print(f"Waiting for the build running now to end before switching to {name}…")
            waiting = True
        time.sleep(1)


def _runtime(d: Daemon) -> bool:
    check = d.call("GET", "/v1/runtime")
    print(f"\n{check['runtime']}")
    for item in check["items"]:
        mark = "ok  " if item["ok"] else ("FAIL" if item["required"] else "warn")
        print(f"  {mark} {item['name']}: {item['detail']}")
    if supports := check.get("supports"):
        print(f"  each sandbox is {supports['isolation']}")
        print(f"  {runtime_commands.not_given(supports)}")
    if not check["ok"]:
        print("\nAgents cannot run here yet: fix what FAIL says, then run `handler setup` again.")
    return bool(check["ok"])


def _network_filter(d: Daemon, verbose: bool) -> int:
    """Follow handlerd's build of the network filter, or start it; 0 once it is built."""
    if d.call("GET", "/v1/network-filter")["imagePresent"]:
        return 0
    print(
        "\nBuilding the network filter: it checks where agents connect and adds your secrets to "
        "their requests (about 240 MB, a minute or two)."
    )
    while True:
        for build in d.call("GET", "/v1/builds"):
            if build["target"] == "network-filter" and build["state"] == "running":
                return image_commands.watch(d, build, verbose)
        try:
            return image_commands.watch(d, d.call("POST", "/v1/network-filter/rebuild"), verbose)
        except ClientError as e:  # handlerd started its own meanwhile, or another build runs
            if e.status != 409:
                raise
            time.sleep(1)


def _program(args: argparse.Namespace, harnesses: list[dict[str, Any]]) -> dict[str, Any]:
    """The agent program to build first: the flag's, else asked on a terminal, else the
    first one handlerd lists (the default)."""
    names = [h["name"] for h in harnesses]
    default = names[0]
    choice = args.program
    if choice is None and not args.yes:
        offered = ", ".join(f"{h['product']} ({h['name']})" for h in harnesses)
        answer = input(
            f"\nWhich agent program first? {offered}. The others are built when an agent needs "
            f"one. [{'/'.join(names)}] ({default}) "
        )
        choice = answer.strip() or default
    for h in harnesses:
        if (choice or default).lower() in (h["name"], h["product"].lower()):
            return h
    raise ClientError(f"'{choice}' is not an agent program: one of {', '.join(names)}")


def _wants_build(args: argparse.Namespace, toolbox: bool, program: str) -> bool:
    """`toolbox`: it is built with the program."""
    if args.yes:
        return True
    question = (
        f"Build the images now? The toolbox, then {program}: about 1 GB, from a minute on a "
        "fast network to a quarter of an hour on a slow one."
        if toolbox
        else f"Build {program} now? A few minutes."
    )
    return input(f"\n{question} [Y/n] ").strip().lower() in ("", "y", "yes")


def _build(d: Daemon, toolbox: bool, program: dict[str, Any] | None, verbose: bool) -> int:
    """The toolbox (when `toolbox`), then `program` (when not built), one line per image."""
    stages = image_commands.Stages(d)
    if toolbox:
        stages.after = 1 if program else 0
        build = d.call("POST", "/v1/toolbox/rebuild")
        if code := image_commands.watch(d, build, verbose, stages):
            return code
    if program is None:
        return 0
    stages.after = 0
    build = d.call("POST", f"/v1/{image_commands.path(program['name'])}/rebuild")
    return image_commands.watch(d, build, verbose, stages)


def engines(d: Daemon) -> list[str]:
    """The system packages giving the engine of agents that run containers (B.6: `nested`'s
    need), the default first."""
    commands = ABILITY_NEEDS["nested"]
    giving = {
        p["name"]: min(commands.index(c) for c in p["provides"] if c in commands)
        for p in d.call("GET", "/v1/toolbox/system-packages")
        if not p.get("error") and set(p.get("provides", [])) & set(commands)
    }
    return sorted(giving, key=lambda name: (giving[name], name))


def _engine(d: Daemon, args: argparse.Namespace, on: list[str]) -> list[str]:
    """The engine agents that run containers use, chosen before the toolbox's first build: the
    flag's, else asked on a terminal, else the default toolbox's. The others are turned off;
    returns the system packages on."""
    found = engines(d)
    engine = args.engine
    if engine is None and not args.yes and sys.stdin.isatty() and len(found) > 1:
        answer = input(
            f"\nAgents that run containers use {' or '.join(found)} ({found[0]} by default). "
            f"Which one? [{'/'.join(found)}] "
        )
        engine = answer.strip().lower() or found[0]
    if engine is None:
        return on
    if engine not in found:
        raise ClientError(f"'{engine}' gives no engine: one of {', '.join(found)}")
    if engine in on and not [p for p in found if p != engine and p in on]:
        return on
    chosen = [engine, *(p for p in on if p not in found)]
    d.call("PUT", "/v1/toolbox/system-packages", {"systemPackages": chosen})
    return [p["name"] for p in d.call("GET", "/v1/toolbox")["systemPackages"]]  # in its order


def _engine_not_chosen(d: Daemon, engine: str, on: list[str]) -> None:
    """--engine once the toolbox is built: setup no longer chooses it; `handler toolbox` does."""
    found = engines(d)
    if engine not in found:
        raise ClientError(f"'{engine}' gives no engine: one of {', '.join(found)}")
    others = [p for p in found if p != engine and p in on]
    if engine in on and not others:
        return
    steps = [f"`handler toolbox add {engine}`"] if engine not in on else []
    steps += [f"`handler toolbox rm {' '.join(others)}`"] if others else []
    print(
        f"--engine {engine}: the toolbox is built, setup leaves it as it is: {', then '.join(steps)}."
    )


def _program_not_built(program: dict[str, Any], no_build: bool) -> None:
    """--program when setup builds nothing: what builds it."""
    if program["imagePresent"]:
        return  # built already: listed above
    why = "nothing is built now (--no-build)" if no_build else "setup builds the first one only"
    print(
        f"--program {program['name']}: {why}; "
        f"`handler image rebuild {program['name']}` builds {program['product']}."
    )


def dispatch(args: argparse.Namespace) -> int:
    manager = "launchd" if daemon_commands.macos() else "systemd"
    print(f"Installing handlerd as a user service ({manager})…")
    try:
        code = daemon_commands.install(dry_run=False)
    except OSError as e:  # no systemctl, launchctl
        code = 1
        print(e)
    if not code:
        d = _daemon()
        print(f"handlerd {d.call('GET', '/v1/health')['version']} is running at {base_url()}")
        return _setup(d, args)
    print(f"{manager} failed: it only keeps handlerd running as a user service.")
    if daemon_commands.wsl():
        print(
            "On WSL, turn systemd on: add `[boot]` and `systemd=true` to /etc/wsl.conf, "
            "run `wsl --shutdown` in Windows, then open the distribution again."
        )
    return _without_service(args)


def _without_service(args: argparse.Namespace) -> int:
    """No user service (no systemd user session: a server, `su`, a container, WSL without it;
    launchd refusing it): the setup through the handlerd already running, else only the machine
    check, through one started for it."""
    try:
        d = Daemon()
        version = d.call("GET", "/v1/health")["version"]
    except ClientError:
        print("Starting handlerd for the machine check…")
        _check_alone()
        print(
            "\nStart `handlerd` yourself and keep it running (sessions live as long as it does), "
            "then run `handler setup` again."
        )
        return 1  # the images wait for a handlerd that keeps running
    print(f"handlerd {version} is running at {base_url()}")
    code = _setup(d, args)
    print("\nKeep `handlerd` running: sessions live as long as it does.")
    return code


def _check_alone() -> None:
    """The machine check through a handlerd started for it, stopped after; its output shown only
    when it does not start."""
    handlerd = daemon_commands.handlerd_path()
    path = f"{Path(handlerd).parent}{os.pathsep}{os.environ.get('PATH', '')}"
    with tempfile.TemporaryFile() as output:
        started = subprocess.Popen(
            [handlerd], stdout=output, stderr=subprocess.STDOUT, env=os.environ | {"PATH": path}
        )
        try:
            _runtime(_daemon(started))
        except ClientError:
            output.seek(0)
            print(output.read().decode(errors="replace")[-4000:], end="")
            raise
        finally:
            started.terminate()
            started.wait()


def _setup(d: Daemon, args: argparse.Namespace) -> int:
    """From the runtime's choice to the images, with handlerd running."""
    _choose_runtime(d, args)
    if not _runtime(d):
        return 1
    if code := _network_filter(d, args.verbose):
        print(
            "The network filter could not be built: "
            "`handler image rebuild network-filter` tries again."
        )
        return code
    toolbox = d.call("GET", "/v1/toolbox")
    harnesses = d.call("GET", "/v1/harnesses")
    built = [h["product"] for h in harnesses if h["imagePresent"]]
    on = [p["name"] for p in toolbox["systemPackages"]]
    if not toolbox["imagePresent"] and (not args.no_build or args.engine):
        on = _engine(d, args, on)
    elif args.engine:
        _engine_not_chosen(d, args.engine, on)
    print(f"\nYour toolbox (the system every agent works in): {toolbox['directory']}")
    print(f"  system packages: {', '.join(on) or 'none'} (`handler toolbox` changes them)")
    if built:
        print(f"  agent programs built: {', '.join(built)}")
    builds = (not toolbox["imagePresent"] or not built) and not args.no_build
    if args.program and not builds:
        _program_not_built(_program(args, harnesses), args.no_build)
    if builds:
        if not args.yes and not sys.stdin.isatty():
            print("Images not built: run `handler setup --yes [--program NAME]`.")
        else:
            program = _program(args, harnesses)
            if _wants_build(args, not toolbox["imagePresent"], program["product"]):
                missing = None if program["imagePresent"] else program
                if code := _build(d, not toolbox["imagePresent"], missing, args.verbose):
                    return code
                print(
                    f"\n{program['product']} is ready. The other agent programs are built when an "
                    "agent needs one (Prepare now), or in Settings → Sandboxes."
                )
    print(
        "\nDone. Open the web UI with `handler ui`: first Settings → Model access, then a project."
    )
    return 0
