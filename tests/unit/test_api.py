import datetime
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Optional

import aiohttp
import pytest
from aiohttp import ClientSession
from aiohttp.hdrs import AUTHORIZATION
from neuro_auth_client.bearer_auth import BearerAuth
from neuro_auth_client.client import ClientSubTreeViewRoot
from yarl import URL

from platform_registry_api.api import (
    OAuthClient,
    OAuthUpstream,
    RepoURL,
    URLFactory,
    V2Handler,
)
from platform_registry_api.config import UpstreamRegistryConfig
from platform_registry_api.helpers import check_image_catalog_permission

_TestServerFactory = Callable[
    [aiohttp.web.Application], Awaitable[aiohttp.test_utils.TestServer]
]


class TestRepoURL:
    @pytest.mark.parametrize(
        "url", (URL("/"), URL("/v2/"), URL("/v2/tags/list"), URL("/v2/blobs/uploads/"))
    )
    def test_from_url_value_error(self, url: URL) -> None:
        with pytest.raises(
            ValueError, match=f"unexpected path in a registry URL: {url}"
        ):
            RepoURL.from_url(url)

    def test_from_url(self) -> None:
        url = URL("https://example.com/v2/name/tags/list?whatever=thatis")
        reg_url = RepoURL.from_url(url)
        assert reg_url == RepoURL(repo="name", url=url)

    def test_from_url_edge_case_1(self) -> None:
        url = URL("/v2/tags/tags/list?whatever=thatis")
        reg_url = RepoURL.from_url(url)
        assert reg_url == RepoURL(repo="tags", url=url)

    def test_from_url_edge_case_2(self) -> None:
        url = URL("/v2/tags/tags/tags/list?whatever=thatis")
        reg_url = RepoURL.from_url(url)
        assert reg_url == RepoURL(repo="tags/tags", url=url)

    def test_from_url_with_cross_repo_blob_mount(self) -> None:
        url = URL(
            "https://example.com/v2/this/img/blobs/uploads/?what=ever&from=another/img"
        )
        reg_url = RepoURL.from_url(url)
        assert reg_url == RepoURL(
            repo="this/img",
            mounted_repo="another/img",
            url=URL(
                "https://example.com/v2/this/img/blobs/uploads/"
                "?what=ever&from=another/img"
            ),
        )

    def test_with_project(self) -> None:
        url = URL("https://example.com/v2/this/img/tags/list?what=ever")
        reg_url = RepoURL.from_url(url).with_project("neuro")
        assert reg_url == RepoURL(
            repo="neuro/this/img",
            url=URL("https://example.com/v2/neuro/this/img/tags/list?what=ever"),
        )

    def test_with_project_and_cross_repo_blob_mount(self) -> None:
        url = URL(
            "https://example.com/v2/this/img/blobs/uploads/?what=ever&from=another/img"
        )
        reg_url = RepoURL.from_url(url).with_project("neuro")
        assert reg_url == RepoURL(
            repo="neuro/this/img",
            mounted_repo="neuro/another/img",
            url=URL(
                "https://example.com/v2/neuro/this/img/blobs/uploads/"
                "?what=ever&from=neuro/another/img"
            ),
        )

    def test_with_repo(self) -> None:
        url = URL("https://example.com/v2/this/image/tags/list?what=ever")
        reg_url = RepoURL.from_url(url).with_repo("another/img")
        assert reg_url == RepoURL(
            repo="another/img",
            url=URL("https://example.com/v2/another/img/tags/list?what=ever"),
        )

    def test_with_origin(self) -> None:
        url = URL("https://example.com/v2/this/image/tags/list?what=ever")
        reg_url = RepoURL.from_url(url).with_origin(URL("http://a.b"))
        assert reg_url == RepoURL(
            repo="this/image", url=URL("http://a.b/v2/this/image/tags/list?what=ever")
        )

    def test_with_origin_relative(self) -> None:
        url = URL("/v2/this/image/tags/list?what=ever")
        reg_url = RepoURL.from_url(url).with_origin(URL("http://a.b"))
        assert reg_url == RepoURL(
            repo="this/image", url=URL("http://a.b/v2/this/image/tags/list?what=ever")
        )

    def test_with_query_no_query(self) -> None:
        url = URL("https://example.com/v2/this/image/tags/list")
        reg_url = RepoURL.from_url(url).with_query({"what": "ever"})
        assert reg_url == RepoURL(
            repo="this/image",
            url=URL("https://example.com/v2/this/image/tags/list?what=ever"),
        )


class TestURLFactory:
    @pytest.fixture
    def url_factory(self) -> URLFactory:
        registry_endpoint_url = URL("http://registry:5000")
        upstream_endpoint_url = URL("http://upstream:5000")
        return URLFactory(
            registry_endpoint_url=registry_endpoint_url,
            upstream_endpoint_url=upstream_endpoint_url,
            upstream_project="upstream/nested",
        )

    def test_create_registry_version_check_url(self, url_factory: URLFactory) -> None:
        assert url_factory.create_registry_version_check_url() == URL(
            "http://upstream:5000/v2/"
        )

    def test_create_upstream_repo_url(self, url_factory: URLFactory) -> None:
        reg_repo_url = RepoURL.from_url(
            URL("http://registry:5000/v2/this/image/tags/list?what=ever")
        )
        up_repo_url = url_factory.create_upstream_repo_url(reg_repo_url)

        expected_url = URL(
            "http://upstream:5000/v2/upstream/nested/this/image/tags/list" "?what=ever"
        )
        assert up_repo_url == RepoURL(
            repo="upstream/nested/this/image", url=expected_url
        )

    def test_create_registry_repo_url(self, url_factory: URLFactory) -> None:
        up_repo_url = RepoURL.from_url(
            URL("http://upstream:5000/v2/upstream/nested/this/image/tags/list?what=")
        )
        reg_repo_url = url_factory.create_registry_repo_url(up_repo_url)

        expected_url = URL("http://registry:5000/v2/this/image/tags/list?what=")
        assert reg_repo_url == RepoURL(repo="this/image", url=expected_url)

    def test_create_registry_repo_url_no_project(self, url_factory: URLFactory) -> None:
        up_repo_url = RepoURL.from_url(
            URL("http://upstream:5000/v2/image/tags/list?what=")
        )
        with pytest.raises(ValueError, match="'image' does not match"):
            url_factory.create_registry_repo_url(up_repo_url)

    def test_create_registry_repo_url_wrong_project(
        self, url_factory: URLFactory
    ) -> None:
        up_repo_url = RepoURL.from_url(
            URL("http://upstream:5000/v2/upstream/image/tags/list?what=")
        )
        with pytest.raises(ValueError, match="'upstream/image' does not match"):
            url_factory.create_registry_repo_url(up_repo_url)


class TestV2Handler:
    def test_filter_images_by_project(self) -> None:
        images_names = [
            "testproject/alice/img1",
            "testproject/alice/img2",
            "testproject2/alice/img3",
        ]
        project = "testproject"
        tree = ClientSubTreeViewRoot._from_json(
            "job",
            {
                "action": "list",
                "children": {"alice": {"action": "manage", "children": {}}},
                "path": "/",
            },
        )
        assert list(V2Handler.filter_images_1_indexed(images_names, tree, project)) == [
            (1, "alice/img1"),
            (2, "alice/img2"),
        ]

    def test_filter_images_by_tree_user_mismatch(self) -> None:
        images_names = [
            "testproject/alice/img1",
            "testproject/alice/img2",
            "testproject/bob/img3",
        ]
        project = "testproject"
        tree = ClientSubTreeViewRoot._from_json(
            "job",
            {
                "action": "list",
                "children": {"alice": {"action": "manage", "children": {}}},
                "path": "/",
            },
        )
        assert list(V2Handler.filter_images_1_indexed(images_names, tree, project)) == [
            (1, "alice/img1"),
            (2, "alice/img2"),
        ]

    def test_filter_images_by_tree_superuser(self) -> None:
        images_names = [
            "testproject/alice/img1",
            "testproject/alice/img2",
            "testproject/bob/img3",
            "testproject/foo/img4",
        ]
        project = "testproject"
        tree = ClientSubTreeViewRoot._from_json(
            "job",
            {
                "action": "manage",
                "children": {"alice": {"action": "manage", "children": {}}},
                "path": "/",
            },
        )
        assert list(V2Handler.filter_images_1_indexed(images_names, tree, project)) == [
            (1, "alice/img1"),
            (2, "alice/img2"),
            (3, "bob/img3"),
            (4, "foo/img4"),
        ]

    def test_filter_images_no_elements(self) -> None:
        images_names: list[str] = []
        project = "testproject"
        tree = ClientSubTreeViewRoot._from_json(
            "job",
            {
                "action": "list",
                "children": {"alice": {"action": "manage", "children": {}}},
                "path": "/",
            },
        )
        assert (
            list(V2Handler.filter_images_1_indexed(images_names, tree, project)) == []
        )

    def test_parse_catalog_repositories_no_key(self) -> None:
        assert V2Handler.parse_catalog_repositories({}) == []

    def test_parse_catalog_repositories_null(self) -> None:
        assert V2Handler.parse_catalog_repositories({"repositories": None}) == []

    def test_parse_catalog_repositories_empty(self) -> None:
        assert V2Handler.parse_catalog_repositories({"repositories": []}) == []

    def test_parse_catalog_repositories(self) -> None:
        assert V2Handler.parse_catalog_repositories(
            {"repositories": ["image:tag"]}
        ) == ["image:tag"]


class TestHelpers_CheckImageCatalogPermission:
    def test_default_permissions(self) -> None:
        # alice checks her own image "alice/img"
        image = "alice/img"
        tree = ClientSubTreeViewRoot._from_json(
            "job",
            {
                "action": "list",
                "children": {"alice": {"action": "manage", "children": {}}},
                "path": "/",
            },
        )
        assert check_image_catalog_permission(image, tree) is True

    def test_another_user_default_permissions__forbidden(self) -> None:
        image = "alice/img"
        tree = ClientSubTreeViewRoot._from_json(
            "job",
            {
                "action": "list",
                "children": {"bob": {"action": "manage", "children": {}}},
                "path": "/",
            },
        )
        assert check_image_catalog_permission(image, tree) is False

    def test_shared_image_read_permissions(self) -> None:
        image = "alice/img"
        # tree requested by bob:
        tree = ClientSubTreeViewRoot._from_json(
            "job",
            {
                "action": "list",
                "children": {
                    "bob": {"action": "manage", "children": {}},
                    "alice": {
                        "action": "list",
                        "children": {"img": {"action": "read", "children": {}}},
                    },
                },
                "path": "/",
            },
        )
        assert check_image_catalog_permission(image, tree) is True

    def test_shared_image_manage_permissions(self) -> None:
        image = "alice/img"
        tree = ClientSubTreeViewRoot._from_json(
            "job",
            {
                "action": "list",
                "children": {
                    "bob": {"action": "manage", "children": {}},
                    "alice": {
                        "action": "list",
                        "children": {"img": {"action": "manage", "children": {}}},
                    },
                },
                "path": "/",
            },
        )
        assert check_image_catalog_permission(image, tree) is True

    def test_shared_image_deny_permissions(self) -> None:
        image = "alice/img"
        tree = ClientSubTreeViewRoot._from_json(
            "job", {"action": "deny", "children": {}, "path": "/"}
        )
        assert check_image_catalog_permission(image, tree) is False

    def test_shared_image_slashes_in_image_name(self) -> None:
        image = "alice/foo/bar/img"
        tree = ClientSubTreeViewRoot._from_json(
            "job",
            {
                "action": "list",
                "children": {
                    "bob": {"action": "manage", "children": {}},
                    "alice": {
                        "action": "list",
                        "children": {
                            "foo": {
                                "action": "list",
                                "children": {
                                    "bar": {
                                        "action": "list",
                                        "children": {
                                            "img": {"action": "read", "children": {}}
                                        },
                                    }
                                },
                            }
                        },
                    },
                },
                "path": "/",
            },
        )
        assert check_image_catalog_permission(image, tree) is True

    def test_shared_image_parent_read_permissions(self) -> None:
        image = "alice/foo/bar/img"
        tree = ClientSubTreeViewRoot._from_json(
            "job",
            {
                "action": "list",
                "children": {
                    "bob": {"action": "manage", "children": {}},
                    "alice": {
                        "action": "list",
                        "children": {"foo": {"action": "read", "children": {}}},
                    },
                },
                "path": "/",
            },
        )
        assert check_image_catalog_permission(image, tree) is True

    def test_shared_image_root_read_permissions(self) -> None:
        image = "alice/foo/bar/img"
        tree = ClientSubTreeViewRoot._from_json(
            "job", {"action": "read", "children": {}, "path": "/"}
        )
        assert check_image_catalog_permission(image, tree) is True


class MockAuthServer:
    counter: int = 0
    expires_in: Optional[int] = None
    issued_at: Optional[str] = None

    async def handle(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        service = request.query.get("service")
        scopes = "-".join(request.query.getall("scope", ())) or None
        self.counter += 1
        payload: dict[str, Any] = {"token": f"token-{service}-{scopes}-{self.counter}"}
        if self.expires_in is not None:
            payload["expires_in"] = self.expires_in
        if self.issued_at is not None:
            payload["issued_at"] = self.issued_at
        return aiohttp.web.json_response(payload)


class MockTime:
    def __init__(self) -> None:
        self._time: float = time.time()

    def time(self) -> float:
        return self._time

    def sleep(self, delta: float) -> None:
        self._time += delta


class UpstreamTokenManager:
    def __init__(
        self,
        client: ClientSession,
        registry_config: UpstreamRegistryConfig,
        timefunc: Optional[Callable[[], float]] = None,
    ) -> None:
        timefunc = timefunc or time.time
        self._oauth_upstream = OAuthUpstream(
            client=OAuthClient(
                client=client,
                url=registry_config.token_endpoint_url,
                service=registry_config.token_service,
                username=registry_config.token_endpoint_username,
                password=registry_config.token_endpoint_password,
                time_factory=timefunc,
            ),
            time_factory=timefunc,
        )

    async def get_token_without_scope(self) -> str:
        headers = await self._oauth_upstream.get_headers_for_version()
        return BearerAuth.decode(headers[AUTHORIZATION]).token

    async def get_token_for_catalog(self) -> str:
        headers = await self._oauth_upstream.get_headers_for_catalog()
        return BearerAuth.decode(headers[AUTHORIZATION]).token

    async def get_token_for_repo(self, repo: str, mounted_repo: str = "") -> str:
        headers = await self._oauth_upstream.get_headers_for_repo(repo, mounted_repo)
        return BearerAuth.decode(headers[AUTHORIZATION]).token


class TestUpstreamTokenManager:
    @pytest.fixture
    def mock_auth_server(self) -> MockAuthServer:
        return MockAuthServer()

    @pytest.fixture
    def mock_time(self) -> MockTime:
        return MockTime()

    @pytest.fixture
    async def upstream_token_manager(
        self,
        aiohttp_server: _TestServerFactory,
        mock_auth_server: MockAuthServer,
        mock_time: MockTime,
    ) -> AsyncIterator[UpstreamTokenManager]:
        app = aiohttp.web.Application()
        app.router.add_get("/auth", mock_auth_server.handle)
        server = await aiohttp_server(app)
        registry_config = UpstreamRegistryConfig(
            endpoint_url=URL("http://upstream:5002"),
            project="testproject",
            token_endpoint_url=server.make_url("/auth"),
            token_service="upstream",
            token_endpoint_username="testuser",
            token_endpoint_password="testpassword",
        )
        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(force_close=True)
        ) as session:
            yield UpstreamTokenManager(
                session, registry_config, timefunc=mock_time.time
            )

    async def test_get_token_without_scope(
        self,
        mock_auth_server: MockAuthServer,
        upstream_token_manager: UpstreamTokenManager,
        mock_time: MockTime,
    ) -> None:
        utm = upstream_token_manager
        token = await utm.get_token_without_scope()
        assert token == "token-upstream-None-1"
        token = await utm.get_token_without_scope()
        assert token == "token-upstream-None-1"
        mock_time.sleep(100)
        token = await utm.get_token_without_scope()
        assert token == "token-upstream-None-2"

    async def test_get_token_without_scope_with_expires_in(
        self,
        mock_auth_server: MockAuthServer,
        upstream_token_manager: UpstreamTokenManager,
        mock_time: MockTime,
    ) -> None:
        utm = upstream_token_manager
        mock_auth_server.expires_in = 400
        token = await utm.get_token_without_scope()
        assert token == "token-upstream-None-1"
        mock_time.sleep(200)
        token = await utm.get_token_without_scope()
        assert token == "token-upstream-None-1"
        mock_time.sleep(200)
        token = await utm.get_token_without_scope()
        assert token == "token-upstream-None-2"

    async def test_get_token_without_scope_with_issued_at(
        self,
        mock_auth_server: MockAuthServer,
        upstream_token_manager: UpstreamTokenManager,
        mock_time: MockTime,
    ) -> None:
        utm = upstream_token_manager
        issued_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            seconds=200
        )
        mock_auth_server.issued_at = issued_at.isoformat()
        mock_auth_server.expires_in = 500
        token = await utm.get_token_without_scope()
        assert token == "token-upstream-None-1"
        mock_time.sleep(150)
        token = await utm.get_token_without_scope()
        assert token == "token-upstream-None-1"
        mock_time.sleep(100)
        token = await utm.get_token_without_scope()
        assert token == "token-upstream-None-2"

    async def test_get_token_for_catalog(
        self,
        mock_auth_server: MockAuthServer,
        upstream_token_manager: UpstreamTokenManager,
        mock_time: MockTime,
    ) -> None:
        utm = upstream_token_manager
        token = await utm.get_token_for_catalog()
        assert token == "token-upstream-registry:catalog:*-1"
        token = await utm.get_token_for_catalog()
        assert token == "token-upstream-registry:catalog:*-1"
        mock_time.sleep(100)
        token = await utm.get_token_for_catalog()
        assert token == "token-upstream-registry:catalog:*-2"

    async def test_get_token_for_repo(
        self,
        mock_auth_server: MockAuthServer,
        upstream_token_manager: UpstreamTokenManager,
        mock_time: MockTime,
    ) -> None:
        utm = upstream_token_manager
        token = await utm.get_token_for_repo("testrepo")
        assert token == "token-upstream-repository:testrepo:*-1"
        token = await utm.get_token_for_repo("testrepo")
        assert token == "token-upstream-repository:testrepo:*-1"
        mock_time.sleep(100)
        token = await utm.get_token_for_repo("testrepo")
        assert token == "token-upstream-repository:testrepo:*-2"
        token = await utm.get_token_for_repo("testrepo", "testrepo2")
        assert token == "token-upstream-repository:testrepo:*-repository:testrepo2:*-3"
