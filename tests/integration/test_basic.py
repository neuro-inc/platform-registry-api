import itertools
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import replace

import aiohttp.web
import pytest
from aiohttp import BasicAuth, hdrs, web
from aiohttp.hdrs import LINK
from aiohttp.test_utils import unused_port
from aiohttp.web import (
    Application,
    HTTPNotFound,
    HTTPOk,
    Request,
    Response,
    json_response,
)
from yarl import URL

from platform_registry_api.api import create_app
from platform_registry_api.config import (
    AuthConfig,
    Config,
    ServerConfig,
    UpstreamRegistryConfig,
    UpstreamType,
)

from tests import _TestClientFactory
from tests.integration.conftest import _User


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
        self.images: list[str] = []
        self.tags: list[str] = []
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
                if not last_repo.startswith(self._project + "/"):
                    raise ValueError
                last_repo = last_repo[len(self._project + "/") :]
                start_index = self.images.index(last_repo) + 1
            except ValueError:
                raise HTTPNotFound(
                    text=json.dumps(
                        {
                            "errors": [
                                {
                                    "code": "NAME_UNKNOWN",
                                    "message": f"{last_repo!r} not found",
                                    "detail": f"{last_repo!r} not found",
                                }
                            ]
                        }
                    )
                )
        images = self.images[start_index : start_index + number]
        response_headers: dict[str, str] = {}
        images = [f"{self._project}/{image}" for image in images]
        if self.images[start_index + number :]:
            next_url = (self.base_url / "v2/_catalog").with_query(
                {"n": str(number), "last": images[-1]}
            )
            response_headers[LINK] = f'<{next_url!s}>; rel="next"'

        return json_response({"repositories": images}, headers=response_headers)

    async def handle_repo_tags_list(self, request: Request) -> Response:
        auth_header_value = request.headers[hdrs.AUTHORIZATION]
        assert BasicAuth.decode(auth_header_value) == BasicAuth(
            login="testuser", password="testpassword"
        )
        repo = request.match_info["repo"]
        if (
            not repo.startswith(self._project + "/")
            or repo[len(self._project + "/") :] not in self.images
        ):
            raise HTTPNotFound(
                text=json.dumps(
                    {
                        "errors": [
                            {
                                "code": "NAME_UNKNOWN",
                                "message": f"The repository with name {repo!r} "
                                "does not exist",
                            }
                        ]
                    }
                )
            )
        number = int(request.query.get("n", 10))
        last_tag = request.query.get("last", "")
        start_index = 0
        if last_tag:
            try:
                start_index = self.tags.index(last_tag) + 1
            except ValueError:
                raise HTTPNotFound(
                    text=json.dumps(
                        {
                            "errors": [
                                {
                                    "code": "NAME_UNKNOWN",
                                    "message": f"Tag {last_tag!r} not found",
                                    "detail": f"Tag {last_tag!r} not found",
                                }
                            ]
                        }
                    )
                )
        tags = self.tags[start_index : start_index + number]
        response_headers: dict[str, str] = {}
        if self.tags[start_index + number :]:
            next_url = (self.base_url / "v2" / repo / "tags/list").with_query(
                {"n": str(number), "last": tags[-1]}
            )
            response_headers[LINK] = f'<{next_url!s}>; rel="next"'

        return json_response({"name": repo, "tags": tags}, headers=response_headers)


@pytest.fixture
def handler(project: str) -> _TestUpstreamHandler:
    return _TestUpstreamHandler(project)


@pytest.fixture
async def upstream(handler: _TestUpstreamHandler) -> AsyncIterator[URL]:
    app = Application()
    app.add_routes(
        [
            web.get("/v2/_catalog", handler.handle_catalog),
            web.get(r"/v2/{repo:.+}/tags/list", handler.handle_repo_tags_list),
        ]
    )

    async with create_local_app_server(app, port=unused_port()) as url:
        handler.base_url = url
        yield url


@pytest.fixture
def auth_config(admin_token: str) -> AuthConfig:
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
    return Config(
        server=ServerConfig(),
        upstream_registry=upstream_registry,
        auth=auth_config,
        cluster_name="test-cluster",
    )


class TestBasicUpstream:
    async def test_catalog(
        self,
        config: Config,
        regular_user_factory: Callable[[], Awaitable[_User]],
        aiohttp_client: _TestClientFactory,
        handler: _TestUpstreamHandler,
    ) -> None:
        app = await create_app(config)
        client = await aiohttp_client(app)
        user = await regular_user_factory()

        async with client.get("/v2/_catalog", auth=user.to_basic_auth()) as resp:
            assert resp.status == HTTPOk.status_code, await resp.text()
            payload = await resp.json()
            assert payload == {"repositories": []}

    async def test_catalog__only_one_and_matching(
        self,
        config: Config,
        regular_user_factory: Callable[[], Awaitable[_User]],
        aiohttp_client: _TestClientFactory,
        handler: _TestUpstreamHandler,
    ) -> None:
        app = await create_app(config)
        client = await aiohttp_client(app)
        user = await regular_user_factory()

        handler.images = [user.name + "/test"]

        async with client.get("/v2/_catalog", auth=user.to_basic_auth()) as resp:
            assert resp.status == HTTPOk.status_code, await resp.text()
            payload = await resp.json()
            assert payload == {"repositories": [user.name + "/test"]}

    async def test_catalog__last_not_found(
        self,
        config: Config,
        regular_user_factory: Callable[[], Awaitable[_User]],
        aiohttp_client: _TestClientFactory,
        handler: _TestUpstreamHandler,
    ) -> None:
        app = await create_app(config)
        client = await aiohttp_client(app)
        user = await regular_user_factory()

        async with client.get(
            "/v2/_catalog",
            auth=user.to_basic_auth(),
            params={"last": f"{user.name}/whatever"},
        ) as resp:
            assert resp.status == HTTPNotFound.status_code, await resp.text()
            payload = await resp.json()
            assert payload == {
                "errors": [
                    {
                        "code": "NAME_UNKNOWN",
                        "message": f"'{user.name}/whatever' not found",
                        "detail": f"'{user.name}/whatever' not found",
                    }
                ]
            }

    async def test_catalog__multiple_users(
        self,
        config: Config,
        regular_user_factory: Callable[[], Awaitable[_User]],
        aiohttp_client: _TestClientFactory,
        handler: _TestUpstreamHandler,
    ) -> None:
        app = await create_app(config)
        client = await aiohttp_client(app)
        user1 = await regular_user_factory()
        user2 = await regular_user_factory()
        user3 = await regular_user_factory()

        handler.images = sorted(
            [
                user2.name + "/test2",
                user1.name + "/test1",
                user1.name + "/test4",
                user3.name + "/test3",
            ]
        )

        async with client.get(
            "/v2/_catalog", auth=user1.to_basic_auth(), params={"n": "1"}
        ) as resp:
            assert resp.status == HTTPOk.status_code, await resp.text()
            last_token = URL(
                resp.links.getone("next", {}).get("url")  # type: ignore
            ).query.get("last")

        async with client.get(
            "/v2/_catalog",
            auth=user1.to_basic_auth(),
            params={"n": "1", "last": last_token},
        ) as resp:
            assert resp.status == HTTPOk.status_code, await resp.text()
            payload = await resp.json()
            assert payload == {"repositories": [user1.name + "/test4"]}

    async def test_catalog__number(
        self,
        config: Config,
        regular_user_factory: Callable[[], Awaitable[_User]],
        aiohttp_client: _TestClientFactory,
        handler: _TestUpstreamHandler,
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

    @pytest.mark.parametrize(
        "number, replace_max", list(itertools.product(range(1, 10), (True, False)))
    )
    async def test_catalog__some_at_a_time(
        self,
        config: Config,
        regular_user_factory: Callable[[], Awaitable[_User]],
        aiohttp_client: _TestClientFactory,
        handler: _TestUpstreamHandler,
        number: int,
        replace_max: bool,
    ) -> None:
        if replace_max:
            config = replace(
                config,
                upstream_registry=replace(
                    config.upstream_registry, max_catalog_entries=number
                ),
            )
        app = await create_app(config)
        client = await aiohttp_client(app)
        user = await regular_user_factory()

        expected = [user.name + f"/test{i}" for i in range(1, 10)]
        handler.images = (
            [f"aaaa{i}" for i in range(1, 10)]
            + expected
            + [f"zzzz{i}" for i in range(1, 10)]
        )

        result: list[str] = []
        url = client.server.make_url("/") / "v2/_catalog"
        while url:
            async with client.session.get(
                url, auth=user.to_basic_auth(), params={"n": str(number)}
            ) as resp:
                assert resp.status == HTTPOk.status_code, await resp.text()
                payload = await resp.json()
                result.extend(payload["repositories"])
                url = resp.links.getone("next", {}).get("url")  # type: ignore

        assert result == expected

    async def test_tags_list(
        self,
        config: Config,
        regular_user_factory: Callable[[], Awaitable[_User]],
        aiohttp_client: _TestClientFactory,
        handler: _TestUpstreamHandler,
    ) -> None:
        app = await create_app(config)
        client = await aiohttp_client(app)
        user = await regular_user_factory()
        repo = user.name + "/test"
        handler.images = [repo]
        handler.tags = ["alpha", "beta", "gamma"]

        async with client.get(
            f"/v2/{repo}/tags/list", auth=user.to_basic_auth()
        ) as resp:
            assert resp.status == HTTPOk.status_code, await resp.text()
            payload = await resp.json()
            assert payload == {"name": repo, "tags": handler.tags}

    async def test_tags_list__last_not_found(
        self,
        config: Config,
        regular_user_factory: Callable[[], Awaitable[_User]],
        aiohttp_client: _TestClientFactory,
        handler: _TestUpstreamHandler,
    ) -> None:
        app = await create_app(config)
        client = await aiohttp_client(app)
        user = await regular_user_factory()
        repo = user.name + "/test"
        handler.images = [repo]

        async with client.get(
            f"/v2/{repo}/tags/list",
            auth=user.to_basic_auth(),
            params={"last": "whatever"},
        ) as resp:
            assert resp.status == HTTPNotFound.status_code, await resp.text()
            payload = await resp.json()
            assert payload == {
                "errors": [
                    {
                        "code": "NAME_UNKNOWN",
                        "message": "Tag 'whatever' not found",
                        "detail": "Tag 'whatever' not found",
                    }
                ]
            }

    async def test_tags_list__number(
        self,
        config: Config,
        regular_user_factory: Callable[[], Awaitable[_User]],
        aiohttp_client: _TestClientFactory,
        handler: _TestUpstreamHandler,
    ) -> None:
        app = await create_app(config)
        client = await aiohttp_client(app)
        user = await regular_user_factory()
        repo = user.name + "/test"
        handler.images = [repo]
        handler.tags = [f"tag{i}" for i in range(1, 10)]

        for i in range(1, 9):
            async with client.get(
                f"/v2/{repo}/tags/list", auth=user.to_basic_auth(), params={"n": str(i)}
            ) as resp:
                assert resp.status == HTTPOk.status_code, await resp.text()
                payload = await resp.json()
                assert payload == {"name": repo, "tags": handler.tags[:i]}

    @pytest.mark.parametrize("number", range(1, 10))
    async def test_tags_list__some_at_a_time(
        self,
        config: Config,
        regular_user_factory: Callable[[], Awaitable[_User]],
        aiohttp_client: _TestClientFactory,
        handler: _TestUpstreamHandler,
        number: int,
    ) -> None:
        app = await create_app(config)
        client = await aiohttp_client(app)
        user = await regular_user_factory()
        repo = user.name + "/test"
        handler.images = [repo]
        handler.tags = [f"tag{i}" for i in range(1, 10)]

        result: list[str] = []
        url = client.server.make_url("/") / f"v2/{repo}/tags/list"
        while url:
            async with client.session.get(
                url, auth=user.to_basic_auth(), params={"n": str(number)}
            ) as resp:
                assert resp.status == HTTPOk.status_code, await resp.text()
                payload = await resp.json()
                assert payload["name"] == repo, payload
                result.extend(payload["tags"])
                url = resp.links.getone("next", {}).get("url")  # type: ignore

        assert result == handler.tags
