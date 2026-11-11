"""Control API (contract D) and the ACP WebSocket endpoints (contract C) — FastAPI app.

Routes are thin: they authenticate, parse, call the domain (the rules an agent or a project must
pass are in save_rules.py) and turn its answer or its errors into HTTP. One module per contract
section, wired by `create_app` in this order:

    common       problem details (RFC 9457), dump, parse_body, the Context every route gets
    catalog      GET /v1/health · /v1/harnesses · /v1/addons · /v1/knowledge … · /v1/directories
    accounts     /v1/accounts … and their login (D.9)
    providers    /v1/providers … · /v1/provider-templates (D.12)
    bindings     /v1/bindings … (G.2, D.15)
    skills       /v1/skills …, their files and archives (D.17)
    folders      /v1/folders (D.13)
    secrets      /v1/secrets … (D.14)
    images       /v1/harnesses/{name}/rebuild · /v1/toolbox … · /v1/addons/{name}/rebuild ·
                 /v1/builds … (D.4)
    projects     /v1/projects … (D.8)
    agents       /v1/agents … every agent, whatever its home (D.1, D.2): created, updated,
                 deleted; POST /v1/agents/{id}/terminal → its terminal program's sandbox (D.16)
    sessions     /v1/sessions … daemon-held chats (F)
    plans        /v1/plans … steps written, approved and run one after another; /v1/plan-drafts …
                 the plans being written (D.27)
    remote       /v1/remote … (D.7, remote design)
    apps         /v1/apps … (H, apps design); the apps themselves are served
                 at their own origins (app_http.py), outermost
    automations  /v1/automations …, /v1/automation-examples, their runs; the runs on a session
                 (I.9)
    inbox        /v1/inbox … what handler tells the person (apps' notifications, automations'
                 results)
    ui           /v1/ui … the web UI's sign-in: a one-time link sets its cookie (auth.py)
    acp          WebSocket /v1/agents/{id}/acp → launcher.start → Relay(policy) (C)
                 WebSocket /v1/sessions/{id}/acp → attach to a daemon-held session (F.4)
    web UI       static files at / + folder picker (webui.py), mounted last
"""

import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI

from handler_contracts import RefusedHost

from .. import __version__, auth, refusals, webui
from ..agent_checks import CheckStore
from ..agent_service import AgentService
from ..agents import AgentRecord, AgentRegistry
from ..app_http import AppOrigins
from ..app_runs import AppRuns
from ..apps import AppStore
from ..assistant import Assistant
from ..automations import Automations
from ..builds import BuildStore
from ..image_updates import ImageUpdater
from ..improvements import ImprovementStore
from ..inbox import Inbox
from ..plan_drafts import PlanDrafts
from ..plans import PlanStore, install_skill
from ..projects import ProjectRegistry
from ..remote import Connector
from ..sessions import SessionRecord, SessionStore
from ..settings import Settings
from ..uses import UseGraph
from ..voice import VoiceStore
from .accounts import add_account_login_routes, add_account_routes
from .acp import add_acp_endpoint
from .addons import add_addon_install_routes
from .agent_checks import add_agent_check_routes
from .agents import add_agent_routes
from .agents_files import add_agents_file_routes
from .apps import add_app_routes
from .areas import add_area_routes
from .ask import add_ask_routes
from .automations import add_automation_routes
from .bindings import add_binding_routes
from .caches import add_cache_routes
from .catalog import add_catalog_routes
from .common import Context, add_error_handlers
from .folders import add_folder_routes
from .handler_needs import add_handler_need_routes
from .images import add_addon_image_routes, add_image_routes
from .inbox import add_inbox_routes
from .pins import add_pin_routes
from .plans import add_plan_routes
from .projects import add_project_routes
from .providers import add_provider_routes
from .remote import add_remote_routes
from .secrets import add_secret_routes
from .sessions import add_session_routes
from .skills import add_skill_archive_routes, add_skill_file_routes, add_skill_routes
from .sources import add_source_routes
from .toolbox import add_toolbox_routes
from .ui import add_ui_routes
from .uses import add_use_routes
from .voice import add_voice_routes


def create_app(settings: Settings) -> FastAPI:
    token = auth.load_or_create_token(settings.token_file)
    registry = AgentRegistry(settings.state_dir)
    sessions = SessionStore(settings, registry)
    projects = ProjectRegistry(settings.state_dir, registry)
    inbox = Inbox(settings)

    def refused_while_away(
        rec: SessionRecord, agent: AgentRecord, hosts: list[RefusedHost]
    ) -> None:
        inbox.add(**refusals.session_message(rec, agent, hosts))

    sessions.refusal_listeners.append(refused_while_away)
    apps = AppStore(settings, token, inbox, AppRuns(settings, sessions, projects, inbox))
    ctx = Context(
        settings,
        token,
        registry,
        projects,
        sessions,
        builds := BuildStore(settings, registry),
        Connector(settings, sessions, apps),
        apps,
        ImageUpdater(settings, builds, registry),
        automations := Automations(settings, sessions, registry, projects, apps=apps, inbox=inbox),
        inbox,
        checks := CheckStore(settings, sessions),
        improvements := ImprovementStore(settings, registry, checks),
        UseGraph(settings, projects, automations, apps),
        Assistant(settings, apps, sessions),
        VoiceStore(settings),
        AgentService(
            settings,
            projects=projects,
            sessions=sessions,
            checks=checks,
            improvements=improvements,
            apps=apps,
        ),
        PlanStore(settings, registry, projects, sessions, inbox),
        PlanDrafts(settings, projects),
    )

    ctx.remote.projects = ctx.projects
    ctx.remote.assistant = ctx.assistant
    ctx.remote.voice = ctx.voice

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        ctx.remote.start()
        ctx.apps.start()
        ctx.updates.start()
        ctx.automations.start()
        install_skill(settings)
        ctx.plans.start_watching()
        yield
        await ctx.plans.close()
        await ctx.improvements.close()
        await ctx.checks.close()
        await ctx.automations.close()
        await ctx.updates.close()
        await ctx.apps.close()
        await ctx.remote.close()

    app = FastAPI(title="handler control plane", version=__version__, lifespan=lifespan)
    add_routes(app, ctx)
    webui.mount(app, settings)  # last: /v1 routes always take precedence
    app.add_middleware(AppOrigins, store=ctx.apps, port=settings.port)  # outermost (H.4)
    return app


def add_routes(app: FastAPI, ctx: Context) -> None:
    """Every route of the Control API (D), one module per contract section."""
    add_error_handlers(app)
    add_catalog_routes(app, ctx)
    add_account_routes(app, ctx)
    add_account_login_routes(app, ctx)
    add_provider_routes(app, ctx)
    add_area_routes(app, ctx)
    add_binding_routes(app, ctx)
    add_skill_routes(app, ctx)
    add_skill_file_routes(app, ctx)
    add_skill_archive_routes(app, ctx)
    add_handler_need_routes(app, ctx)
    add_agents_file_routes(app, ctx)
    add_folder_routes(app, ctx)
    add_cache_routes(app, ctx)
    add_secret_routes(app, ctx)
    add_toolbox_routes(app, ctx)
    add_image_routes(app, ctx)
    add_addon_image_routes(app, ctx)
    add_addon_install_routes(app, ctx)
    add_source_routes(app, ctx)
    add_project_routes(app, ctx)
    add_pin_routes(app, ctx)
    add_agent_routes(app, ctx)
    add_agent_check_routes(app, ctx)
    add_use_routes(app, ctx)
    add_session_routes(app, ctx)
    add_plan_routes(app, ctx)
    add_remote_routes(app, ctx)
    add_app_routes(app, ctx)
    add_ask_routes(app, ctx)
    add_voice_routes(app, ctx)
    add_automation_routes(app, ctx)
    add_inbox_routes(app, ctx)
    add_ui_routes(app, ctx)
    add_acp_endpoint(app, ctx)
