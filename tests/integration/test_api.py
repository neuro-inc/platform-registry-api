from typing import Awaitable, Callable

import pytest
from yarl import URL

from platform_registry_api.api import create_app
from platform_registry_api.config import (
    AuthConfig,
    Config,
    EnvironConfigFactory,
    ServerConfig,
    UpstreamRegistryConfig,
)
from tests import _TestClientFactory
from tests.integration.conftest import _User


@pytest.fixture
def config(in_docker: bool, admin_token: str, cluster_name: str) -> Config:
    if in_docker:
        return EnvironConfigFactory().create()

    upstream_registry = UpstreamRegistryConfig(
        endpoint_url=URL("http://localhost:5002"),
        project="testproject",
        token_endpoint_url=URL("http://localhost:5001/auth"),
        token_service="upstream",
        token_endpoint_username="testuser",
        token_endpoint_password="testpassword",
    )
    auth = AuthConfig(
        server_endpoint_url=URL("http://localhost:5003"), service_token=admin_token
    )
    return Config(
        server=ServerConfig(),
        upstream_registry=upstream_registry,
        auth=auth,
        cluster_name=cluster_name,
    )


class TestV2Api:
    @pytest.mark.asyncio
    async def test_unauthorized(
        self, aiohttp_client: _TestClientFactory, config: Config
    ) -> None:
        app = await create_app(config)
        client = await aiohttp_client(app)
        async with client.get("/v2/") as resp:
            assert resp.status == 401
            assert resp.headers["WWW-Authenticate"] == ('Basic realm="Docker Registry"')

    @pytest.mark.asyncio
    async def test_invalid_credentials(
        self, aiohttp_client: _TestClientFactory, config: Config
    ) -> None:
        app = await create_app(config)
        client = await aiohttp_client(app)
        headers = {"Authorization": "Basic ab"}
        async with client.get("/v2/", headers=headers) as resp:
            assert resp.status == 400

    @pytest.mark.asyncio
    async def test_version_check(
        self,
        aiohttp_client: _TestClientFactory,
        config: Config,
        regular_user_factory: Callable[[], Awaitable[_User]],
    ) -> None:
        user = await regular_user_factory()
        app = await create_app(config)
        client = await aiohttp_client(app)
        auth = user.to_basic_auth()
        async with client.get("/v2/", auth=auth) as resp:
            assert resp.status == 200

    async def test_version_check_includes_service_version(
        self,
        aiohttp_client: _TestClientFactory,
        config: Config,
        regular_user_factory: Callable[[], Awaitable[_User]],
    ) -> None:
        user = await regular_user_factory()
        app = await create_app(config)
        client = await aiohttp_client(app)
        auth = user.to_basic_auth()
        async with client.get("/v2/", auth=auth) as resp:
            assert resp.status == 200
            assert "platform-registry-api" in resp.headers["X-Service-Version"]

    @pytest.mark.asyncio
    async def test_catalog(
        self,
        aiohttp_client: _TestClientFactory,
        config: Config,
        regular_user_factory: Callable[[], Awaitable[_User]],
    ) -> None:
        user = await regular_user_factory()
        app = await create_app(config)
        client = await aiohttp_client(app)
        auth = user.to_basic_auth()
        url = "/v2/_catalog"
        async with client.get(url, auth=auth) as resp:
            assert resp.status == 200, await resp.text()
            data = await resp.json()
            assert "repositories" in data
            assert isinstance(data["repositories"], list)

    @pytest.mark.asyncio
    async def test_catalog__no_auth(
        self, aiohttp_client: _TestClientFactory, config: Config
    ) -> None:
        app = await create_app(config)
        client = await aiohttp_client(app)
        url = "/v2/_catalog"
        async with client.get(url) as resp:
            assert resp.status == 401, await resp.text()

    @pytest.mark.asyncio
    async def test_repo_unauthorized(
        self, aiohttp_client: _TestClientFactory, config: Config
    ) -> None:
        app = await create_app(config)
        client = await aiohttp_client(app)
        async with client.get("/v2/neuromation/unknown/tags/list") as resp:
            assert resp.status == 401
            assert resp.headers["WWW-Authenticate"] == ('Basic realm="Docker Registry"')

    @pytest.mark.asyncio
    async def test_unknown_repo(
        self,
        aiohttp_client: _TestClientFactory,
        config: Config,
        regular_user_factory: Callable[[], Awaitable[_User]],
    ) -> None:
        user = await regular_user_factory()
        app = await create_app(config)
        client = await aiohttp_client(app)
        auth = user.to_basic_auth()
        url = f"/v2/{user.name}/unknown/tags/list"
        async with client.get(url, auth=auth) as resp:
            assert resp.status == 404
            payload = await resp.json()
            assert payload == {
                "errors": [
                    {
                        "code": "NAME_UNKNOWN",
                        "detail": {"name": f"{user.name}/unknown"},
                        "message": "repository name not known to registry",
                    }
                ]
            }

    @pytest.mark.asyncio
    async def test_cross_repo_blob_mount(
        self,
        aiohttp_client: _TestClientFactory,
        config: Config,
        regular_user_factory: Callable[[], Awaitable[_User]],
    ) -> None:
        user = await regular_user_factory()
        app = await create_app(config)
        client = await aiohttp_client(app)
        auth = user.to_basic_auth()
        url = f"/v2/{user.name}/unknown/blobs/uploads/?from={user.name}/unknown2"
        async with client.post(url, auth=auth) as resp:
            assert resp.status == 202, await resp.text()

    @pytest.mark.asyncio
    async def test_cross_repo_blob_mount_forbidden(
        self,
        aiohttp_client: _TestClientFactory,
        config: Config,
        regular_user_factory: Callable[[], Awaitable[_User]],
    ) -> None:
        user = await regular_user_factory()
        app = await create_app(config)
        client = await aiohttp_client(app)
        auth = user.to_basic_auth()
        url = f"/v2/{user.name}/unknown/blobs/uploads/?from={user.name}-other/unknown"
        async with client.post(url, auth=auth) as resp:
            assert resp.status == 403

    @pytest.mark.asyncio
    async def test_x_forwarded_proto(
        self,
        aiohttp_client: _TestClientFactory,
        config: Config,
        regular_user_factory: Callable[[], Awaitable[_User]],
    ) -> None:
        user = await regular_user_factory()
        app = await create_app(config)
        client = await aiohttp_client(app)
        auth = user.to_basic_auth()
        headers = {"X-Forwarded-Proto": "https"}
        url = f"/v2/{user.name}/image/blobs/uploads/"
        async with client.post(url, auth=auth, headers=headers) as resp:
            assert resp.status == 202
            location_url = URL(resp.headers["Location"])
            assert location_url.scheme == "https"
