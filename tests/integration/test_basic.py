from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable, Dict, List

import aiohttp.web
import pytest
from aiohttp import BasicAuth, hdrs, web
from aiohttp.hdrs import LINK
from aiohttp.test_utils import unused_port
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


@pytest.fixture
def project() -> str:
    return "testproject"


class _TestUpstreamHandler:
    def __init__(self, project: str) -> None:
        self._project = project
        self.images: List[str] = []
        self.base_url = URL()

    async def handle_catalog(self, request: Request) -> Response:
        auth_header_value = request.headers[hdrs.AUTHORIZATION]
        assert BasicAuth.decode(auth_header_value) == BasicAuth(
            login="testuser", password="testpassword"
        )
        number = int(request.query.get("n", 10))
        last_repo = request.query.get("last", "")
        start_index = 0
        if last_repo:
            try:
                start_index = self.images.index(last_repo) + 1
            except ValueError:
                pass
        images = self.images[start_index : start_index + number]
        response_headers: Dict[str, str] = {}
        images = [f"{self._project}/{image}" for image in images]
        if images and self.images[start_index + number :]:
            next_url = (self.base_url / "v2/_catalog").with_query(
                {"n": str(number), "last": images[-1]}
            )
            response_headers[LINK] = f'<{next_url!s}>; rel="next"'

        return json_response({"repositories": images}, headers=response_headers)


@pytest.fixture
def handler(project: str) -> _TestUpstreamHandler:
    return _TestUpstreamHandler(project)


@pytest.fixture
async def upstream(handler: _TestUpstreamHandler) -> AsyncIterator[URL]:
    app = Application()
    app.add_routes([web.get("/v2/_catalog", handler.handle_catalog)])

    async with create_local_app_server(app, port=unused_port()) as url:
        handler.base_url = url
        yield url


@pytest.fixture
def auth_config(in_docker: bool, admin_token: str) -> AuthConfig:
    if in_docker:
        return EnvironConfigFactory().create().auth
    return AuthConfig(
        server_endpoint_url=URL("http://localhost:5003"), service_token=admin_token
    )


@pytest.fixture
def config(upstream: URL, auth_config: AuthConfig, project: str) -> Config:
    upstream_registry = UpstreamRegistryConfig(
        type=UpstreamType.BASIC,
        endpoint_url=upstream,
        project=project,
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
    async def test_catalog(
        self, config, regular_user_factory, aiohttp_client, handler
    ) -> None:
        app = await create_app(config)
        client = await aiohttp_client(app)
        user = await regular_user_factory()

        async with client.get("/v2/_catalog", auth=user.to_basic_auth()) as resp:
            assert resp.status == HTTPOk.status_code, await resp.text()
            payload = await resp.json()
            assert payload == {"repositories": []}

    async def test_catalog__only_one_and_matching(
        self, config, regular_user_factory, aiohttp_client, handler
    ) -> None:
        app = await create_app(config)
        client = await aiohttp_client(app)
        user = await regular_user_factory()

        handler.images = [user.name + "/test"]

        async with client.get("/v2/_catalog", auth=user.to_basic_auth()) as resp:
            assert resp.status == HTTPOk.status_code, await resp.text()
            payload = await resp.json()
            assert payload == {"repositories": [user.name + "/test"]}

    async def test_catalog__multiple_users(
        self, config, regular_user_factory, aiohttp_client, handler
    ) -> None:
        app = await create_app(config)
        client = await aiohttp_client(app)
        user1 = await regular_user_factory()
        user2 = await regular_user_factory()
        user3 = await regular_user_factory()

        handler.images = [
            user2.name + "/test2",
            user1.name + "/test1",
            user3.name + "/test3",
        ]

        async with client.get("/v2/_catalog", auth=user1.to_basic_auth()) as resp:
            assert resp.status == HTTPOk.status_code, await resp.text()
            payload = await resp.json()
            assert payload == {"repositories": [user1.name + "/test1"]}

    async def test_catalog__number(
        self, config, regular_user_factory, aiohttp_client, handler
    ) -> None:
        app = await create_app(config)
        client = await aiohttp_client(app)
        user = await regular_user_factory()

        handler.images = [user.name + f"/test{i}" for i in range(1, 10)]

        for i in range(1, 9):
            async with client.get(
                "/v2/_catalog", auth=user.to_basic_auth(), params={"n": str(i)}
            ) as resp:
                assert resp.status == HTTPOk.status_code, await resp.text()
                payload = await resp.json()
                assert payload == {"repositories": handler.images[:i]}

    @pytest.mark.parametrize("number", list(range(1, 10)))
    async def test_catalog__some_at_a_time(
        self, config, regular_user_factory, aiohttp_client, handler, number: int
    ) -> None:
        app = await create_app(config)
        client = await aiohttp_client(app)
        user = await regular_user_factory()

        handler.images = [user.name + f"/test{i}" for i in range(1, 10)]

        result: List[str] = []
        url = client.server.make_url("/") / "v2/_catalog"
        while url:
            async with client.session.get(
                url, auth=user.to_basic_auth(), params={"n": str(number)}
            ) as resp:
                assert resp.status == HTTPOk.status_code, await resp.text()
                payload = await resp.json()
                result.extend(payload["repositories"])
                url = resp.links.getone("next", {}).get("url")

        assert result == handler.images
