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
def upstream_project() -> str:
    return "testproject"


class _TestUpstreamHandler:
    def __init__(self, upstream_project: str) -> None:
        self._project = upstream_project
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
            except ValueError as exc:
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
                ) from exc
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
            except ValueError as exc:
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
                ) from exc
        tags = self.tags[start_index : start_index + number]
        response_headers: dict[str, str] = {}
        if self.tags[start_index + number :]:
            next_url = (self.base_url / "v2" / repo / "tags/list").with_query(
                {"n": str(number), "last": tags[-1]}
            )
            response_headers[LINK] = f'<{next_url!s}>; rel="next"'

        return json_response({"name": repo, "tags": tags}, headers=response_headers)


@pytest.fixture
def handler(upstream_project: str) -> _TestUpstreamHandler:
    return _TestUpstreamHandler(upstream_project)


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
def config(upstream: URL, auth_config: AuthConfig, upstream_project: str) -> Config:
    upstream_registry = UpstreamRegistryConfig(
        type=UpstreamType.BASIC,
        endpoint_url=upstream,
        project=upstream_project,
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
        org: str,
        project: str,
    ) -> None:
        app = await create_app(config)
        client = await aiohttp_client(app)
        user = await regular_user_factory()
        params = {"org": org, "project": project}
        async with client.get(
            "/v2/_catalog", auth=user.to_basic_auth(), params=params
        ) as resp:
            assert resp.status == HTTPOk.status_code, await resp.text()
            payload = await resp.json()
            assert payload == {"repositories": []}

    async def test_catalog__only_one_and_matching(
        self,
        config: Config,
        regular_user_factory: Callable[[], Awaitable[_User]],
        aiohttp_client: _TestClientFactory,
        handler: _TestUpstreamHandler,
        org: str,
        project: str,
    ) -> None:
        app = await create_app(config)
        client = await aiohttp_client(app)
        user = await regular_user_factory()

        handler.images = [f"{org}/{project}/test"]
        params = {"org": org, "project": project}
        async with client.get(
            "/v2/_catalog", auth=user.to_basic_auth(), params=params
        ) as resp:
            assert resp.status == HTTPOk.status_code, await resp.text()
            payload = await resp.json()
            assert payload == {"repositories": [f"{org}/{project}/test"]}

    async def test_catalog__last_not_found(
        self,
        config: Config,
        regular_user_factory: Callable[[], Awaitable[_User]],
        aiohttp_client: _TestClientFactory,
        handler: _TestUpstreamHandler,
        org: str,
        project: str,
    ) -> None:
        app = await create_app(config)
        client = await aiohttp_client(app)
        user = await regular_user_factory()

        async with client.get(
            "/v2/_catalog",
            auth=user.to_basic_auth(),
            params={
                "last": f"{org}/{project}/whatever",
                "org": org,
                "project": project,
            },
        ) as resp:
            assert resp.status == HTTPNotFound.status_code, await resp.text()
            payload = await resp.json()
            assert payload == {
                "errors": [
                    {
                        "code": "NAME_UNKNOWN",
                        "message": f"'{org}/{project}/whatever' not found",
                        "detail": f"'{org}/{project}/whatever' not found",
                    }
                ]
            }

    @pytest.mark.parametrize(
        ("number", "replace_max"), list(itertools.product(range(1, 10), (True, False)))
    )
    async def test_catalog__some_at_a_time(
        self,
        config: Config,
        regular_user_factory: Callable[[], Awaitable[_User]],
        aiohttp_client: _TestClientFactory,
        handler: _TestUpstreamHandler,
        number: int,
        replace_max: bool,
        org: str,
        project: str,
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

        expected = [f"{org}/{project}/test{i}" for i in range(1, 10)]
        handler.images = (
            [f"aaaa{i}" for i in range(1, 10)]
            + expected
            + [f"zzzz{i}" for i in range(1, 10)]
        )

        result: list[str] = []
        url = client.server.make_url("/") / "v2/_catalog"
        while url:
            async with client.session.get(
                url,
                auth=user.to_basic_auth(),
                params={"n": str(number), "org": org, "project": project},
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
        org: str,
        project: str,
    ) -> None:
        app = await create_app(config)
        client = await aiohttp_client(app)
        user = await regular_user_factory()
        repo = f"{org}/{project}/test"
        handler.images = [repo]
        handler.tags = ["alpha", "beta", "gamma"]

        async with client.get(
            f"/v2/{repo}/tags/list",
            auth=user.to_basic_auth(),
            params={"org": org, "project": project},
        ) as resp:
            assert resp.status == HTTPOk.status_code, await resp.text()
            payload = await resp.json()
            assert payload == {"name": repo, "tags": handler.tags}

    @pytest.mark.parametrize("number", range(1, 10))
    async def test_tags_list__some_at_a_time(
        self,
        config: Config,
        regular_user_factory: Callable[[], Awaitable[_User]],
        aiohttp_client: _TestClientFactory,
        handler: _TestUpstreamHandler,
        number: int,
        org: str,
        project: str,
    ) -> None:
        app = await create_app(config)
        client = await aiohttp_client(app)
        user = await regular_user_factory()
        repo = f"{org}/{project}/test"
        handler.images = [repo]
        handler.tags = [f"tag{i}" for i in range(1, 10)]

        result: list[str] = []
        url = client.server.make_url("/") / f"v2/{repo}/tags/list"
        while url:
            async with client.session.get(
                url,
                auth=user.to_basic_auth(),
                params={"n": str(number), "org": org, "project": project},
            ) as resp:
                assert resp.status == HTTPOk.status_code, await resp.text()
                payload = await resp.json()
                assert payload["name"] == repo, payload
                result.extend(payload["tags"])
                url = resp.links.getone("next", {}).get("url")  # type: ignore

        assert result == handler.tags
