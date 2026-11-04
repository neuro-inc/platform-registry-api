from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import pytest
from aiohttp.test_utils import TestClient as _TestClient, TestServer as _TestServer
from aiohttp.web import Application, Request, Response
from aiohttp_security import (
    AbstractAuthorizationPolicy,
    AbstractIdentityPolicy,
    setup as setup_security,
)
from neuro_auth_client import Permission
from yarl import URL

from platform_registry_api.api import UPSTREAM_CLIENT, V2Handler
from platform_registry_api.config import (
    AdminClientConfig,
    AuthConfig,
    Config,
    ServerConfig,
    UpstreamRegistryConfig,
    UpstreamType,
)
from platform_registry_api.upstream_client import UpstreamV2ApiClient
from tests import _TestClientFactory


_TestServerFactory = Callable[[Application], Awaitable[_TestServer]]

UPLOAD_URL = "/v2/org/project/img/blobs/uploads/?mount=sha256:abc&from=org/other/img"


class _IdentityPolicy(AbstractIdentityPolicy):
    async def identify(self, request: Request) -> str | None:
        return "user"

    async def remember(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def forget(self, *args: Any, **kwargs: Any) -> None:
        pass


class _AuthorizationPolicy(AbstractAuthorizationPolicy):
    def __init__(self, allowed: set[tuple[str, str]]) -> None:
        self._allowed = allowed

    async def authorized_userid(self, identity: str) -> str | None:
        return identity

    async def permits(
        self, identity: str | None, permission: Any, context: Any = None
    ) -> bool:
        permissions: list[Permission] = context
        return all((p.uri, p.action) in self._allowed for p in permissions)


class _Upstream:
    def __init__(self) -> None:
        self.queries: list[dict[str, str]] = []

    async def handle(self, request: Request) -> Response:
        self.queries.append(dict(request.query))
        return Response(status=202, headers={"Location": "/v2/upload/uuid"})


class TestBlobMount:
    @pytest.fixture
    def upstream(self) -> _Upstream:
        return _Upstream()

    @pytest.fixture
    async def client_factory(
        self,
        aiohttp_server: _TestServerFactory,
        aiohttp_client: _TestClientFactory,
        upstream: _Upstream,
    ) -> AsyncIterator[
        Callable[[set[tuple[str, str]]], Awaitable[_TestClient[Request, Application]]]
    ]:
        upstream_app = Application()
        upstream_app.router.add_route("*", "/v2/{tail:.+}", upstream.handle)
        upstream_server = await aiohttp_server(upstream_app)
        config = Config(
            server=ServerConfig(),
            upstream_registry=UpstreamRegistryConfig(
                type=UpstreamType.BASIC,
                endpoint_url=upstream_server.make_url(""),
                project="testproject",
                basic_username="testuser",
                basic_password="testpassword",
            ),
            auth=AuthConfig(server_endpoint_url=None, service_token="token"),
            admin=AdminClientConfig(endpoint_url=None, token="token"),
            cluster_name="test-cluster",
        )

        async with UpstreamV2ApiClient(config=config.upstream_registry) as client:

            async def _factory(
                allowed: set[tuple[str, str]],
            ) -> _TestClient[Request, Application]:
                app = Application()
                setup_security(app, _IdentityPolicy(), _AuthorizationPolicy(allowed))
                v2_app = Application()
                V2Handler(app=v2_app, config=config).register(v2_app)
                v2_app[UPSTREAM_CLIENT] = client
                app.add_subapp("/v2", v2_app)
                return await aiohttp_client(app)

            yield _factory

    async def test_mount_from_readable_repo(
        self,
        client_factory: Callable[
            [set[tuple[str, str]]], Awaitable[_TestClient[Request, Application]]
        ],
        upstream: _Upstream,
    ) -> None:
        client = await client_factory(
            {
                ("image://test-cluster/org/project/img", "write"),
                ("image://test-cluster/org/other/img", "read"),
            }
        )

        async with client.post(UPLOAD_URL) as resp:
            assert resp.status == 202

        assert upstream.queries == [
            {"mount": "sha256:abc", "from": "testproject/org/other/img"}
        ]

    async def test_mount_from_unreadable_repo_starts_regular_upload(
        self,
        client_factory: Callable[
            [set[tuple[str, str]]], Awaitable[_TestClient[Request, Application]]
        ],
        upstream: _Upstream,
    ) -> None:
        client = await client_factory(
            {("image://test-cluster/org/project/img", "write")}
        )

        async with client.post(UPLOAD_URL) as resp:
            assert resp.status == 202
            assert URL(resp.headers["Location"]).path == "/v2/upload/uuid"

        assert upstream.queries == [{}]

    async def test_upload_to_unwritable_repo_forbidden(
        self,
        client_factory: Callable[
            [set[tuple[str, str]]], Awaitable[_TestClient[Request, Application]]
        ],
        upstream: _Upstream,
    ) -> None:
        client = await client_factory({("image://test-cluster/org/other/img", "read")})

        async with client.post(UPLOAD_URL) as resp:
            assert resp.status == 403

        assert upstream.queries == []
