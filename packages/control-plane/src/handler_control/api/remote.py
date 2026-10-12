"""Remote control routes: the gateway, the status light, paired devices (D.7)."""

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import (
    PairDeviceRequest,
    SetRemoteGatewayRequest,
)

from ..remote import RemoteError
from .common import Context, ProblemError, dump, parse_body


def add_remote_routes(app: FastAPI, ctx: Context) -> None:
    authed = [Depends(ctx.require_auth)]

    @app.get("/v1/remote", dependencies=authed)
    def remote_status() -> Response:
        return dump(ctx.remote.status())

    @app.put("/v1/remote/gateway", dependencies=authed)
    async def set_gateway(request: Request) -> Response:
        body = parse_body(SetRemoteGatewayRequest, await request.body())
        ctx.remote.set_gateway(body.gateway_url, body.host_token)
        return dump(ctx.remote.status())

    @app.delete("/v1/remote/gateway", dependencies=authed)
    async def clear_gateway() -> Response:
        ctx.remote.clear_gateway()
        return dump(ctx.remote.status())

    @app.post("/v1/remote/devices", dependencies=authed)
    async def pair_device(request: Request) -> Response:
        body = parse_body(PairDeviceRequest, await request.body())
        try:
            return dump(await ctx.remote.pair(body.name, body.person, body.scope), status=201)
        except RemoteError as e:
            raise ProblemError(409, "cannot pair a device", str(e)) from None

    @app.delete("/v1/remote/devices/{device_id}", dependencies=authed)
    async def revoke_device(device_id: str) -> Response:
        if not await ctx.remote.revoke(device_id):
            raise ProblemError(404, "device not found", device_id)
        return Response(status_code=204)
