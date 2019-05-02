import datetime
import time
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Optional

import aiohttp
import pytest
from neuro_auth_client.client import ClientSubTreeViewRoot
from yarl import URL

from platform_registry_api.api import (
    RepoURL,
    TokenCache,
    UpstreamTokenManager,
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
    def test_from_url_value_error(self, url):
        with pytest.raises(
            ValueError, match=f"unexpected path in a registry URL: {url}"
        ):
            RepoURL.from_url(url)

    def test_from_url(self):
        url = URL("https://example.com/v2/name/tags/list?whatever=thatis")
        reg_url = RepoURL.from_url(url)
        assert reg_url == RepoURL(repo="name", url=url)

    def test_from_url_edge_case_1(self):
        url = URL("/v2/tags/tags/list?whatever=thatis")
        reg_url = RepoURL.from_url(url)
        assert reg_url == RepoURL(repo="tags", url=url)

    def test_from_url_edge_case_2(self):
        url = URL("/v2/tags/tags/tags/list?whatever=thatis")
        reg_url = RepoURL.from_url(url)
        assert reg_url == RepoURL(repo="tags/tags", url=url)

    def test_with_repo(self):
        url = URL("https://example.com/v2/this/image/tags/list?what=ever")
        reg_url = RepoURL.from_url(url).with_repo("another/img")
        assert reg_url == RepoURL(
            repo="another/img",
            url=URL("https://example.com/v2/another/img/tags/list?what=ever"),
        )

    def test_with_origin(self):
        url = URL("https://example.com/v2/this/image/tags/list?what=ever")
        reg_url = RepoURL.from_url(url).with_origin(URL("http://a.b"))
        assert reg_url == RepoURL(
            repo="this/image", url=URL("http://a.b/v2/this/image/tags/list?what=ever")
        )


class TestURLFactory:
    @pytest.fixture
    def url_factory(self):
        registry_endpoint_url = URL("http://registry:5000")
        upstream_endpoint_url = URL("http://upstream:5000")
        return URLFactory(
            registry_endpoint_url=registry_endpoint_url,
            upstream_endpoint_url=upstream_endpoint_url,
            upstream_project="upstream",
        )

    def test_create_registry_version_check_url(self, url_factory):
        assert url_factory.create_registry_version_check_url() == URL(
            "http://upstream:5000/v2/"
        )

    def test_create_upstream_repo_url(self, url_factory):
        reg_repo_url = RepoURL.from_url(
            URL("http://registry:5000/v2/this/image/tags/list?what=ever")
        )
        up_repo_url = url_factory.create_upstream_repo_url(reg_repo_url)

        expected_url = URL(
            "http://upstream:5000/v2/upstream/this/image/tags/list?what=ever"
        )
        assert up_repo_url == RepoURL(repo="upstream/this/image", url=expected_url)

    def test_create_registry_repo_url(self, url_factory):
        up_repo_url = RepoURL.from_url(
            URL("http://upstream:5000/v2/upstream/this/image/tags/list?what=")
        )
        reg_repo_url = url_factory.create_registry_repo_url(up_repo_url)

        expected_url = URL("http://registry:5000/v2/this/image/tags/list?what=")
        assert reg_repo_url == RepoURL(repo="this/image", url=expected_url)

    def test_create_registry_repo_url_no_project(self, url_factory):
        up_repo_url = RepoURL.from_url(
            URL("http://upstream:5000/v2/image/tags/list?what=")
        )
        with pytest.raises(ValueError, match='Upstream project "" does not match'):
            url_factory.create_registry_repo_url(up_repo_url)

    def test_create_registry_repo_url_wrong_project(self, url_factory):
        up_repo_url = RepoURL.from_url(
            URL("http://upstream:5000/v2/unknown/image/tags/list?what=")
        )
        with pytest.raises(
            ValueError, match='Upstream project "unknown" does not match'
        ):
            url_factory.create_registry_repo_url(up_repo_url)


class TestV2Handler:
    def test_filter_images_by_project(self):
        images_names = [
            "testproject/alice/img1",
            "testproject/alice/img2",
            "testproject2/alice/img3",
        ]
        project = "testproject"
        tree = ClientSubTreeViewRoot._from_json(
            {
                "action": "list",
                "children": {"alice": {"action": "manage", "children": {}}},
                "path": "/",
            }
        )
        assert list(V2Handler.filter_images(images_names, tree, project)) == [
            "alice/img1",
            "alice/img2",
        ]

    def test_filter_images_by_tree_user_mismatch(self):
        images_names = [
            "testproject/alice/img1",
            "testproject/alice/img2",
            "testproject/bob/img3",
        ]
        project = "testproject"
        tree = ClientSubTreeViewRoot._from_json(
            {
                "action": "list",
                "children": {"alice": {"action": "manage", "children": {}}},
                "path": "/",
            }
        )
        assert list(V2Handler.filter_images(images_names, tree, project)) == [
            "alice/img1",
            "alice/img2",
        ]

    def test_filter_images_by_tree_superuser(self):
        images_names = [
            "testproject/alice/img1",
            "testproject/alice/img2",
            "testproject/bob/img3",
            "testproject/foo/img4",
        ]
        project = "testproject"
        tree = ClientSubTreeViewRoot._from_json(
            {
                "action": "manage",
                "children": {"alice": {"action": "manage", "children": {}}},
                "path": "/",
            }
        )
        assert list(V2Handler.filter_images(images_names, tree, project)) == [
            "alice/img1",
            "alice/img2",
            "bob/img3",
            "foo/img4",
        ]

    def test_filter_images_no_elements(self):
        images_names = []
        project = "testproject"
        tree = ClientSubTreeViewRoot._from_json(
            {
                "action": "list",
                "children": {"alice": {"action": "manage", "children": {}}},
                "path": "/",
            }
        )
        assert list(V2Handler.filter_images(images_names, tree, project)) == []


class TestHelpers_CheckImageCatalogPermission:
    def test_default_permissions(self):
        # alice checks her own image "alice/img"
        image = "alice/img"
        tree = ClientSubTreeViewRoot._from_json(
            {
                "action": "list",
                "children": {"alice": {"action": "manage", "children": {}}},
                "path": "/",
            }
        )
        assert check_image_catalog_permission(image, tree) is True

    def test_another_user_default_permissions__forbidden(self):
        image = "alice/img"
        tree = ClientSubTreeViewRoot._from_json(
            {
                "action": "list",
                "children": {"bob": {"action": "manage", "children": {}}},
                "path": "/",
            }
        )
        assert check_image_catalog_permission(image, tree) is False

    def test_shared_image_read_permissions(self):
        image = "alice/img"
        # tree requested by bob:
        tree = ClientSubTreeViewRoot._from_json(
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
            }
        )
        assert check_image_catalog_permission(image, tree) is True

    def test_shared_image_manage_permissions(self):
        image = "alice/img"
        tree = ClientSubTreeViewRoot._from_json(
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
            }
        )
        assert check_image_catalog_permission(image, tree) is True

    def test_shared_image_slashes_in_image_name(self):
        image = "alice/foo/bar/img"
        tree = ClientSubTreeViewRoot._from_json(
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
            }
        )
        assert check_image_catalog_permission(image, tree) is True

    def test_shared_image_slashes_in_image_name_deny_in_the_middle(self):
        image = "alice/foo/bar/img"
        tree = ClientSubTreeViewRoot._from_json(
            {
                "action": "list",
                "children": {
                    "bob": {"action": "manage", "children": {}},
                    "alice": {
                        "action": "list",
                        "children": {
                            "foo": {
                                "action": "deny",
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
            }
        )
        assert check_image_catalog_permission(image, tree) is False


class MockAuthServer:
    counter: int = 0
    expires_in: Optional[int] = None
    issued_at: Optional[str] = None

    async def handle(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        service = request.query.get("service")
        scope = request.query.get("scope")
        self.counter += 1
        payload: Dict[str, Any] = {"token": f"token-{service}-{scope}-{self.counter}"}
        if self.expires_in is not None:
            payload["expires_in"] = self.expires_in
        if self.issued_at is not None:
            payload["issued_at"] = self.issued_at
        return aiohttp.web.json_response(payload)


class TestUpstreamTokenManager:
    @pytest.fixture
    def mock_auth_server(self) -> MockAuthServer:
        return MockAuthServer()

    @pytest.fixture
    async def upstream_token_manager(
        self, aiohttp_server: _TestServerFactory, mock_auth_server: MockAuthServer
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
            yield UpstreamTokenManager(session, registry_config)

    @pytest.fixture
    def sleep(self, monkeypatch: Any) -> Callable[[float], None]:
        def mock_sleep(delta: float) -> None:
            orig_time = time.time

            def mock_time() -> float:
                return orig_time() + delta

            monkeypatch.setattr(time, "time", mock_time)

        return mock_sleep

    @pytest.mark.asyncio
    async def test_get_token_without_scope(
        self,
        mock_auth_server: MockAuthServer,
        upstream_token_manager: UpstreamTokenManager,
        sleep: Callable[[float], None],
    ) -> None:
        utm = upstream_token_manager
        token = await utm.get_token_without_scope()
        assert token == "token-upstream-None-1"
        token = await utm.get_token_without_scope()
        assert token == "token-upstream-None-1"
        sleep(100)
        token = await utm.get_token_without_scope()
        assert token == "token-upstream-None-2"

    @pytest.mark.asyncio
    async def test_get_token_without_scope_with_expires_in(
        self,
        mock_auth_server: MockAuthServer,
        upstream_token_manager: UpstreamTokenManager,
        sleep: Callable[[float], None],
    ) -> None:
        utm = upstream_token_manager
        mock_auth_server.expires_in = 400
        token = await utm.get_token_without_scope()
        assert token == "token-upstream-None-1"
        sleep(200)
        token = await utm.get_token_without_scope()
        assert token == "token-upstream-None-1"
        sleep(200)
        token = await utm.get_token_without_scope()
        assert token == "token-upstream-None-2"

    @pytest.mark.asyncio
    async def test_get_token_without_scope_with_issued_at(
        self,
        mock_auth_server: MockAuthServer,
        upstream_token_manager: UpstreamTokenManager,
        sleep: Callable[[float], None],
    ) -> None:
        utm = upstream_token_manager
        issued_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            seconds=200
        )
        mock_auth_server.issued_at = issued_at.isoformat()
        mock_auth_server.expires_in = 500
        token = await utm.get_token_without_scope()
        assert token == "token-upstream-None-1"
        sleep(150)
        token = await utm.get_token_without_scope()
        assert token == "token-upstream-None-1"
        sleep(100)
        token = await utm.get_token_without_scope()
        assert token == "token-upstream-None-2"

    @pytest.mark.asyncio
    async def test_get_token_for_catalog(
        self,
        mock_auth_server: MockAuthServer,
        upstream_token_manager: UpstreamTokenManager,
        sleep: Callable[[float], None],
    ) -> None:
        utm = upstream_token_manager
        token = await utm.get_token_for_catalog()
        assert token == "token-upstream-registry:catalog:*-1"
        token = await utm.get_token_for_catalog()
        assert token == "token-upstream-registry:catalog:*-1"
        sleep(100)
        token = await utm.get_token_for_catalog()
        assert token == "token-upstream-registry:catalog:*-2"

    @pytest.mark.asyncio
    async def test_get_token_for_repo(
        self,
        mock_auth_server: MockAuthServer,
        upstream_token_manager: UpstreamTokenManager,
        sleep: Callable[[float], None],
    ) -> None:
        utm = upstream_token_manager
        token = await utm.get_token_for_repo("testrepo")
        assert token == "token-upstream-repository:testrepo:*-1"
        token = await utm.get_token_for_repo("testrepo")
        assert token == "token-upstream-repository:testrepo:*-1"
        sleep(100)
        token = await utm.get_token_for_repo("testrepo")
        assert token == "token-upstream-repository:testrepo:*-2"

    def test_parse_expiration_time(self):
        parse_expiration_time = UpstreamTokenManager.parse_expiration_time
        assert parse_expiration_time({}, 1556642814.0) == 1556642859.0
        payload = {"expires_in": 300}
        assert parse_expiration_time(payload, 1556642814.0) == 1556643039.0
        payload = {"expires_in": 300, "issued_at": "2019-04-30T16:46:54Z"}
        assert parse_expiration_time(payload, 0) == 1556643039.0
        payload = {"expires_in": 300, "issued_at": "2019-04-30T19:46:54+03:00"}
        assert parse_expiration_time(payload, 0) == 1556643039.0

    def test_token_cache(self):
        cache = TokenCache()
        assert cache.get("upstream", None, 1556642814.0) is None
        cache.put("upstream", None, 1556642814.0, "testtoken")
        assert cache.get("upstream", None, 1556642813.0) == "testtoken"
        assert cache.get("upstream", "registry:catalog:*", 1556642813.0) is None
        assert cache.get("upstream", None, 1556642815.0) is None
        cache.put("upstream", None, 1556642814.0, "othertoken")
        assert cache.get("upstream", None, 1556642813.0) == "othertoken"
        assert cache.get("upstream", None, 1556642815.0) is None
