"""Image routes: harness, toolbox, network filter and addon rebuilds, build progress and logs
(D.4, G.4), the user's toolbox Containerfile (B.6)."""

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import (
    Build,
    ImageUpdatesRequest,
    NetworkFilterInfo,
    ToolboxContainerfile,
    ToolboxContainerfileUpdate,
    ToolboxInfo,
)
from handler_harness import addons as addon_catalog
from handler_harness import catalog, images

from .. import runtime
from ..builds import (
    ADDON_PREFIX,
    NETWORK_FILTER_TARGET,
    TOOLBOX_TARGET,
    BuildBusyError,
    NoImageError,
)
from .common import Context, ProblemError, dump, parse_body


def start_build(ctx: Context, target: str) -> Response:
    try:
        return dump(ctx.builds.start(target), status=202)
    except BuildBusyError as e:
        raise ProblemError(409, "a build is already running", str(e)) from None


def add_addon_image_routes(app: FastAPI, ctx: Context) -> None:
    """Rebuild addon images (G.4), like harness images."""
    authed = [Depends(ctx.require_auth)]

    def addon_target(name: str) -> str:
        """`addon:<name>` for an addon with an image; 404 otherwise, 409 if its files are wrong."""
        target = f"{ADDON_PREFIX}{name}"
        try:
            ctx.builds.check_target(target)
        except (addon_catalog.UnknownAddonError, NoImageError) as e:
            raise ProblemError(404, "addon image not found", str(e)) from None
        except addon_catalog.InvalidAddonError as e:
            raise ProblemError(409, "addon invalid", str(e)) from None
        return target

    @app.post("/v1/addons/{name}/rebuild", dependencies=authed)
    async def rebuild_addon(name: str) -> Response:
        return start_build(ctx, addon_target(name))


def add_image_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]

    def get_harness(name: str) -> catalog.Harness:
        try:
            return catalog.get(name)
        except catalog.UnknownHarnessError:
            raise ProblemError(404, "harness not found", name) from None

    def get_build(build_id: str) -> Build:
        build = ctx.builds.get(build_id)
        if build is None:
            raise ProblemError(404, "build not found", build_id)
        return build

    def start(target: str) -> Response:
        return start_build(ctx, target)

    @app.get("/v1/toolbox", dependencies=authed)
    def toolbox() -> Response:
        latest = runtime.inspect(images.ref(images.TOOLBOX, images.LATEST))
        return dump(
            ToolboxInfo(
                image=images.TOOLBOX,
                image_present=latest is not None,
                built_at=latest.created if latest else None,
                directory=str(catalog.toolbox_dir()),
            )
        )

    @app.get("/v1/network-filter", dependencies=authed)
    def network_filter() -> Response:
        found = runtime.proxy()
        return dump(
            NetworkFilterInfo(
                image=found.ref,
                image_present=found.image is not None,
                built_at=found.image.created if found.image else None,
            )
        )

    @app.post("/v1/network-filter/rebuild", dependencies=authed)
    async def rebuild_network_filter() -> Response:
        return start(NETWORK_FILTER_TARGET)

    @app.get("/v1/image-updates", dependencies=authed)
    def image_updates() -> Response:
        return dump(ctx.updates.view())

    @app.put("/v1/image-updates", dependencies=authed)
    async def set_image_updates(request: Request) -> Response:
        body = parse_body(ImageUpdatesRequest, await request.body())
        return dump(ctx.updates.set_schedule(body.schedule))

    @app.post("/v1/image-updates/run", dependencies=authed)
    async def run_image_updates() -> Response:
        """Update the network filter and every built harness and addon image now (one build
        after the other)."""
        if not ctx.updates.run_now():
            raise ProblemError(409, "image updates are already running")
        return dump(ctx.updates.view(), status=202)

    @app.get("/v1/toolbox/containerfile", dependencies=authed)
    def toolbox_containerfile() -> Response:
        try:
            content = (catalog.toolbox_dir() / "Containerfile").read_text()
        except OSError as e:
            raise ProblemError(404, "toolbox Containerfile missing", str(e)) from None
        default = (catalog.DEFAULT_TOOLBOX / "Containerfile").read_text()
        return dump(ToolboxContainerfile(content=content, default_content=default))

    @app.put("/v1/toolbox/containerfile", dependencies=authed)
    async def save_toolbox_containerfile(request: Request) -> Response:
        """Saved whole; the next toolbox rebuild uses it (nothing is rebuilt here)."""
        body = parse_body(ToolboxContainerfileUpdate, await request.body())
        path = catalog.toolbox_dir() / "Containerfile"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.tmp")
        tmp.write_text(body.content)
        tmp.replace(path)
        return toolbox_containerfile()

    @app.post("/v1/toolbox/rebuild", dependencies=authed)
    async def rebuild_toolbox() -> Response:
        return start(TOOLBOX_TARGET)

    @app.post("/v1/harnesses/{name}/rebuild", dependencies=authed)
    async def rebuild_harness(name: str) -> Response:
        return start(get_harness(name).name)

    @app.get("/v1/builds", dependencies=authed)
    def list_builds() -> Response:
        return dump(ctx.builds.list())

    @app.get("/v1/builds/{build_id}", dependencies=authed)
    def inspect_build(build_id: str) -> Response:
        return dump(get_build(build_id))

    @app.get("/v1/builds/{build_id}/log", dependencies=authed)
    def build_log(build_id: str, offset: int = 0) -> Response:
        return dump(ctx.builds.read_log(get_build(build_id), offset))

    @app.post("/v1/builds/{build_id}/cancel", dependencies=authed)
    async def cancel_build(build_id: str) -> Response:
        get_build(build_id)
        if not ctx.builds.cancel(build_id):
            raise ProblemError(409, "build is not running")
        await ctx.builds.wait(build_id)
        return dump(get_build(build_id))
