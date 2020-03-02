from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable

import aiohttp.web
import pytest
from aiohttp import BasicAuth, hdrs, web
from aiohttp.test_utils import unused_port as _unused_port
from aiohttp.web import Application, HTTPOk, Request, Response, json_response
from yarl import URL

from platform_registry_api.api import create_app
from platform_registry_api.config import (
    AuthConfig,
    Config,
    EnvironConfigFactory,
    ServerConfig,
    UpstreamRegistryConfig,
    UpstreamType,
    ZipkinConfig,
)


pytestmark = pytest.mark.asyncio


@pytest.fixture
def unused_port_factory() -> Callable[[], int]:
    return _unused_port


@pytest.fixture
async def raw_client() -> AsyncIterator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession() as session:
        yield session


@asynccontextmanager
async def create_local_app_server(
    app: aiohttp.web.Application, host: str = "0.0.0.0", port: int = 8080
) -> AsyncIterator[URL]:
    runner = aiohttp.web.AppRunner(app)
    try:
        await runner.setup()
        site = aiohttp.web.TCPSite(runner, host, port)
        await site.start()
        yield URL(site.name)
    finally:
        await runner.shutdown()
        await runner.cleanup()


class _TestUpstreamHandler:
    async def handle_catalog(self, request: Request) -> Response:
        auth_header_value = request.headers[hdrs.AUTHORIZATION]
        assert BasicAuth.decode(auth_header_value) == BasicAuth(
            login="testuser", password="testpassword"
        )
        return json_response({"repositories": []})


@pytest.fixture
def handler() -> _TestUpstreamHandler:
    return _TestUpstreamHandler()


@pytest.fixture
async def upstream(
    handler: _TestUpstreamHandler, unused_port_factory: Callable[[], int]
) -> AsyncIterator[URL]:
    app = Application()
    app.add_routes([web.get("/v2/_catalog", handler.handle_catalog)])

    async with create_local_app_server(app, port=unused_port_factory()) as url:
        yield url


@pytest.fixture
def auth_config(in_docker: bool, admin_token: str) -> AuthConfig:
    if in_docker:
        return EnvironConfigFactory().create().auth
    return AuthConfig(
        server_endpoint_url=URL("http://localhost:5003"), service_token=admin_token
    )


@pytest.fixture
def config(upstream: URL, auth_config: AuthConfig) -> Config:
    upstream_registry = UpstreamRegistryConfig(
        type=UpstreamType.BASIC,
        endpoint_url=upstream,
        project="testproject",
        basic_username="testuser",
        basic_password="testpassword",
    )
    zipkin_config = ZipkinConfig(URL("http://zipkin:9411"), 0)
    return Config(
        server=ServerConfig(),
        upstream_registry=upstream_registry,
        auth=auth_config,
        zipkin=zipkin_config,
        cluster_name="test-cluster",
    )


class TestBasicUpstream:
    async def test_catalog(self, config, regular_user_factory, aiohttp_client) -> None:
        app = await create_app(config)
        client = await aiohttp_client(app)
        user = await regular_user_factory()

        async with client.get("/v2/_catalog", auth=user.to_basic_auth()) as resp:
            assert resp.status == HTTPOk.status_code, await resp.text()
            payload = await resp.json()
            assert payload == {"repositories": []}
