"""Unit tests: apps (contract H) — manifest, sandbox spec, snapshot, app files (H.15),
links and cookies. The daemon running real apps is tests/apps."""

import asyncio
import dataclasses
import io
import json
import re
import time
import tomllib
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError
from source_repo import TEST_SOURCE

from handler_contracts import (
    APP_CODE_DIR,
    APP_SOCKET,
    RUNTIME_IMAGE,
    RUNTIME_VERSION,
    AppManifest,
    FilteredNetwork,
    NoNetwork,
    Pin,
    SandboxSpec,
)
from handler_control import apps, compose, pins
from handler_control.agents import AgentRegistry
from handler_control.app_runs import AppRunError, AppRuns
from handler_control.apps import (
    AppError,
    AppStore,
    DeployError,
    Deployment,
    read_manifest,
    snapshot,
)
from handler_control.inbox import Inbox
from handler_control.sessions import SessionStore
from handler_control.settings import Settings
from handler_harness import addons

BUILDER = addons.BUILTIN_DIR / "app-builder"
TEMPLATE = BUILDER / "skills" / "app-builder" / "template"


def manifest(**overrides: Any) -> AppManifest:
    data = {"apiVersion": "handler.app/v1", "name": "notes", "version": "0.1.0"} | overrides
    return AppManifest.model_validate(data)


RESULT = {
    "type": "object",
    "required": ["status", "summary"],
    "properties": {
        "status": {"enum": ["ok", "attention", "failed"]},
        "summary": {"type": "string"},
    },
}
# a CV app's folders (`cv` read-only, `drafts` read-write) and its job `write`, reading `cv`
CV_NEEDS = {"files": {"cv": {}, "drafts": {"mode": "rw"}}}
WRITE_JOB = {"description": "Write a CV", "files": {"cv": "read"}, "result": RESULT}


def with_job(job: dict[str, Any] | None = None, **overrides: Any) -> AppManifest:
    """An app with the job `write` (WRITE_JOB, changed by `job`)."""
    data = {"needs": CV_NEEDS, "jobs": {"write": WRITE_JOB | (job or {})}} | overrides
    return manifest(**data)


# ── manifest ────────────────────────────────────────────────────────────


def test_defaults() -> None:
    m = manifest()
    assert (m.server.entry, m.server.dir, m.ui.dir) == ("server/main.ts", "server", "ui/dist")
    assert m.needs.egress == []


@pytest.mark.rule(
    "app.its-manifest-is-strict", "app.one-name-one-app", "action.done-by-its-code-or-its-job"
)
@pytest.mark.parametrize(
    "overrides",
    [
        {"name": "Notes"},  # not a DNS label
        {"name": "a" * 31},
        {"version": "1.0"},
        {"server": {"entry": "main.ts"}},  # the whole folder would be installed
        {"server": {"entry": "../main.ts"}},
        {"ui": {"dir": "/srv/ui"}},
        {"ui": {"dir": "server/public"}},  # overlaps the backend's directory
        {"needs": {"egress": ["example.com"]}},  # no port
        {"needs": {"secrets": ["api_key"]}},  # env var names in capitals
        {"needs": {"secrets": ["HANDLER_APP_DATA"]}},  # set by handler
        {"needs": {"secrets": ["BUN_RUNTIME_TRANSPILER_CACHE_PATH"]}},
        {"needs": {"secrets": ["HTTPS_PROXY"]}},
        {"needs": {"unknown": ["x"]}},  # unknown keys are errors: nothing asked is ignored
        {"typo": 1},
        {"actions": {"add": {"description": "Add"}}},  # done by nothing
        {"actions": {"add": {"description": "Add", "route": "POST /api/a", "job": "x"}}},  # both
        {"actions": {"add": {"description": "Add", "route": "GET /api/a"}}},  # a POST
        {"actions": {"plan": {"description": "Plan", "agent": "planner"}}},  # apps have no agents
        {"needs": {"agents": {"planner": {"from": "agent"}}}},  # an app brings jobs, no agents
        {"actions": {"add": {"description": "", "route": "POST /api/a"}}},
        {"schemas": ["cv@1", "cv@1"]},  # a schema named twice
        {"schemas": ["cv"]},  # not a `$id`
    ],
)
def test_invalid(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        manifest(**overrides)


@pytest.mark.rule("app.its-manifest-is-strict", "action.done-by-its-code-or-its-job")
@pytest.mark.parametrize(
    ("job", "overrides", "said"),
    [
        ({"files": {"photos": "read"}}, {}, "jobs.write.files: no files need photos"),
        ({"files": {"cv": "write"}}, {}, "jobs.write.files.cv: write, but the need is ro"),
        ({"files": {"cv": "edit"}}, {}, "files.cv"),  # read or write
        ({"worksIn": ["drafts"]}, {}, "worksIn: drafts is not one of its files"),
        ({"schemas": ["cv@1"]}, {}, "cv@1 is not in the app's schemas"),
        ({"egress": ["example.com"]}, {}, "egress"),  # no port
        ({"timeout": "2d"}, {}, "timeout: at most 1d"),
        ({"then": "GET /api/cvs"}, {}, "then"),  # a POST of its own
        ({"then": "POST https://example.com/api"}, {}, "then"),
        ({"result": None}, {}, "result"),  # a job gives a result
        ({"description": ""}, {}, "description"),
        ({}, {"actions": {"go": {"description": "Go", "job": "nope"}}}, "no job nope"),
        (
            {},
            {"actions": {"go": {"description": "Go", "job": "write", "route": "POST /api/go"}}},
            "an action is done by its code (route) or a job (job): one",
        ),
        (
            {},
            {"actions": {"go": {"description": "Go", "job": "write", "fields": {}}}},
            "a job's action takes the form of its job",
        ),
        (
            {},
            {"automations": [{"description": "D", "when": {"every": "1d"}, "run": {"job": "x"}}]},
            "run.job: no job x",
        ),
        (
            {},
            {
                "automations": [
                    {
                        "description": "D",
                        "when": {"every": "1d"},
                        "run": {"job": "write", "agent": "a"},
                    }
                ]
            },
            "run.agent",  # a suggested automation runs a job, never an agent
        ),
        (
            {},
            {
                "automations": [
                    {
                        "description": "D",
                        "when": {"every": "1d"},
                        "run": {"job": "write", "call": "POST /api/x"},
                    }
                ]
            },
            "runs one of its jobs (job) or calls a route (call): one",
        ),
        (
            {},
            {
                "automations": [
                    {"description": "D", "when": {"every": "1d"}, "run": {"call": "GET /x"}}
                ]
            },
            "run.call",  # one of its POST /api/… routes
        ),
        ({}, {"jobs": {f"j{i}": WRITE_JOB for i in range(11)}}, "jobs"),  # at most 10
        ({}, {"jobs": {"Write": WRITE_JOB}}, "jobs.Write"),  # a need's name
    ],
)
def test_a_job_reaches_only_what_its_app_declares(
    job: dict[str, Any], overrides: dict[str, Any], said: str
) -> None:
    """A job names only files needs and schemas of its app's, writes only a folder given `rw`;
    an action or a suggested automation names a job it has, and is done by one thing.

    If this fails: a job is declared to reach a folder you were never asked for, or to write
    one you gave read-only."""
    with pytest.raises(ValidationError, match=re.escape(said)):
        with_job(job, **overrides)


@pytest.mark.rule("app.its-manifest-is-strict")
def test_a_job_s_declaration() -> None:
    m = with_job(
        {"files": {"cv": "read", "drafts": "write"}, "worksIn": ["drafts"], "schemas": ["cv@1"]}
        | {"egress": ["example.com:443"], "fields": {"type": "object"}, "timeout": "30m"}
        | {"then": "POST /api/cvs"},
        schemas=["cv@1"],
        actions={"write": {"description": "Write my CV", "job": "write"}},
        automations=[
            {"description": "Weekly", "when": {"every": "7d"}, "run": {"job": "write"}},
            {"description": "Nightly", "when": {"at": "03:00"}, "run": {"call": "POST /api/tidy"}},
        ],
    )
    assert m.automations[1].run.call == "POST /api/tidy"
    job = m.jobs["write"]
    assert (job.files, job.works_in, job.timeout_sec) == (
        {"cv": "read", "drafts": "write"}, ["drafts"], 1800,
    )  # fmt: skip
    assert (m.actions["write"].job, m.automations[0].run.job) == ("write", "write")


@pytest.mark.rule("deploy.what-it-adds-is-said-first")
def test_added_needs() -> None:
    m = manifest(needs={"egress": ["a.example.com:443", "b.example.com:443"], "secrets": ["K"]})
    before = manifest(needs={"egress": ["a.example.com:443"]})
    assert m.added_needs(before) == ["egress b.example.com:443", "secret K"]
    assert m.added_needs(m) == []
    assert m.added_needs(None) == [
        "egress a.example.com:443", "egress b.example.com:443", "secret K",
    ]  # fmt: skip


@pytest.mark.rule("deploy.what-it-adds-is-said-first")
def test_what_a_job_reaches_is_said_before_deploy() -> None:
    """A new job is said, and so is what each job reaches beyond the installed version: a folder
    and its access, a schema, a host.

    If this fails: an update makes a job write a folder of yours, or reach a host, that you
    never agreed to."""
    v1 = with_job()
    assert v1.added_needs(None) == [
        "file cv (ro)", "file drafts (rw)", "job write", "job write: file cv (read)",
    ]  # fmt: skip
    assert v1.added_needs(v1) == []
    v2 = with_job(
        {"files": {"cv": "read", "drafts": "write"}, "egress": ["example.com:443"]}
        | {"schemas": ["cv@1"]},
        schemas=["cv@1"],
    )
    assert v2.added_needs(v1) == [
        "job write: egress example.com:443", "job write: file drafts (write)",
        "job write: schema cv@1",
    ]  # fmt: skip
    assert v1.added_needs(v2) == []  # reaching less adds nothing


def test_template_manifest_is_valid() -> None:
    m = AppManifest.from_toml((TEMPLATE / "app.toml").read_text())
    assert (TEMPLATE / m.server.entry).is_file()


@pytest.mark.rule("app-backend.in-a-strict-sandbox")
def test_app_builder_has_the_runtime_bun_version() -> None:
    """The agents that write apps test them with the Bun apps run on (H.3)."""
    containerfile = (BUILDER / "Containerfile").read_text()
    m = re.search(r"ARG BUN_VERSION=bun-v([0-9.]+)", containerfile)
    assert m and m[1] == RUNTIME_VERSION


# ── sandbox spec (H.3) ──────────────────────────────────────────────────


def spec(m: AppManifest, test: bool = False) -> SandboxSpec:
    return compose.app_sandbox_spec(
        name="handler-app-notes-1", manifest=m, code="/c", data="/d/data", run="/r", test=test
    )


@pytest.mark.rule("app-backend.in-a-strict-sandbox")
def test_spec_is_offline_and_read_only() -> None:
    s = spec(manifest())
    assert s.image == RUNTIME_IMAGE
    assert s.isolation == "strict"
    assert isinstance(s.network, NoNetwork)
    assert s.work_folder.path == "/d/data"
    folders = {f.target: (f.source, f.writable) for f in s.folders}
    assert folders == {APP_CODE_DIR: ("/c", False)}
    # its socket, served to handlerd; nothing of handlerd's to reach without a need (A.10)
    [run] = s.socket_folders
    assert (run.source, run.target, run.serves, run.reaches) == (
        "/r",
        "/run/handler-app",
        ["app.sock"],
        [],
    )
    assert s.workdir == "/d/data"
    assert s.argv == ["run", "--no-install", "--no-env-file", f"{APP_CODE_DIR}/server/main.ts"]
    assert s.env["HANDLER_APP_SOCKET"] == APP_SOCKET and s.env["HANDLER_APP_DATA"] == "/d/data"
    assert s.resources and s.resources.memory == "512m"


@pytest.mark.rule("sandbox.its-sockets-cross-as-declared")
def test_an_app_that_notifies_reaches_handler_s_socket_its_tests_do_not() -> None:
    """With `needs.notify`, the backend reaches handlerd's socket (H.9); its tests never.
    If this fails: an app's tests send notifications, or a backend cannot."""
    m = manifest(needs={"notify": True})
    [run] = spec(m).socket_folders
    assert (run.serves, run.reaches) == (["app.sock"], ["handler.sock"])
    assert spec(m).env["HANDLER_APP_API"] == "/run/handler-app/handler.sock"
    [tested] = spec(m, test=True).socket_folders
    assert tested.reaches == []


@pytest.mark.rule("app-need.a-folder-in-your-home-never-handler-s")
def test_spec_with_folders_names_them_by_need() -> None:
    m = manifest(needs={"files": {"tasks": {"mode": "rw"}, "notes": {}}})
    files = [("tasks", "/h/planner", True), ("notes", "/h/notes.md", False)]
    s = compose.app_sandbox_spec(
        name="handler-app-notes-1", manifest=m, code="/c", data="/d/data", run="/r", files=files
    )
    assert json.loads(s.env["HANDLER_APP_FILES"]) == {"tasks": "/h/planner", "notes": "/h/notes.md"}
    folders = {f.target: f.writable for f in s.folders}
    assert (folders["/h/planner"], folders["/h/notes.md"]) == (True, False)


@pytest.mark.rule("notes.agents-never-reach-the-history")
def test_a_read_write_folder_s_own_git_is_read_only_to_the_backend(tmp_path: Path) -> None:
    """A folder given rw keeps its `.git` (your history) read-only over it; one given read-only
    is read-only whole.

    If this fails: an app rewrites your folder's git history, or plants a hook your next `git`
    command runs."""
    rw, ro = tmp_path / "rw", tmp_path / "ro"
    for folder in (rw, ro):
        (folder / ".git").mkdir(parents=True)
    files = [("cv", str(rw), True), ("old", str(ro), False)]
    s = compose.app_sandbox_spec(
        name="n", manifest=manifest(), code="/c", data="/d", run="/r", files=files
    )
    folders = {f.target: (f.source, f.writable) for f in s.folders}
    assert folders[str(rw)] == (str(rw), True)
    assert folders[f"{rw}/.git"] == (f"{rw}/.git", False)
    assert f"{ro}/.git" not in folders and folders[str(ro)] == (str(ro), False)


@pytest.mark.rule("notes.agents-never-reach-the-history")
def test_a_folder_whose_git_is_a_link_is_not_given_read_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `.git` that is a link (or a worktree's file) cannot be kept read-only: the app does not
    start with that folder read-write.

    If this fails: an app writes through the link into a git history it was never given."""
    monkeypatch.setenv("HOME", str(tmp_path))
    s = store(tmp_path)
    cv = tmp_path / "cv"
    cv.mkdir()
    (tmp_path / "elsewhere").mkdir()
    (cv / ".git").symlink_to(tmp_path / "elsewhere")
    s.records["notes"] = apps.AppRecord(name="notes", files={"cv": str(cv)})
    with pytest.raises(DeployError, match=r"its \.git is not a folder"):
        s.check_files("notes", manifest(needs={"files": {"cv": {"mode": "rw"}}}))
    assert s.check_files("notes", manifest(needs={"files": {"cv": {}}})) == [("cv", str(cv), False)]


@pytest.mark.rule("notes.writable-has-a-history")
def test_the_folders_an_app_writes(tmp_path: Path) -> None:
    """Each folder given to a files need in rw of the installed version; not a read-only one, a
    file, nor an app not installed.

    If this fails: what an app writes in your files has no history to undo it."""
    s = store(tmp_path)
    cv, old, note = tmp_path / "cv", tmp_path / "old", tmp_path / "note.md"
    cv.mkdir()
    old.mkdir()
    note.write_text("x")
    version = s.version_dir("notes", 1)
    version.mkdir(parents=True)
    (version / "app.toml").write_text("""
        apiVersion = "handler.app/v1"
        name = "notes"
        version = "0.1.0"
        title = "Notes"
        [needs.files]
        cv = { mode = "rw" }
        old = {}
        note = { mode = "rw" }
    """)
    files = {"cv": str(cv), "old": str(old), "note": str(note)}
    s.records["notes"] = apps.AppRecord(name="notes", files=files)
    s.records["draft"] = apps.AppRecord(name="draft", files={"cv": str(cv)})
    assert s.written_folders() == []
    s.records["notes"].deployments.append(Deployment(1, "0.1.0", datetime.now(UTC)))
    [written] = s.written_folders()
    assert (written.app, written.title, written.path) == ("notes", "Notes", str(cv))
    assert not written.running


@pytest.mark.rule("app-backend.in-a-strict-sandbox")
def test_spec_with_egress() -> None:
    s = spec(manifest(needs={"egress": ["api.example.com:443"]}))
    assert isinstance(s.network, FilteredNetwork)
    assert s.network.allow == ["api.example.com:443"] and s.network.enforcement == "enforce"


@pytest.mark.rule("app-backend.in-a-strict-sandbox")
def test_test_spec() -> None:
    s = spec(manifest(), test=True)
    assert s.argv[0] == "test" and s.argv[-1] == f"{APP_CODE_DIR}/server"
    assert "--no-install" in s.argv and "--pass-with-no-tests" in s.argv


@pytest.mark.rule("app-backend.its-secrets-reach-it-alone")
def test_secrets_go_to_the_backend_not_to_tests() -> None:
    m = manifest(needs={"secrets": ["API_KEY"]})

    def build(test: bool) -> SandboxSpec:
        return compose.app_sandbox_spec(
            name="n",
            manifest=m,
            code="/c",
            data="/d",
            run="/r",
            secrets={"API_KEY": "v"},
            test=test,
        )

    assert build(test=False).env["API_KEY"] == "v"
    tested = build(test=True)
    assert "API_KEY" not in tested.env
    assert all(a != "v" for a in tested.argv)


# ── snapshot (H.6) ──────────────────────────────────────────────────────


def app_folder(root: Path) -> Path:
    src = root / "src"
    (src / "server").mkdir(parents=True)
    (src / "server" / "main.ts").write_text("// main\n")
    (src / "ui" / "dist").mkdir(parents=True)
    (src / "ui" / "dist" / "index.html").write_text("<!doctype html>")
    (src / "ui" / "src").mkdir()
    (src / "ui" / "src" / "App.svelte").write_text("<p>source</p>")
    (src / "app.toml").write_text(
        'apiVersion = "handler.app/v1"\nname = "notes"\nversion = "0.1.0"\n'
    )
    return src


def zipped(folder: Path, top: str = "") -> bytes:
    """The app file of a folder (H.15), its files at the root or in one folder `top`."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                zf.write(path, top + path.relative_to(folder).as_posix())
    return buffer.getvalue()


@pytest.mark.rule("deploy.a-failure-changes-nothing", "app.nothing-is-read-through-a-link-out")
def test_snapshot_copies_only_what_is_installed(tmp_path: Path) -> None:
    src = app_folder(tmp_path)
    (src / "server" / "link.ts").symlink_to("main.ts")  # inside: kept as a link
    snapshot(src, tmp_path / "v1", AppManifest.from_toml((src / "app.toml").read_text()))
    copied = sorted(str(p.relative_to(tmp_path / "v1")) for p in (tmp_path / "v1").rglob("*"))
    assert copied == [
        "app.toml", "server", "server/link.ts", "server/main.ts",
        "ui", "ui/dist", "ui/dist/index.html",
    ]  # fmt: skip
    assert (tmp_path / "v1" / "server" / "link.ts").is_symlink()


@pytest.mark.rule("app.nothing-is-read-through-a-link-out")
@pytest.mark.parametrize("where", ["ui/dist/leak.txt", "server/leak.ts"])
def test_snapshot_refuses_links_outside(tmp_path: Path, where: str) -> None:
    src = app_folder(tmp_path)
    (tmp_path / "secret").write_text("key")
    (src / where).symlink_to(tmp_path / "secret")
    m = AppManifest.from_toml((src / "app.toml").read_text())
    with pytest.raises(DeployError, match="link to outside"):
        snapshot(src, tmp_path / "v1", m)


@pytest.mark.rule("deploy.a-failure-changes-nothing")
def test_snapshot_needs_a_built_ui(tmp_path: Path) -> None:
    src = app_folder(tmp_path)
    (src / "ui" / "dist" / "index.html").unlink()
    with pytest.raises(DeployError, match="build the UI"):
        snapshot(src, tmp_path / "v1", AppManifest.from_toml((src / "app.toml").read_text()))


RESULT_TOML = """
[jobs.write.result]
type = "object"
required = ["status", "summary"]
[jobs.write.result.properties.status]
enum = ["ok", "attention", "failed"]
[jobs.write.result.properties.summary]
type = "string"
"""


def app_with_a_job(root: Path, job: str = "", instructions: str = "Write a CV.\n") -> Path:
    src = app_folder(root)
    (src / "cv").mkdir()
    (src / "app.toml").write_text(
        (src / "app.toml").read_text()
        + '[needs.files.cv]\n[jobs.write]\ndescription = "Write a CV"\nfiles = { cv = "read" }\n'
        + job
        + RESULT_TOML
    )
    (src / "jobs").mkdir()
    (src / "jobs" / "write.md").write_text(instructions)
    return src


def snapshot_of(src: Path, target: Path) -> None:
    snapshot(src, target, AppManifest.from_toml((src / "app.toml").read_text()))


@pytest.mark.rule("app.its-manifest-is-strict", "deploy.a-failure-changes-nothing")
def test_a_job_s_instructions_are_installed_with_it(tmp_path: Path) -> None:
    snapshot_of(app_with_a_job(tmp_path), tmp_path / "v1")
    assert (tmp_path / "v1" / "jobs" / "write.md").read_text() == "Write a CV.\n"


@pytest.mark.rule("app.its-manifest-is-strict")
@pytest.mark.parametrize(
    ("change", "said"),
    [
        (lambda src: (src / "jobs" / "write.md").unlink(), "jobs.write: its instructions"),
        (lambda src: (src / "jobs" / "notes.txt").write_text("x"), "jobs/notes.txt is no job's"),
        (lambda src: (src / "jobs" / "old.md").write_text("x"), "jobs/old.md is no job's"),
        (
            lambda src: (src / "jobs" / "write.md").write_text("For {{ad}}."),
            r"jobs.write.instructions: \{\{ad\}\} is not a field of its form",
        ),
    ],
)
def test_a_deploy_fails_on_a_job_s_instructions(tmp_path: Path, change: Any, said: str) -> None:
    """A job's instructions are `jobs/<name>.md`, and `jobs/` holds nothing else; they name only
    fields of its form: else the deploy (or a draft opened) fails, naming what.

    If this fails: a job is installed with no instructions, or with ones the app does not run."""
    src = app_with_a_job(tmp_path)
    change(src)
    with pytest.raises(DeployError, match=said):
        snapshot_of(src, tmp_path / "v1")


@pytest.mark.rule("app.its-manifest-is-strict", "action.done-by-its-code-or-its-job")
@pytest.mark.parametrize(
    ("job", "said"),
    [
        ('fields = { type = "string" }\n', "jobs.write.fields"),
        (
            'timeout = "30m"\n[jobs.write.fields]\ntype = "object"\nminProperties = -1\n',
            "jobs.write.fields: not a JSON Schema",
        ),
        ("", None),
    ],
)
def test_a_job_s_form_and_result_are_checked_at_deploy(
    tmp_path: Path, job: str, said: str | None
) -> None:
    """A job's form is the JSON Schema of an object and its result says how it went (`status`,
    `summary`), as an agent's job's (D.18, I.3's rule).

    If this fails: a job is installed whose form cannot be filled, or whose end the inbox and
    Ask cannot tell."""
    src = app_with_a_job(tmp_path, job)
    if said is None:
        snapshot_of(src, tmp_path / "v1")
        return
    with pytest.raises(DeployError, match=said):
        snapshot_of(src, tmp_path / "v1")


@pytest.mark.rule("action.done-by-its-code-or-its-job")
def test_a_job_s_result_says_how_it_went(tmp_path: Path) -> None:
    src = app_with_a_job(tmp_path)
    toml = (src / "app.toml").read_text()
    toml = toml.replace('required = ["status", "summary"]', 'required = ["summary"]')
    (src / "app.toml").write_text(toml)
    with pytest.raises(DeployError, match=r"jobs\.write: its result has no required 'status'"):
        snapshot_of(src, tmp_path / "v1")


@pytest.mark.rule("action.done-by-its-code-or-its-job")
def test_an_app_s_action_and_automation_may_run_a_job(tmp_path: Path) -> None:
    """An action done by a job, a suggested automation running one: read as declared."""
    src = app_with_a_job(tmp_path)
    extra = '[actions.write]\ndescription = "Write my CV"\njob = "write"\n'
    extra += '[[automations]]\ndescription = "Weekly"\nwhen = { every = "7d" }\n'
    extra += 'run = { job = "write" }\n'
    (src / "app.toml").write_text((src / "app.toml").read_text() + extra)
    manifest = read_manifest(src)
    assert (manifest.actions["write"].job, manifest.automations[0].run.job) == ("write", "write")


# ── links and cookies (H.4) ─────────────────────────────────────────────


def store(tmp_path: Path) -> AppStore:
    settings = Settings(
        port=7430,
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
        bindings_dir=tmp_path / "bindings",
        allowed_origins=frozenset(),
        web_ui_dir=tmp_path / "ui",
        data_dir=tmp_path / "data",
        schemas_dir=tmp_path / "schemas",  # the Library's: never the home's
    )
    inbox, registry = Inbox(settings), AgentRegistry(settings.state_dir)
    sessions = SessionStore(settings, registry)
    runs = AppRuns(settings, sessions, inbox)
    return AppStore(settings, token="t0ken", inbox=inbox, runs=runs)


@pytest.mark.rule("app-origin.opened-by-a-one-time-link")
def test_link_is_one_time_and_per_app(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.add_file(zipped(app_folder(tmp_path)))
    s.records["notes"].deployments.append(Deployment(1, "0.1.0", datetime.now(UTC)))
    url = s.open_link("notes")
    assert url.startswith("http://notes.localhost:7430/_handler/login?code=")
    code = url.split("code=")[1]
    assert not s.redeem("other", code)  # a code opens its own app only, and is spent
    url = s.open_link("notes")
    code = url.split("code=")[1]
    assert s.redeem("notes", code)
    assert not s.redeem("notes", code)


@pytest.mark.rule("app-origin.opened-by-a-one-time-link")
def test_cookie_is_per_app_and_per_token(tmp_path: Path) -> None:
    s = store(tmp_path)
    assert s.cookie_matches("notes", s.cookie("notes"))
    assert not s.cookie_matches("notes", s.cookie("other"))
    assert not s.cookie_matches("notes", None)
    other = AppStore(s.settings, token="another", inbox=s.inbox, runs=s.runs)
    assert not other.cookie_matches("notes", s.cookie("notes"))


@pytest.mark.rule("app.uninstalled-leaves-nothing-of-it", "pin.gone-with-what-it-pins")
def test_uninstalled_its_pin_goes(tmp_path: Path) -> None:
    """An app installed later under its name does not find itself pinned."""
    s = store(tmp_path)
    s.add_file(zipped(app_folder(tmp_path)))
    project = Pin(kind="project", id="p_0123456789")
    pins.save(s.settings.state_dir, [Pin(kind="app", id="notes"), project])
    asyncio.run(s.remove("notes"))
    assert pins.load(s.settings.state_dir) == [project]


@pytest.mark.rule("app.its-code-is-kept-by-handler")
def test_registry_survives_a_restart(tmp_path: Path) -> None:
    s = store(tmp_path)
    record, new = s.add_file(zipped(app_folder(tmp_path)))
    assert new and record.name == "notes"
    assert (tmp_path / "data" / "apps" / "notes" / "data").is_dir()
    again = AppStore(s.settings, token="t0ken", inbox=s.inbox, runs=s.runs)
    assert "notes" in again.records and again.records["notes"].from_source is None
    source = tmp_path / "data" / "apps" / "notes" / "source"
    assert tomllib.loads((source / "app.toml").read_text())["name"] == "notes"


@pytest.mark.rule("app.its-code-is-kept-by-handler")
def test_an_app_file_is_its_code_kept_by_handler(tmp_path: Path) -> None:
    """Its code is Handler's copy: the folder it came from can go; the file of an app you have
    is its next version; one folder at the zip's root is the app's; its export is the code."""
    s = store(tmp_path)
    folder = app_folder(tmp_path)
    s.add_file(zipped(folder, top="notes-0.1.0/"))
    source = tmp_path / "data" / "apps" / "notes" / "source"
    assert (source / "ui" / "src" / "App.svelte").read_text() == "<p>source</p>"
    (folder / "app.toml").write_text((folder / "app.toml").read_text().replace("0.1.0", "0.2.0"))
    _, new = s.add_file(zipped(folder))
    assert not new and s.view("notes").source.version == "0.2.0"
    name, data = s.export("notes")
    assert name == "notes-0.2.0.zip"
    assert "ui/src/App.svelte" in zipfile.ZipFile(io.BytesIO(data)).namelist()
    for bad, why in [(b"nope", "not an app file"), (zipped(folder / "ui"), "no app.toml")]:
        with pytest.raises(AppError, match=why):
            s.add_file(bad)


@pytest.mark.rule("source.never-over-an-app-from-elsewhere")
def test_an_app_file_over_one_from_a_source_makes_it_yours(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.add_from_source("official", TEST_SOURCE / "apps" / "journal")
    _, data = s.export("journal")
    s.add_file(data)
    assert s.view("journal").from_source is None


# ── from a source (D.26) ────────────────────────────────────────────────


@pytest.mark.rule("source.never-over-an-app-from-elsewhere")
def test_an_app_from_a_source_is_a_copy_that_keeps_its_source(tmp_path: Path) -> None:
    s = store(tmp_path)
    record, new = s.add_from_source("official", TEST_SOURCE / "apps" / "journal")
    copy = tmp_path / "data" / "apps" / "journal" / "source"
    assert new and record.from_source == "official" and (copy / "app.toml").is_file()
    assert s.view("journal").from_source == "official"
    assert s.view("journal").source.version == manifest_version(TEST_SOURCE / "apps" / "journal")
    _, new = s.add_from_source("official", TEST_SOURCE / "apps" / "journal")
    assert not new  # its next version
    again = AppStore(s.settings, token="t0ken", inbox=s.inbox, runs=s.runs)
    assert again.records["journal"].from_source == "official"


@pytest.mark.rule("source.never-over-an-app-from-elsewhere")
def test_a_source_never_replaces_an_app_from_elsewhere(tmp_path: Path) -> None:
    """Only the source an app came from gives it a next version: another source offering an app
    of that name, or any source once the app is yours, would replace its code with a stranger's."""
    s = store(tmp_path)
    s.add_from_source("official", TEST_SOURCE / "apps" / "journal")
    with pytest.raises(AppError, match="from the source official: remove it first"):
        s.add_from_source("acme", TEST_SOURCE / "apps" / "journal")
    _, data = s.export("journal")
    s.add_file(data)  # yours from now on
    with pytest.raises(AppError, match="journal, yours: remove it first"):
        s.add_from_source("official", TEST_SOURCE / "apps" / "journal")
    assert s.view("journal").from_source is None


@pytest.mark.rule("app.one-name-one-app")
def test_an_app_named_other_than_its_folder_is_refused(tmp_path: Path) -> None:
    s = store(tmp_path)
    folder = app_folder(tmp_path)
    renamed = folder.rename(folder.parent / "other")
    with pytest.raises(AppError, match="names another app, notes"):
        s.add_from_source("acme", renamed)


@pytest.mark.rule("app.one-name-one-app", "chat.is-no-app")
@pytest.mark.parametrize(
    ("name", "why"),
    [
        pytest.param("chat", "the name of Chat", id="chat-s-name"),
        pytest.param("notes--draft", "an opened draft's", id="an-opened-draft-s-name"),
    ],
)
def test_an_app_taking_chat_s_or_a_draft_s_name_is_refused(
    tmp_path: Path, name: str, why: str
) -> None:
    """An app file whose manifest names Chat, or ends in `--draft` (an opened draft's origin and
    folder): refused, and nothing of it kept. Names close to them are apps like any.

    If this fails: an app takes the address of Chat or of another app's draft."""
    s = store(tmp_path)
    folder = app_folder(tmp_path)
    toml = (folder / "app.toml").read_text()
    (folder / "app.toml").write_text(toml.replace('name = "notes"', f'name = "{name}"'))
    with pytest.raises(AppError, match=why):
        s.add_file(zipped(folder))
    assert s.records == {} and not (tmp_path / "data" / "apps" / name).exists()
    for near in ("chats", "draft", "notes-draft"):
        (folder / "app.toml").write_text(toml.replace('name = "notes"', f'name = "{near}"'))
        assert s.add_file(zipped(folder))[0].name == near


@pytest.mark.rule("source.never-over-an-app-from-elsewhere")
def test_an_app_of_yours_comes_from_no_source(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.add_file(zipped(app_folder(tmp_path)))
    assert s.view("notes").from_source is None


def manifest_version(folder: Path) -> str:
    return AppManifest.from_toml((folder / "app.toml").read_text()).version


@pytest.mark.rule("app-notify.only-to-whom-it-is-shared-with")
def test_an_app_sends_at_most_30_notifications_an_hour(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """30 notifications of an app within an hour go; the 31st is refused (429) and reaches no
    inbox; another app is not held back; an hour after the first, it may send again.

    If this fails: an app floods your desktop and your inbox."""
    now = [1000.0]
    monkeypatch.setattr(apps.time, "monotonic", lambda: now[0])
    s = store(tmp_path)
    folder = app_folder(tmp_path)
    s.add_file(zipped(folder))
    (folder / "app.toml").write_text((folder / "app.toml").read_text().replace("notes", "other"))
    s.add_file(zipped(folder))

    def send(name: str) -> int:
        return asyncio.run(s.notification(name, {"title": "Hello"}))[0]

    assert [send("notes") for _ in range(30)] == [200] * 30
    assert send("notes") == 429
    assert len([m for m in s.inbox.list() if m.name == "notes"]) == 30
    assert send("other") == 200
    now[0] += 3600
    assert send("notes") == 200


FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures"


@pytest.mark.rule("app-job.its-code-starts-one-only-while-answering-the-owner")
def test_a_trial_or_a_request_without_the_owner_s_start_token_starts_no_run(
    tmp_path: Path,
) -> None:
    """Asked straight at handlerd's socket (an app may skip its helper): a deploy's trial or an
    opened draft (both served by `trial`) gets 403 for a run, and so does a run whose start
    token is not one handlerd gave for a request of the owner's, to this app.

    If this fails: an app runs its jobs on your account when nobody asked, from a trial, a draft,
    or another app's request."""
    s = store(tmp_path)
    s.add_file(zipped(app_folder(tmp_path)))
    body = {"job": "coach", "start": "made-up", "fields": {}}
    assert asyncio.run(s.trial("notes", "POST", "/runs", body))[0] == 403
    assert s.issue_start("notes", "alice") is None  # a person's request gets no token
    for start in ("made-up", s.issue_start("other", "owner")):
        with pytest.raises(AppRunError) as refused:
            asyncio.run(s.run_call("notes", "POST", "/runs", body | {"start": start}))
        assert refused.value.status == 403
    assert s.runs.sessions.records == {}


@pytest.mark.rule("app-backend.runs-only-while-used")
def test_a_first_request_during_a_deploy_waits_and_starts_the_new_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A first `/api` request while a deploy is under way: no backend starts until the deploy
    ends, then the one started is the new version's. (The runtime is stubbed: what starts is
    recorded, and the deploy is held at its runtime pull.)

    If this fails: a request starts the old version mid-deploy, which then runs on, or two
    backends of one app run at once on its data."""
    s = store(tmp_path)
    started: list[tuple[int, bool]] = []
    pulling, pulled = asyncio.Event(), asyncio.Event()

    async def start(name: str, seq: int, *args: Any, check: bool = False, **kw: Any) -> Any:
        started.append((seq, check))
        return SimpleNamespace(last_used=0.0)

    async def pull(name: str) -> None:
        pulling.set()
        await pulled.wait()

    async def nothing(*args: Any, **kwargs: Any) -> None:
        return None

    for name, value in [
        ("_start", start), ("_run_tests", nothing), ("_stop", nothing),
        ("_stop_backend", nothing), ("_watch", nothing),
    ]:  # fmt: skip
        monkeypatch.setattr(s, name, value)
    folder = app_folder(tmp_path)
    s.add_file(zipped(folder))

    async def scenario() -> None:
        pulled.set()
        await s.deploy("notes")  # #1
        (folder / "app.toml").write_text(
            (folder / "app.toml").read_text().replace("0.1.0", "0.2.0")
        )
        s.add_file(zipped(folder))
        pulled.clear()
        pulling.clear()
        monkeypatch.setattr(s, "_pull_runtime", pull)
        deploy = asyncio.create_task(s.deploy("notes"))  # #2, held at its pull
        await pulling.wait()
        first_request = asyncio.create_task(s.ensure_running("notes"))
        for _ in range(20):
            await asyncio.sleep(0)
        assert not first_request.done() and (1, False) not in started
        pulled.set()
        await deploy
        await first_request  # the one started: version 2's (below)

    monkeypatch.setattr(s, "_pull_runtime", nothing)
    asyncio.run(scenario())
    assert [seq for seq, check in started if not check] == [2]


def test_a_deploy_replaces_a_version_folder_no_deployment_owns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The app's folder already holds `versions/1` (a state lost while the data folder was
    kept: the new one numbers from 1 again): the deploy installs its own version there. (The
    runtime is stubbed.)

    If this fails: deploying the app answers 500 "Directory not empty" until its old version
    folder is deleted by hand."""
    s = store(tmp_path)

    async def nothing(*args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(last_used=0.0)

    for name in ("_pull_runtime", "_run_tests", "_start", "_stop", "_stop_backend", "_watch"):
        monkeypatch.setattr(s, name, nothing)
    s.add_file(zipped(app_folder(tmp_path)))
    stray = s.version_dir("notes", 1)
    (stray / "server").mkdir(parents=True)
    (stray / "server" / "old.ts").write_text("// a lost state's\n")
    asyncio.run(s.deploy("notes"))
    assert [d.seq for d in s.get("notes").deployments] == [1]
    assert sorted(p.name for p in (stray / "server").iterdir()) == ["main.ts"]


def test_a_draft_reopened_while_the_reaper_closes_the_idle_one_stays_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reaper is stopping an idle opened draft when the person opens it again: the reopen
    waits for it, and the draft it opens stays open, its copies there. (The runtime is stubbed:
    the idle draft's backend stops until the test lets it.)

    If this fails: opening a draft again just as the idle one is reaped shows a draft whose
    address answers nothing, or whose code was deleted under it."""
    s = store(tmp_path)
    s.settings = dataclasses.replace(s.settings, app_idle_timeout=0.1)
    folder = app_folder(tmp_path)
    stopping, stopped = asyncio.Event(), asyncio.Event()

    async def start(*args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(last_used=time.monotonic())

    async def stop_backend(backend: Any) -> None:
        if backend.last_used == 0.0:  # the idle draft's
            stopping.set()
            await stopped.wait()

    async def nothing(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(s, "_start", start)
    monkeypatch.setattr(s, "_stop_backend", stop_backend)
    monkeypatch.setattr(s, "_pull_runtime", nothing)

    async def scenario() -> None:
        await s.open_draft("s1", folder, None)
        s.previews["notes"].backend.last_used = 0.0  # idle since long
        s.reaper = asyncio.create_task(s._reap())
        await asyncio.wait_for(stopping.wait(), 5)  # the reaper is stopping it
        reopen = asyncio.create_task(s.open_draft("s1", folder, None))
        for _ in range(20):
            await asyncio.sleep(0)
        stopped.set()
        await reopen
        s.reaper.cancel()

    asyncio.run(scenario())
    assert s.previews["notes"].backend.last_used > 0
    assert (s.app_dir("notes--draft") / "code" / "app.toml").is_file()
