from unittest.mock import AsyncMock

import pytest
from yarl import URL

from platform_registry_api.auth_strategies import (
    BasicAuthStrategy,
    OAuthStrategy,
    OAuthToken,
)
from platform_registry_api.config import (
    Config,
)
from platform_registry_api.upstream_client import UpstreamV2ApiClient


class TestUpstreamV2APIClient:
    async def test_basic_auth_strategy(self, config_basic: Config) -> None:
        async with UpstreamV2ApiClient(config=config_basic.upstream_registry) as client:
            assert isinstance(client._auth_strategy, BasicAuthStrategy)
            headers = await client.auth_headers()
            assert headers == {"Authorization": "Basic dGVzdHVzZXI6dGVzdHBhc3N3b3Jk"}

    async def test_oauth_auth_strategy(
        self, config_oauth: Config, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async with UpstreamV2ApiClient(config=config_oauth.upstream_registry) as client:
            assert isinstance(client._auth_strategy, OAuthStrategy)
            monkeypatch.setattr(
                OAuthStrategy,
                "get_token",
                AsyncMock(
                    return_value=OAuthToken(
                        access_token="testtoken", expires_at=1560000000
                    )
                ),
            )
            headers = await client.auth_headers()
            assert headers == {"Authorization": "Bearer testtoken"}

    async def test_attributes(self, upstream_client: UpstreamV2ApiClient) -> None:
        assert upstream_client._url == URL("http://test-upstream")
        assert upstream_client._repo_prefix == URL("testproject/")
        assert upstream_client._config is not None
        assert upstream_client._auth_strategy is not None
        assert upstream_client._client is not None

    async def test_full_repo_name(self, upstream_client: UpstreamV2ApiClient) -> None:
        full_repo_name = upstream_client._full_repo_name("test-repo")
        assert full_repo_name == "testproject/test-repo"

    async def test_endpoints(self, upstream_client: UpstreamV2ApiClient) -> None:
        repo = "repo-name"
        assert upstream_client._v2_url == URL("http://test-upstream/v2/")
        assert upstream_client._v2_catalog_url() == URL(
            "http://test-upstream/v2/_catalog"
        )
        assert upstream_client._v2_tags_list_url(repo) == URL(
            "http://test-upstream/v2/testproject/repo-name/tags/list"
        )
        assert upstream_client._v2_image_manifests_tag_url(repo, "tag") == URL(
            "http://test-upstream/v2/testproject/repo-name/manifests/tag"
        )
        assert upstream_client._v2_image_manifests_digest_url(repo, "digest") == URL(
            "http://test-upstream/v2/testproject/repo-name/manifests/digest"
        )
        assert upstream_client._v2_repo_with_suffix(repo, "suffix?from=from") == URL(
            "http://test-upstream/v2/testproject/repo-name/suffix?from=from"
        )

    def test_scopes(self, upstream_client: UpstreamV2ApiClient) -> None:
        assert upstream_client._get_catalog_scopes() == ("registry:catalog:*",)
        assert upstream_client._get_repo_scopes(repo="repo") == [
            "repository:testproject/repo:*",
        ]
        assert upstream_client._get_repo_scopes(
            repo="repo", mounted_repo="mounted_repo"
        ) == [
            "repository:testproject/repo:*",
            "repository:testproject/mounted_repo:*",
        ]
