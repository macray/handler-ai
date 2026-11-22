"""Every app of a registry of Handler's (HANDLER_TEST_REGISTRY: a checkout of one), held to what
Handler promises an app (contract H), the same way for each, with no code of its own: installed
from that registry as the official source (D.26), each folder it needs given fresh (its `init`
files copied in, H.2), who works on its jobs the fake harness, its suggested automations made
(off), deployed (its own tests run, its jobs' instructions and schemas checked, H.15); then each
of its actions asked with its form filled minimally from its schema (H.12): one done by its code
answers, one done by a job starts a run that ends with the result the fake harness gives (one
fitting the job's `result` minimally) and calls the job's `then` once (H.11); each scheduled nudge
sent at a slot the scheduler finds due, its `prepare` answering what it may (H.17); uninstalled,
nothing of it is left (H.14). What the app does with its data is its own server tests'; what
cannot be done without knowing the app (a form no simple value fills) is skipped and said in the
test's output (`-s`, or its report on a failure). Opt-in: the registry is not in this
repository, and changes without notice."""

import time
import tomllib
from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from handler_control import interfaces
from handler_control.secrets import SecretStore

from ..support import dev_env
from ..support.daemon import FAKE_SECRET, Daemon, start_daemon
from ..support.sources import REGISTRY
from .conftest import api, real_sandbox_env, requires_app_runtime

pytestmark = requires_app_runtime

FAKE = {"program": "fake", "account": "fake"}
WAIT = 90  # a job's run on the fake harness, a nudge's slot (at most a minute away)


def registry_apps() -> list[Any]:
    """Each `apps/<name>/` of the registry given, by its folder's name."""
    if REGISTRY is None:
        return [
            pytest.param(
                None,
                id="no-registry",
                marks=pytest.mark.skip(reason="HANDLER_TEST_REGISTRY not set"),
            )
        ]
    folder = REGISTRY / "apps"
    names = (
        sorted(p.name for p in folder.iterdir() if (p / "app.toml").is_file())
        if (folder.is_dir())
        else []
    )
    if not names:
        return [
            pytest.param(
                None, id="no-apps", marks=pytest.mark.skip(reason=f"{REGISTRY} has no apps")
            )
        ]
    return [pytest.param(name, id=name) for name in names]


@pytest.fixture(scope="module")
def daemon(data_root: Path) -> Iterator[Daemon]:
    """A handlerd reading the registry as its official source, the fake account logged in (who
    works on the apps' jobs), its scheduler looking every 2 s (its reaper's tick: a quarter of
    the apps' idle time)."""
    assert REGISTRY is not None
    SecretStore(data_root / "handler").put("accounts/fake/token", FAKE_SECRET)
    env = {"HANDLER_DATA_DIR": str(data_root / "handler"), "HANDLER_APP_IDLE_TIMEOUT": "8"}
    yield from start_daemon(extra_env=env | real_sandbox_env(), source=REGISTRY, addons=())


# --- A form filled minimally from its schema ---


class NotTriedError(Exception):
    """A step the test cannot do without knowing the app (a form no simple value fills, an
    action its code refuses until it has data, a job taking no fields): skipped, and said."""


def strings() -> tuple[str, ...]:
    """What a string field is tried with, in this order: a word, then the shapes of the
    patterns forms use (a day, a time, a moment, an address, a link)."""
    today = date.today().isoformat()
    return (
        "test",
        today,
        "10:00",
        f"{today}T10:00:00Z",
        "test@example.com",
        "https://example.com/",
    )


def minimal(schema: dict[str, Any], where: str) -> Any:
    """The least value `schema` takes: its required fields only, a required string "test" (or
    the first of `strings` it takes), an enum its first value, a number 1 (or its minimum), an
    array its fewest items. NotTriedError when none of those fits."""
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "object" or "properties" in schema:
        props = schema.get("properties", {})
        out = {}
        for name in schema.get("required", []):
            if name not in props:
                raise NotTriedError(f"{where}.{name}: required, with no schema")
            out[name] = minimal(props[name], f"{where}.{name}")
        return out
    if kind == "array":
        least = schema.get("minItems", 0)
        return [minimal(schema.get("items", {}), f"{where}[]")] * least if least else []
    if kind == "boolean":
        return False
    if kind in ("number", "integer"):
        tries: list[Any] = [1, schema.get("minimum"), schema.get("exclusiveMinimum")]
        tries += [t + 1 for t in tries[1:] if t is not None]
    elif kind == "string":
        least = schema.get("minLength", 0)
        tries = [*strings(), ("test" * (least // 4 + 1))[: max(least, 4)]]
    else:
        raise NotTriedError(f"{where}: of type {kind!r}")
    for t in tries:
        if t is not None and not interfaces.errors(schema, t):
            return t
    said = ", ".join(f"{k} {schema[k]!r}" for k in ("pattern", "format", "minimum") if k in schema)
    raise NotTriedError(f"{where}: no simple value fits it ({said or kind})")


def filled(schema: dict[str, Any] | None, where: str) -> dict[str, Any]:
    """A form filled minimally, checked against its schema as Handler checks it."""
    if schema is None:
        return {}
    value = minimal(schema, where)
    if found := interfaces.errors(schema, value):
        raise NotTriedError(f"{where}: {value!r} does not fit it: {'; '.join(found)}")
    return value


# --- The steps, each failure naming the app and the step ---


def until(what: Callable[[], Any], failure: str) -> Any:
    deadline = time.monotonic() + WAIT
    while not (found := what()):
        assert time.monotonic() < deadline, failure
        time.sleep(0.5)
    return found


def install(
    daemon: Daemon, folder: str, manifest: dict[str, Any], said: list[str]
) -> dict[str, Any]:
    """From the registry, as the install page does it: each folder made fresh, its secrets,
    who works, its suggested automations (off), then deployed. Its view once deployed."""
    api(daemon, "GET", "/v1/sources")  # the official source read
    r = api(daemon, "POST", f"/v1/sources/official/apps/{folder}")
    assert r.status_code == 201, f"{folder}: install from the registry: {r.text}"
    app = r.json()
    name = app["name"]
    for need, declared in manifest.get("needs", {}).get("files", {}).items():
        path = daemon.make_scope() / need
        body = {"path": str(path), "create": True}
        r = api(daemon, "PUT", f"/v1/apps/{name}/files/{need}", body)
        assert r.status_code == 200, f"{name}: folder {need} given: {r.text}"
        for rel in declared.get("init", []):
            assert (path / Path(rel).name).is_file(), f"{name}: folder {need}: {rel} not copied in"
    for secret in app["secrets"]:
        r = api(daemon, "PUT", f"/v1/apps/{name}/secrets/{secret['name']}", {"value": "test"})
        assert r.status_code == 200, f"{name}: secret {secret['name']} kept: {r.text}"
        said.append(f"secret {secret['name']}: given 'test', not a real one")
    if app["jobs"]:
        r = api(daemon, "PUT", f"/v1/apps/{name}/who-works", FAKE)
        assert r.status_code == 200, f"{name}: who works chosen: {r.text}"
    for i, s in enumerate(app["suggests"]):
        definition = {"apiVersion": "handler.automation/v1", "description": s["description"]}
        definition |= {"when": s["when"], "run": {"app": name} | s["run"]}
        body = {"name": f"{name}-suggested-{i}", "definition": definition, "enable": False}
        r = api(daemon, "POST", "/v1/automations", body)
        assert r.status_code == 201, f"{name}: suggested automation {s['description']!r}: {r.text}"
        assert r.json()["problems"] == [], f"{name}: suggested automation {i}: {r.json()}"
    r = api(daemon, "POST", f"/v1/apps/{name}/deploy")
    log = api(daemon, "GET", f"/v1/apps/{name}/log").json()["text"]
    assert r.status_code == 200, f"{name}: deploy (its tests, its jobs checked):\n{log}"
    return r.json()


def by_code(daemon: Daemon, name: str, action: dict[str, Any], fields: dict[str, Any]) -> None:
    """Its code answers at once an action's result, or refuses it saying why (a 4xx with its
    `error`: what it needs first, which only knowing the app could give): NotTriedError then."""
    act = f"{name}: action {action['name']} {fields}"
    r = api(daemon, "POST", f"/v1/apps/{name}/actions/{action['name']}", {"fields": fields})
    assert r.status_code == 200, f"{act}: {r.text}"
    done = r.json()
    if done["state"] == "succeeded":
        return
    log = api(daemon, "GET", f"/v1/apps/{name}/log").json()["text"]
    answered = [
        ln for ln in log.splitlines() if f"action {action['name']}: {action['route']}" in ln
    ]
    status = answered[-1].rsplit(": ", 1)[-1] if answered else "no answer"
    refused = status.startswith("4") and not done["error"].startswith("answered ")
    assert refused, f"{act}: its code answered no result ({status}): {done['error']}"
    raise NotTriedError(f"its code refused it ({status}): {done['error']}")


def by_job(
    daemon: Daemon, name: str, action: dict[str, Any], fields: dict[str, Any], job: dict[str, Any]
) -> None:
    """A run of its job, ended with the result the fake harness gives; its `then` called once,
    without failing, before the inbox is told."""
    if "fields" not in job:  # Handler refuses fields to a job that takes none
        raise NotTriedError(
            f"job {action['job']} takes no fields: the fake harness has no `answer`"
        )
    answer = filled(job.get("result"), f"job {action['job']}'s result")
    given = fields | {"fake": "valid", "answer": answer}  # the fake harness's: it answers `answer`
    act = f"{name}: action {action['name']} (job {action['job']})"
    r = api(daemon, "POST", f"/v1/apps/{name}/actions/{action['name']}", {"fields": given})
    assert r.status_code == 200, f"{act}: not started: {r.text}"
    done = r.json()
    path = f"/v1/apps/{name}/actions/{action['name']}/runs/{done['runId']}"
    done = until(
        lambda: (d := api(daemon, "GET", path).json())["state"] != "running" and d,
        f"{act}: its run did not end",
    )
    assert done["state"] == "succeeded", f"{act}: its run: {done.get('error')}"
    assert done["result"]["data"] == answer, f"{act}: its result: {done['result']}"
    if "then" not in job:
        return

    def told() -> list[dict[str, Any]]:  # after its `then` (AppRuns._watch)
        inbox = api(daemon, "GET", "/v1/inbox").json()
        return [m for m in inbox if m.get("sessionId") == done["sessionId"]]

    until(told, f"{act}: the inbox was never told its end (its `then` {job['then']} hung?)")
    assert len(told()) == 1, f"{act}: told {len(told())} times"
    (run,) = [
        r for r in api(daemon, "GET", f"/v1/apps/{name}/runs").json() if r["id"] == done["runId"]
    ]
    assert run.get("thenError") is None, f"{act}: its `then` {job['then']}: {run['thenError']}"
    log = api(daemon, "GET", f"/v1/apps/{name}/log").json()["text"]
    called = [line for line in log.splitlines() if f"run {done['runId']}: then " in line]
    assert len(called) == 1, f"{act}: its `then` called {len(called)} times:\n{log}"


def next_minute() -> str:
    """The local time of the next minute at least 5 s away, as a `when`'s `at`."""
    at = (datetime.now() + timedelta(seconds=65)).replace(second=0, microsecond=0)
    return at.strftime("%H:%M")


def nudges_sent(daemon: Daemon, name: str, nudges: dict[str, Any], said: list[str]) -> None:
    """Each scheduled nudge's slot made due (its time yours: the next minute, counted from now),
    sent by the scheduler: its `prepare` answers one nudge, several, or none (204), never an
    error nor something that is no nudge."""
    scheduled = [n for n, d in nudges.items() if "when" in d]
    if not scheduled:
        return
    at = next_minute()
    for nudge in scheduled:
        r = api(daemon, "PUT", f"/v1/apps/{name}/nudges/{nudge}/when", {"when": {"at": at}})
        assert r.status_code == 200, f"{name}: nudge {nudge}: its time set: {r.text}"

    def lines() -> list[str] | None:
        log = api(daemon, "GET", f"/v1/apps/{name}/log").json()["text"]
        found = [ln for ln in log.splitlines() if any(f"nudge {n} at " in ln for n in scheduled)]
        return found if len(found) >= len(scheduled) else None

    for line in until(lines, f"{name}: nudges {scheduled} not sent at {at}"):
        assert ": not sent:" not in line, f"{name}: {line}"
        said.append(line.split("] ", 1)[-1].strip())


def uninstalled(daemon: Daemon, data_root: Path, name: str, folders: list[str]) -> None:
    """Nothing of it left: its record, its runs and their sessions, its automations, its
    nudges, its data; the folders it was given stay."""
    kept = [
        root / "apps" / name for root in (data_root / "handler", daemon.config_dir.parent / "state")
    ]
    assert all(p.is_dir() for p in kept), f"{name}: not where its data is looked for: {kept}"
    automations = [a["name"] for a in api(daemon, "GET", "/v1/automations").json()]
    mine = [a for a in automations if a.startswith(f"{name}-suggested-")]
    assert api(daemon, "DELETE", f"/v1/apps/{name}").status_code == 204, f"{name}: uninstall"
    assert api(daemon, "GET", f"/v1/apps/{name}").status_code == 404, f"{name}: still listed"
    assert api(daemon, "GET", f"/v1/apps/{name}/runs").status_code == 404, f"{name}: runs left"
    for auto in mine:
        assert api(daemon, "GET", f"/v1/automations/{auto}").status_code == 404, (
            f"{name}: automation {auto} left"
        )
    sessions = [s["id"] for s in api(daemon, "GET", "/v1/sessions").json() if s.get("app") == name]
    assert sessions == [], f"{name}: its jobs' sessions left: {sessions}"
    inbox = api(daemon, "GET", "/v1/inbox").json()
    nudges = [m["id"] for m in inbox if m.get("app") == name and m.get("kind") == "nudge"]
    assert nudges == [], f"{name}: its nudges left in the inbox: {nudges}"
    for path in kept:
        assert not path.exists(), f"{name}: {path} left"
    for path in folders:
        assert Path(path).is_dir(), f"{name}: your folder {path} removed with it"


@pytest.mark.timeout(dev_env.IMAGE_TIMEOUT)  # its deploy may pull the apps' runtime image
@pytest.mark.parametrize("folder", registry_apps())
def test_a_registry_app_gets_what_handler_promises_apps(
    daemon: Daemon, data_root: Path, folder: str
) -> None:
    """Installed from the registry, deployed, each action asked, each scheduled nudge sent,
    uninstalled: each step does what contract H says, for this app.

    If this fails: an app of Handler's registry does not install, deploy, answer, run its jobs,
    send its nudges or leave cleanly on a Handler of this version: either the app breaks a rule
    of contract H (fix the app), or Handler broke a promise apps rely on."""
    assert REGISTRY is not None
    manifest = tomllib.loads((REGISTRY / "apps" / folder / "app.toml").read_text())
    said: list[str] = []
    try:
        app = install(daemon, folder, manifest, said)
        name = app["name"]
        jobs = manifest.get("jobs", {})
        for action in app["actions"]:
            declared = manifest["actions"][action["name"]]
            try:
                fields = filled(action.get("fields"), f"action {action['name']}'s form")
                if action["by"] == "code":
                    by_code(daemon, name, action | {"route": declared["route"]}, fields)
                else:
                    job = declared["job"]
                    by_job(daemon, name, action | {"job": job}, fields, jobs[job])
                said.append(f"action {action['name']} (by its {action['by']}): {fields} answered")
            except NotTriedError as e:
                said.append(f"action {action['name']}: skipped, {e}")
        nudges_sent(daemon, name, manifest.get("nudges", {}), said)
        given = [f["path"] for f in api(daemon, "GET", f"/v1/apps/{name}").json()["files"]]
        uninstalled(daemon, data_root, name, given)
    finally:
        print(f"\n{folder}:\n" + "\n".join(f"  {line}" for line in said))
