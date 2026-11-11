"""Provider routes: providers and their templates (D.12)."""

from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import (
    Protocol,
    ProviderInfo,
    ProviderRequest,
    ProviderTestRequest,
)

from .. import (
    llm,
    provider_reach,
    providers,
    secrets,
)
from .accounts import references
from .areas import check_areas
from .common import Context, ProblemError, dump, log, parse_body


def add_provider_routes(app: FastAPI, ctx: Context) -> None:
    """D.12: written from the forms (their key goes to the secret store), or by hand."""
    authed = [Depends(ctx.require_auth)]
    settings = ctx.settings
    store = secrets.SecretStore(settings.data_dir)

    def info(name: str) -> ProviderInfo:
        return next(p for p in provider_infos(ctx) if p.name == name)

    @app.get("/v1/providers", dependencies=authed)
    def list_providers() -> Response:
        return dump(provider_infos(ctx))

    @app.get("/v1/provider-templates", dependencies=authed)
    def list_provider_templates() -> Response:
        return dump(providers.templates())

    @app.post("/v1/providers", dependencies=authed)
    async def create_provider(request: Request) -> Response:
        body = parse_body(ProviderRequest, await request.body())
        check_areas(ctx, body.areas)
        try:
            providers.save(settings.providers_dir, store, body, None)
        except providers.ProviderError as e:
            raise ProblemError(409, "cannot create the provider", str(e)) from None
        log.info("provider %s created", body.name)
        return dump(info(body.name), status=201)

    @app.post("/v1/providers/test", dependencies=authed)
    async def test_provider(request: Request) -> Response:
        """Ask its server for its models from where a sandbox would (D.12): the endpoints typed,
        or a saved provider's. A saved key goes to its own endpoints' hosts only (E3)."""
        body = parse_body(ProviderTestRequest, await request.body())
        endpoints, key = what_to_test(ctx, store, body)
        reach = await provider_reach.test(endpoints, key)
        ctx.reaches.keep(reach)
        log.info("provider test %s: %s", ", ".join(reach.urls), reach.error or "answered")
        return dump(reach)

    @app.put("/v1/providers/{name}", dependencies=authed)
    async def replace_provider(name: str, request: Request) -> Response:
        """Replace it, and rename it while no agent uses it; its agents follow at their next
        start. Without `key`, its key is kept (a hand-written reference too)."""
        body = parse_body(ProviderRequest, await request.body())
        check_areas(ctx, body.areas)
        old = providers.get(settings.providers_dir, name)
        if not old.path.is_file():
            raise ProblemError(404, "provider not found", name)
        if body.name != name and (users := references(ctx)["provider"].get(name)):
            raise ProblemError(409, "provider in use: cannot rename it", ", ".join(users))
        try:
            providers.save(settings.providers_dir, store, body, old)
        except providers.ProviderError as e:
            raise ProblemError(409, "cannot rename the provider", str(e)) from None
        log.info("provider %s saved", body.name)
        return dump(info(body.name))

    @app.delete("/v1/providers/{name}", dependencies=authed)
    def delete_provider(name: str) -> Response:
        """It and its key in the secret store. The agents using it keep its name, a model that
        cannot start until they are given another provider (E1)."""
        if not providers.get(settings.providers_dir, name).path.is_file():
            raise ProblemError(404, "provider not found", name)
        providers.delete(settings.providers_dir, store, name)
        log.info("provider %s deleted", name)
        return Response(status_code=204)


def what_to_test(
    ctx: Context, store: secrets.SecretStore, body: ProviderTestRequest
) -> tuple[dict[Protocol, str], str | None]:
    """The endpoints to ask and the key to send (D.12): those typed, else the saved provider's;
    its key only to its own endpoints' hosts (E3)."""
    endpoints = body.endpoints
    key = body.key
    if body.provider is not None:
        saved = providers.get(ctx.settings.providers_dir, body.provider)
        if not saved.path.is_file():
            raise ProblemError(404, "provider not found", body.provider)
        if saved.provider is None:
            raise ProblemError(409, "the provider is invalid", saved.error)
        own = {urlparse(url).hostname for url in saved.provider.endpoints.values()}
        endpoints = endpoints or dict(saved.provider.endpoints)
        hosts = {urlparse(url).hostname for url in endpoints.values()}
        if key is None and saved.provider.api_key is not None and hosts <= own:
            try:
                key = secrets.resolve(saved.provider.api_key, store)
            except secrets.SecretError as e:
                raise ProblemError(409, "its key cannot be read", str(e)) from None
    assert endpoints is not None  # the request names endpoints or a provider
    return endpoints, key


def provider_infos(ctx: Context) -> list[ProviderInfo]:
    """The providers, their status and the agents using them."""
    settings = ctx.settings
    using = references(ctx)["provider"]
    store = secrets.SecretStore(settings.data_dir)
    infos = []
    for loaded in providers.load_all(settings.providers_dir):
        names = using.get(loaded.name, [])
        if (spec := loaded.provider) is None:
            infos.append(
                ProviderInfo(name=loaded.name, status="invalid", error=loaded.error, agents=names)
            )
            continue
        problems = providers.problems(spec, store)
        key = spec.api_key
        infos.append(
            ProviderInfo(
                name=loaded.name,
                description=spec.description,
                endpoints=dict(spec.endpoints),
                models=spec.models,
                key=None if key is None else secrets.kind(key),
                status="incomplete" if problems else "ready",
                problems=problems,
                agents=names,
                harnesses=providers.harnesses(spec),
                model_alone=spec.endpoint_for(llm.PROTOCOLS) is not None,
                files=sorted(spec.files or {}),
                areas=spec.areas,
                local=provider_reach.local(spec.endpoints),
                reached=ctx.reaches.of(spec.endpoints),
            )
        )
    return infos
