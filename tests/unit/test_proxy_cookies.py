from collections.abc import Awaitable, Callable

import pytest
from aiohttp.test_utils import TestServer as _TestServer
from aiohttp.web import Application, Request, StreamResponse, json_response

from platform_registry_api.config import (
    UpstreamRegistryConfig,
    UpstreamType,
)
from platform_registry_api.upstream_client import UpstreamV2ApiClient


_TestServerFactory = Callable[[Application], Awaitable[_TestServer]]
_TestClientFactory = Callable[..., Awaitable[object]]


class _UpstreamHandler:
    def __init__(self) -> None:
        self.received_cookie_headers: list[str] = []

    async def handle(self, request: Request) -> StreamResponse:
        self.received_cookie_headers.extend(request.headers.getall("Cookie", []))
        return json_response(
            {},
            headers={"Set-Cookie": "sid=upstream-session; Path=/; HttpOnly"},
        )


class TestProxyCookies:
    @pytest.fixture
    async def upstream_handler(self) -> _UpstreamHandler:
        return _UpstreamHandler()

    @pytest.fixture
    async def proxy_client(
        self,
        aiohttp_server: _TestServerFactory,
        aiohttp_client: _TestClientFactory,
        upstream_handler: _UpstreamHandler,
    ) -> object:
        upstream_app = Application()
        upstream_app.router.add_route("*", "/v2/{tail:.+}", upstream_handler.handle)
        upstream_server = await aiohttp_server(upstream_app)

        config = UpstreamRegistryConfig(
            type=UpstreamType.BASIC,
            endpoint_url=upstream_server.make_url(""),
            project="testproject",
            basic_username="testuser",
            basic_password="testpassword",
        )
        upstream_client = UpstreamV2ApiClient(config=config)
        await upstream_client.__aenter__()

        async def handle(request: Request) -> StreamResponse:
            return await upstream_client.proxy_request(request)

        proxy_app = Application()
        proxy_app.router.add_route(
            "*",
            r"/v2/{repo:.+}/{path_suffix:(tags|manifests|blobs)/.*}",
            handle,
        )

        async def close_upstream(app: Application) -> None:
            await upstream_client.aclose()

        proxy_app.on_cleanup.append(lambda app: close_upstream(app))
        return await aiohttp_client(proxy_app)

    async def test_client_cookie_not_forwarded_to_upstream(
        self, proxy_client: object, upstream_handler: _UpstreamHandler
    ) -> None:
        resp = await proxy_client.get(  # type: ignore[attr-defined]
            "/v2/org/proj/img/manifests/latest",
            headers={"Cookie": "sid=leaked-harbor-session"},
        )
        assert resp.status == 200
        assert upstream_handler.received_cookie_headers == []

    async def test_upstream_set_cookie_not_returned_to_client(
        self, proxy_client: object, upstream_handler: _UpstreamHandler
    ) -> None:
        resp = await proxy_client.get(  # type: ignore[attr-defined]
            "/v2/org/proj/img/manifests/latest"
        )
        assert resp.status == 200
        assert resp.headers.getall("Set-Cookie", []) == []
