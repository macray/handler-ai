"""Generate schemas/*.schema.json from the pydantic contracts (single source of truth).

Usage:
    python -m handler_contracts.schemas [OUT_DIR]          write files
    python -m handler_contracts.schemas --check [OUT_DIR]  exit 1 if files are out of date
"""

import json
import sys
from pathlib import Path

from pydantic import BaseModel

from .account import ACCOUNT_API_VERSION, Account
from .addon import ADDON_API_VERSION, BINDING_API_VERSION, AddonManifest, Binding
from .app import APP_API_VERSION, AppManifest
from .automation import (
    AUTOMATION_API_VERSION,
    Automation,
    AutomationCheck,
    AutomationDefinitionRequest,
    AutomationExample,
    AutomationRun,
    AutomationView,
    CreateAutomationRequest,
    TryAutomationRequest,
)
from .control import (
    CONTROL_API_VERSION,
    SOURCE_API_VERSION,
    AccountInfo,
    AccountLoginRequest,
    AccountRequest,
    ActionRequest,
    ActionRun,
    AddonInfo,
    AddonInstalled,
    AddonInstallRequest,
    AddonPreview,
    AddonPreviewRequest,
    AddSourceRequest,
    Agent,
    AgentChecks,
    AgentRequest,
    AgentsExport,
    AgentsFile,
    App,
    AppAction,
    AppLink,
    AppLog,
    AreaInfo,
    AreaRequest,
    AssistantAnswer,
    AssistantRequest,
    BindingInfo,
    BindingRequest,
    Build,
    BuildLog,
    CachesInfo,
    CacheSizes,
    CachesRequest,
    Check,
    CheckRun,
    CheckUpdateRequest,
    CreateDirectoryRequest,
    CreateKnowledgeFolderRequest,
    CreateProjectRequest,
    CreateSessionRequest,
    CreateSkillRequest,
    DirectoryListing,
    DraftPreview,
    EgressEvent,
    ExportAgentsRequest,
    HandlerNeed,
    HarnessInfo,
    Health,
    ImageUpdates,
    ImageUpdatesRequest,
    Improvement,
    InboxMessage,
    KeepAttemptRequest,
    KeepCheckRequest,
    KnowledgeFolderView,
    KnowledgeListing,
    KnowledgeNote,
    LoginWindow,
    NetworkFilterInfo,
    PairDeviceRequest,
    PatchAgentRequest,
    Problem,
    Project,
    ProjectSettingsRequest,
    ProviderInfo,
    ProviderRequest,
    ProviderTemplate,
    PutSecretRequest,
    RemotePairing,
    RemoteStatus,
    RevealRequest,
    SecretInfo,
    Session,
    SessionChanges,
    SessionFile,
    SessionFolder,
    SessionFound,
    SessionMounts,
    SetAppAgentRequest,
    SetAppFileRequest,
    SetAppPersonsRequest,
    SetAppSecretRequest,
    SetHandlerNeedAgentRequest,
    SetKnowledgeRootRequest,
    SetProjectPinnedRequest,
    SetRemoteGatewayRequest,
    SetSessionRemoteRequest,
    SkillFile,
    SkillFileRequest,
    SkillInfo,
    SkillRequest,
    SkillUrlRequest,
    Source,
    SourceItemDetail,
    SourceManifest,
    SpeechRequest,
    StartImprovementRequest,
    ToolboxContainerfile,
    ToolboxContainerfileUpdate,
    ToolboxInfo,
    Transcription,
    Uses,
    Voice,
    VoiceSettings,
    WorkFolderInfo,
    WorkFolders,
    WorkFoldersInfo,
)
from .harness import (
    HARNESS_API_VERSION,
    HARNESS_LAUNCH_API_VERSION,
    HarnessDescriptor,
    HarnessLaunch,
)
from .provider import PROVIDER_API_VERSION, Provider
from .remote import (
    REMOTE_API_VERSION,
    ActionRunParams,
    AgentList,
    AppHttpAnswer,
    AppHttpParams,
    AppList,
    AppUi,
    AppUiParams,
    AskAnswer,
    AskOptions,
    AskParams,
    ClosedNotice,
    DetachParams,
    InboxList,
    PushKey,
    PushSubscribeParams,
    PushSubscription,
    RemoteActionRun,
    RemoteAgent,
    RemoteProject,
    RemoteTranscription,
    SessionList,
    SharedApp,
    SharedApps,
    SharedSession,
    StartedSession,
    StartSessionParams,
    TranscribeParams,
)
from .sandbox import SANDBOX_API_VERSION, RuntimeCheck, SandboxSpec

DEFAULT_OUT_DIR = Path(__file__).resolve().parents[4] / "schemas"


def _control(name: str) -> str:
    return f"{CONTROL_API_VERSION}/{name}"


def _remote(name: str) -> str:
    return f"{REMOTE_API_VERSION}/{name}"


DOCUMENTS: list[tuple[str, type[BaseModel]]] = [
    (ACCOUNT_API_VERSION, Account),
    (PROVIDER_API_VERSION, Provider),
    (HARNESS_API_VERSION, HarnessDescriptor),
    (HARNESS_LAUNCH_API_VERSION, HarnessLaunch),
    (SANDBOX_API_VERSION, SandboxSpec),
    (ADDON_API_VERSION, AddonManifest),
    (BINDING_API_VERSION, Binding),
    (APP_API_VERSION, AppManifest),
    (SOURCE_API_VERSION, SourceManifest),
    (AUTOMATION_API_VERSION, Automation),
    (_control("app"), App),
    (_control("app-action"), AppAction),
    (_control("action-request"), ActionRequest),
    (_control("action-run"), ActionRun),
    (_control("assistant-request"), AssistantRequest),
    (_control("assistant-answer"), AssistantAnswer),
    (_control("voice-settings"), VoiceSettings),
    (_control("draft-preview"), DraftPreview),
    (_control("voice"), Voice),
    (_control("speech-request"), SpeechRequest),
    (_control("transcription"), Transcription),
    (_control("app-link"), AppLink),
    (_control("app-log"), AppLog),
    (_control("inbox-message"), InboxMessage),
    (_control("set-app-persons-request"), SetAppPersonsRequest),
    (_control("set-app-secret-request"), SetAppSecretRequest),
    (_control("set-app-file-request"), SetAppFileRequest),
    (_control("set-app-agent-request"), SetAppAgentRequest),
    (_control("set-handler-need-agent-request"), SetHandlerNeedAgentRequest),
    (_control("addon-info"), AddonInfo),
    (_control("addon-preview"), AddonPreview),
    (_control("addon-preview-request"), AddonPreviewRequest),
    (_control("addon-install-request"), AddonInstallRequest),
    (_control("addon-installed"), AddonInstalled),
    (_control("binding-info"), BindingInfo),
    (_control("binding-request"), BindingRequest),
    (_control("area-info"), AreaInfo),
    (_control("area-request"), AreaRequest),
    (_control("skill-info"), SkillInfo),
    (_control("skill-file"), SkillFile),
    (_control("skill-file-request"), SkillFileRequest),
    (_control("skill-request"), SkillRequest),
    (_control("create-skill-request"), CreateSkillRequest),
    (_control("skill-url-request"), SkillUrlRequest),
    (_control("harness-info"), HarnessInfo),
    (_control("toolbox-info"), ToolboxInfo),
    (_control("network-filter-info"), NetworkFilterInfo),
    (_control("image-updates"), ImageUpdates),
    (_control("image-updates-request"), ImageUpdatesRequest),
    (_control("runtime-check"), RuntimeCheck),  # A.8, as GET /v1/runtime returns it
    (_control("toolbox-containerfile"), ToolboxContainerfile),
    (_control("toolbox-containerfile-update"), ToolboxContainerfileUpdate),
    (_control("caches-info"), CachesInfo),
    (_control("caches-request"), CachesRequest),
    (_control("cache-sizes"), CacheSizes),
    (_control("build"), Build),
    (_control("build-log"), BuildLog),
    (_control("account-info"), AccountInfo),
    (_control("account-request"), AccountRequest),
    (_control("account-login-request"), AccountLoginRequest),
    (_control("login-window"), LoginWindow),
    (_control("provider-info"), ProviderInfo),
    (_control("secret-info"), SecretInfo),
    (_control("put-secret-request"), PutSecretRequest),
    (_control("provider-template"), ProviderTemplate),
    (_control("provider-request"), ProviderRequest),
    (_control("patch-agent-request"), PatchAgentRequest),
    (_control("agent"), Agent),
    (_control("handler-need"), HandlerNeed),
    (_control("agents-file"), AgentsFile),
    (_control("export-agents-request"), ExportAgentsRequest),
    (_control("agents-export"), AgentsExport),
    (_control("source"), Source),
    (_control("source-item-detail"), SourceItemDetail),
    (_control("add-source-request"), AddSourceRequest),
    (_control("work-folders"), WorkFolders),
    (_control("work-folder-info"), WorkFolderInfo),
    (_control("work-folders-info"), WorkFoldersInfo),
    (_control("create-project-request"), CreateProjectRequest),
    (_control("project-settings-request"), ProjectSettingsRequest),
    (_control("set-project-pinned-request"), SetProjectPinnedRequest),
    (_control("agent-request"), AgentRequest),
    (_control("project"), Project),
    (_control("create-session-request"), CreateSessionRequest),
    (_control("session"), Session),
    (_control("check"), Check),
    (_control("check-run"), CheckRun),
    (_control("agent-checks"), AgentChecks),
    (_control("keep-check-request"), KeepCheckRequest),
    (_control("check-update-request"), CheckUpdateRequest),
    (_control("improvement"), Improvement),
    (_control("uses"), Uses),
    (_control("start-improvement-request"), StartImprovementRequest),
    (_control("keep-attempt-request"), KeepAttemptRequest),
    (_control("set-session-remote-request"), SetSessionRemoteRequest),
    (_control("session-changes"), SessionChanges),
    (_control("session-folder"), SessionFolder),
    (_control("session-file"), SessionFile),
    (_control("session-found"), SessionFound),
    (_control("session-mounts"), SessionMounts),
    (_control("reveal-request"), RevealRequest),
    (_control("remote-status"), RemoteStatus),
    (_control("set-remote-gateway-request"), SetRemoteGatewayRequest),
    (_control("pair-device-request"), PairDeviceRequest),
    (_control("remote-pairing"), RemotePairing),
    (_control("egress-event"), EgressEvent),
    (_control("health"), Health),
    (_control("directory-listing"), DirectoryListing),
    (_control("create-directory-request"), CreateDirectoryRequest),
    (_control("knowledge-listing"), KnowledgeListing),
    (_control("set-knowledge-root-request"), SetKnowledgeRootRequest),
    (_control("create-knowledge-folder-request"), CreateKnowledgeFolderRequest),
    (_control("knowledge-folder-view"), KnowledgeFolderView),
    (_control("knowledge-note"), KnowledgeNote),
    (_control("problem"), Problem),
    (_control("automation-view"), AutomationView),
    (_control("automation-run"), AutomationRun),
    (_control("automation-example"), AutomationExample),
    (_control("create-automation-request"), CreateAutomationRequest),
    (_control("try-automation-request"), TryAutomationRequest),
    (_control("automation-definition-request"), AutomationDefinitionRequest),
    (_control("automation-check"), AutomationCheck),
    (_remote("shared-session"), SharedSession),
    (_remote("remote-agent"), RemoteAgent),
    (_remote("remote-project"), RemoteProject),
    (_remote("ask-params"), AskParams),
    (_remote("ask-answer"), AskAnswer),
    (_remote("ask-options"), AskOptions),
    (_remote("action-run-params"), ActionRunParams),
    (_remote("action-run"), RemoteActionRun),
    (_remote("transcribe-params"), TranscribeParams),
    (_remote("transcription"), RemoteTranscription),
    (_remote("shared-app"), SharedApp),
    (_remote("session-list"), SessionList),
    (_remote("agent-list"), AgentList),
    (_remote("start-session-params"), StartSessionParams),
    (_remote("started-session"), StartedSession),
    (_remote("shared-apps"), SharedApps),
    (_remote("app-list"), AppList),
    (_remote("inbox-list"), InboxList),
    (_remote("push-key"), PushKey),
    (_remote("push-subscribe-params"), PushSubscribeParams),
    (_remote("push-subscription"), PushSubscription),
    (_remote("detach-params"), DetachParams),
    (_remote("closed-notice"), ClosedNotice),
    (_remote("app-ui-params"), AppUiParams),
    (_remote("app-ui"), AppUi),
    (_remote("app-http-params"), AppHttpParams),
    (_remote("app-http-answer"), AppHttpAnswer),
]


def render() -> dict[str, str]:
    """File name → JSON Schema text. Schemas describe documents as written (validation mode)."""
    files: dict[str, str] = {}
    for doc_id, model in DOCUMENTS:
        schema = model.model_json_schema(by_alias=True, mode="validation")
        doc = {"$id": f"urn:{doc_id}", "$schema": "https://json-schema.org/draft/2020-12/schema"}
        files[f"{doc_id.replace('/', '.')}.schema.json"] = json.dumps(doc | schema, indent=2) + "\n"
    return files


def main(argv: list[str]) -> int:
    check = "--check" in argv
    args = [a for a in argv if a != "--check"]
    out_dir = Path(args[0]) if args else DEFAULT_OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    rendered = render()
    stale = [
        name
        for name, content in rendered.items()
        if not (out_dir / name).exists() or (out_dir / name).read_text() != content
    ]
    extra = sorted(p.name for p in out_dir.glob("*.schema.json") if p.name not in rendered)
    if check:
        if stale or extra:
            print(
                f"schemas out of date: {', '.join(stale + extra)} (run the generator)",
                file=sys.stderr,
            )
            return 1
        print("schemas up to date")
        return 0
    for name in extra:
        (out_dir / name).unlink()
    for name, content in rendered.items():
        (out_dir / name).write_text(content)
    print(f"wrote {len(rendered)} schemas to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
