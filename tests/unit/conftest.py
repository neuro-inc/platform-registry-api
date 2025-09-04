from collections.abc import AsyncGenerator

import pytest
from yarl import URL

from platform_registry_api.config import (
    AdminClientConfig,
    AuthConfig,
    Config,
    ServerConfig,
    UpstreamRegistryConfig,
    UpstreamType,
)
from platform_registry_api.upstream_client import UpstreamV2ApiClient


@pytest.fixture(scope="session")
def config_basic() -> Config:
    upstream_registry = UpstreamRegistryConfig(
        type=UpstreamType.BASIC,
        endpoint_url=URL("http://test-upstream"),
        project="testproject",
        basic_username="testuser",
        basic_password="testpassword",
    )
    auth = AuthConfig(
        server_endpoint_url=URL("http://test-auth-api"), service_token="admin_token"
    )
    admin_client = AdminClientConfig(URL("http://test-admin-api"), token="admin_token")
    return Config(
        server=ServerConfig(),
        upstream_registry=upstream_registry,
        auth=auth,
        admin_client=admin_client,
        cluster_name="test-cluster",
    )


@pytest.fixture(scope="session")
def config_oauth() -> Config:
    upstream_registry = UpstreamRegistryConfig(
        endpoint_url=URL("http://test-upstream"),
        project="testproject",
        token_endpoint_url=URL("http://test-auth-server"),
        token_service="upstream",
        token_endpoint_username="testuser",
        token_endpoint_password="testpassword",
    )
    auth = AuthConfig(
        server_endpoint_url=URL("http://test-auth-api"), service_token="admin_token"
    )
    admin_token = AdminClientConfig(
        endpoint_url=URL("http://test-admin-api"), token="admin_token"
    )
    return Config(
        server=ServerConfig(),
        upstream_registry=upstream_registry,
        auth=auth,
        admin_client=admin_token,
        cluster_name="test-cluster",
    )


@pytest.fixture(scope="session")
async def upstream_client(config_oauth: Config) -> AsyncGenerator[UpstreamV2ApiClient]:
    async with UpstreamV2ApiClient(config=config_oauth.upstream_registry) as client:
        yield client
