"""Contract I — Automations (`handler.automation/v1`): *when this happens, run that*. When a session
stops or a schedule comes, handlerd runs the automation's run: the user's script in a sandbox (which
may call models through handlerd's `llm` service, and whose files handlerd appends to knowledge
notes), an agent with an interface (its result goes to the inbox), or a mini app's route.

`Automation` is hand-written TOML (`<config>/automations/<name>/automation.toml`): unknown keys
are errors. The rest is exchanged: the Control API's views and requests (I.9), and the `llm/v1`
service's one tool, `llm_complete` (I.5).
"""

import tomllib
from typing import Annotated, Any, Literal, Self

from pydantic import AfterValidator, AwareDatetime, Field, model_validator

from .common import Document, StrictDocument
from .miniapp import AppName

AUTOMATION_API_VERSION = "handler.automation/v1"
AUTOMATION_FILE = "automation.toml"

AutomationName = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]
AutomationEvent = Literal["session.stopped"]  # an event `when` (I.2); a schedule is the other
# a provider's model, "provider/model": the provider's name, then its model's id
LlmModel = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_.-]*/.+$")]
RunState = Literal["queued", "running", "succeeded", "failed", "cancelled", "interrupted"]
Day = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

MIN_EVERY_MINUTES = 5
DEFAULT_TIMEOUT_SEC = 600  # a script's (I.3)
MAX_LLM_INPUT = 256 * 1024  # system + prompt + input, in bytes (I.5)
MAX_LLM_SCHEMA = 64 * 1024
MAX_APPEND = 256 * 1024  # one `from` file (I.6)


def _output_path(p: str) -> str:
    if p.startswith("/") or ".." in p.split("/"):
        raise ValueError("must be relative to the run's output folder, without '..'")
    return p


class Schedule(StrictDocument):
    """A `when` that is a time (I.2): every N minutes or hours, or at a local time of day."""

    every: Annotated[str, Field(pattern=r"^[1-9]\d{0,3}[mh]$")] | None = None  # "30m", "2h"
    at: Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")] | None = None  # local time
    days: list[Day] | None = None  # with `at`; default every day

    @model_validator(mode="after")
    def _one_rule(self) -> Self:
        if (self.every is None) == (self.at is None):
            raise ValueError("a schedule has either 'every' or 'at'")
        if self.days is not None and self.at is None:
            raise ValueError("'days' goes with 'at'")
        if not (self.days is None or self.days):
            raise ValueError("'days' lists at least one day")
        if self.every_minutes is not None and self.every_minutes < MIN_EVERY_MINUTES:
            raise ValueError(f"'every' is at least {MIN_EVERY_MINUTES}m")
        return self

    @property
    def every_minutes(self) -> int | None:
        if self.every is None:
            return None
        return int(self.every[:-1]) * (60 if self.every.endswith("h") else 1)

    @property
    def label(self) -> str:
        """ "every 1h", "at 08:30", "at 08:30 mon,fri"."""
        if self.every is not None:
            return f"every {self.every}"
        return " ".join(x for x in (f"at {self.at}", ",".join(self.days or [])) if x)


class AutomationOnly(StrictDocument):
    """The sessions an automation is for: by their project's name, their agent's; absent: any."""

    project: list[str] | None = None
    agent: list[str] | None = None


class AutomationServices(StrictDocument):
    llm: list[LlmModel] = []  # the models the script may call (I.5)


class AutomationAppend(StrictDocument):
    """A file the run wrote, appended by handlerd to a knowledge note once the run succeeded
    (I.6)."""

    from_: Annotated[str, Field(alias="from", min_length=1), AfterValidator(_output_path)]
    to: Annotated[str, Field(min_length=1)]  # a markdown note, relative to the knowledge root


class AutomationSubject(StrictDocument):
    skill: Annotated[str, Field(min_length=1)]  # a skill of the library (D.17)


class AutomationAgentInput(StrictDocument):
    """What the agent's run is started with (D.18 `SessionInput`)."""

    fields: dict[str, Any] = {}
    subject: AutomationSubject | None = None


class AutomationAgentRun(StrictDocument):
    """`run = { agent, project?, input? }`: a run of an agent with an interface (I.3, D.18)."""

    agent: Annotated[str, Field(min_length=1)]  # its name
    project: str | None = None  # its project's name; absent: an agent of no project
    input: AutomationAgentInput = AutomationAgentInput()


class AutomationAppCall(StrictDocument):
    """`run = { app, call }`: a call to a mini app's route, as the owner (I.3, H.9)."""

    app: AppName
    call: Annotated[str, Field(pattern=r"^POST /api/[A-Za-z0-9/_.-]*$")]


class Automation(StrictDocument):
    """automation.toml (I.1)."""

    api_version: Literal["handler.automation/v1"]
    description: str | None = None
    when: AutomationEvent | Schedule
    only: AutomationOnly | None = None  # with `session.stopped`
    # a script: a command line (`sh -c`), in its folder; or an agent run; or an app's route
    run: Annotated[str, Field(min_length=1)] | AutomationAgentRun | AutomationAppCall
    timeout_sec: Annotated[int, Field(ge=1, le=3600)] | None = None  # a script's, default 600
    services: AutomationServices | None = None  # a script's
    append: list[AutomationAppend] = []  # a script's

    @model_validator(mode="after")
    def _fits(self) -> Self:
        if self.only is not None and self.schedule is not None:
            raise ValueError("'only' goes with when = \"session.stopped\"")
        if self.script is None:
            for key, value in (
                ("timeoutSec", self.timeout_sec),
                ("services", self.services),
                ("append", self.append or None),
            ):
                if value is not None:
                    raise ValueError(f"'{key}' goes with a script run")
        return self

    @property
    def schedule(self) -> Schedule | None:
        return self.when if isinstance(self.when, Schedule) else None

    @property
    def script(self) -> str | None:
        return self.run if isinstance(self.run, str) else None

    @property
    def agent_run(self) -> AutomationAgentRun | None:
        return self.run if isinstance(self.run, AutomationAgentRun) else None

    @property
    def app_call(self) -> AutomationAppCall | None:
        return self.run if isinstance(self.run, AutomationAppCall) else None

    @classmethod
    def from_toml(cls, text: str) -> Self:
        return cls.model_validate(tomllib.loads(text))


class AutomationLlmUsage(Document):
    calls: int = 0
    in_tokens: int = 0
    out_tokens: int = 0


class AutomationAppended(Document):
    to: str
    bytes: int
    text: str | None = None  # a try's preview: the first 4 KiB of what it would append


class AutomationRun(Document):
    id: str  # "a_" + 16 hex
    automation: AutomationName
    trial: bool = False
    session_id: str | None = None  # the stopped session it read (I.4)
    seq_from: int | None = None
    seq_to: int | None = None
    slot: AwareDatetime | None = None  # the schedule's slot it ran for
    missed: int = 0  # slots before it, missed while handlerd was not running (only the last runs)
    agent_session_id: str | None = None  # an agent run's session (D.18)
    state: RunState
    exit_code: int | None = None
    ms: int | None = None
    llm: AutomationLlmUsage = AutomationLlmUsage()
    appended: list[AutomationAppended] = []
    error: str | None = None
    created_at: AwareDatetime
    ended_at: AwareDatetime | None = None


class AutomationView(Document):
    name: AutomationName
    description: str | None = None
    definition: Automation | None = None  # absent when it does not parse
    directory: str  # its folder, where its files are edited
    files: list[str] = []  # relative to it
    problems: list[str] = []
    enabled: bool = False
    permissions: list[str] = []  # what it may touch and what starts it, in sentences (I.7)
    warnings: list[str] = []  # what to know before turning it on (an account's terms, I.7)
    next_at: AwareDatetime | None = None  # a scheduled one's next slot, while it is on
    pending: int = 0  # runs waiting
    behind: AutomationName | None = None  # what runs now, when its runs wait (one at a time)
    capped: bool = False  # the daily cap is reached
    last_run: AutomationRun | None = None


class AutomationExample(Document):
    """An example automation handler ships (I.1), copied by `POST /v1/automations`."""

    name: AutomationName
    description: str | None = None


class CreateAutomationRequest(Document):
    """A new automation, off: a shipped example copied, or a definition handler writes as its
    automation.toml (the web UI's form, I.1). With `enable`, turned on at once (I.7)."""

    name: AutomationName
    from_: Annotated[AutomationName | None, Field(alias="from")] = None  # a shipped example
    definition: Automation | None = None
    enable: bool = False

    @model_validator(mode="after")
    def _one_source(self) -> Self:
        if (self.from_ is None) == (self.definition is None):
            raise ValueError("give either 'from' (an example) or 'definition'")
        if self.from_ is not None and self.enable:
            raise ValueError("an example is created off: edit it, then turn it on")
        return self


class AutomationDefinitionRequest(Document):
    """A definition to check (`POST /v1/automations/check`) or to write over an automation's
    automation.toml (`PUT /v1/automations/{name}`: the web UI's form, I.1)."""

    definition: Automation


class AutomationCheck(Document):
    """What a definition would do before it is saved (I.9): what `AutomationView` would say."""

    problems: list[str] = []
    warnings: list[str] = []
    permissions: list[str] = []
    next_at: AwareDatetime | None = None  # a schedule's first slot if it were turned on now


class TryAutomationRequest(Document):
    session_id: str | None = None  # the session read, for `when = "session.stopped"` (I.8)


class LlmUsage(StrictDocument):
    in_tokens: int
    out_tokens: int


class LlmRequest(StrictDocument):
    """`llm_complete`'s input (I.5)."""

    model: LlmModel  # one of the automation's `services.llm`
    system: str | None = None
    prompt: Annotated[str, Field(min_length=1)]
    input: str | None = None
    schema_: Annotated[dict[str, Any] | None, Field(alias="schema")] = None


class LlmResponse(StrictDocument):
    """`llm_complete`'s output (I.5)."""

    valid: bool
    value: Any = None  # with a schema: the parsed answer
    text: str | None = None  # without one: the answer
    error: str | None = None  # why it is not valid (its JSON, after the repair turn)
    usage: LlmUsage
    ms: int
