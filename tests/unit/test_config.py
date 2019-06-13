from yarl import URL

from platform_registry_api.config import (
    AuthConfig,
    Config,
    EnvironConfigFactory,
    ServerConfig,
    UpstreamRegistryConfig,
    UpstreamType,
)


class TestEnvironConfigFactory:
    def test_defaults_oauth(self) -> None:
        environ = {
            "NP_REGISTRY_UPSTREAM_URL": "https://test_host",
            "NP_REGISTRY_UPSTREAM_PROJECT": "test_project",
            "NP_REGISTRY_UPSTREAM_TOKEN_URL": "https://test_host/token",
            "NP_REGISTRY_UPSTREAM_TOKEN_SERVICE": "test_host",
            "NP_REGISTRY_UPSTREAM_TOKEN_USERNAME": "test_username",
            "NP_REGISTRY_UPSTREAM_TOKEN_PASSWORD": "test_password",
            "NP_REGISTRY_AUTH_URL": "https://test_auth",
            "NP_REGISTRY_AUTH_TOKEN": "test_auth_token",
        }
        config = EnvironConfigFactory(environ=environ).create()
        assert config == Config(
            server=ServerConfig(),
            upstream_registry=UpstreamRegistryConfig(
                endpoint_url=URL("https://test_host"),
                project="test_project",
                type=UpstreamType.OAUTH,
                token_endpoint_url=URL("https://test_host/token"),
                token_service="test_host",
                token_endpoint_username="test_username",
                token_endpoint_password="test_password",
                max_catalog_entries=100,
            ),
            auth=AuthConfig(
                server_endpoint_url=URL("https://test_auth"),
                service_token="test_auth_token",
            ),
        )
        assert config.upstream_registry.is_oauth

    def test_oauth(self) -> None:
        environ = {
            "NP_REGISTRY_API_PORT": "1234",
            "NP_REGISTRY_UPSTREAM_URL": "https://test_host",
            "NP_REGISTRY_UPSTREAM_PROJECT": "test_project",
            "NP_REGISTRY_UPSTREAM_TYPE": "oauth",
            "NP_REGISTRY_UPSTREAM_MAX_CATALOG_ENTRIES": "10000",
            "NP_REGISTRY_UPSTREAM_TOKEN_URL": "https://test_host/token",
            "NP_REGISTRY_UPSTREAM_TOKEN_SERVICE": "test_host",
            "NP_REGISTRY_UPSTREAM_TOKEN_USERNAME": "test_username",
            "NP_REGISTRY_UPSTREAM_TOKEN_PASSWORD": "test_password",
            "NP_REGISTRY_AUTH_URL": "https://test_auth",
            "NP_REGISTRY_AUTH_TOKEN": "test_auth_token",
        }
        config = EnvironConfigFactory(environ=environ).create()
        assert config == Config(
            server=ServerConfig(port=1234),
            upstream_registry=UpstreamRegistryConfig(
                endpoint_url=URL("https://test_host"),
                project="test_project",
                type=UpstreamType.OAUTH,
                token_endpoint_url=URL("https://test_host/token"),
                token_service="test_host",
                token_endpoint_username="test_username",
                token_endpoint_password="test_password",
                max_catalog_entries=10000,
            ),
            auth=AuthConfig(
                server_endpoint_url=URL("https://test_auth"),
                service_token="test_auth_token",
            ),
        )
        assert config.upstream_registry.is_oauth

    def test_aws_ecr(self) -> None:
        environ = {
            "NP_REGISTRY_UPSTREAM_URL": "https://test_host",
            "NP_REGISTRY_UPSTREAM_PROJECT": "test_project",
            "NP_REGISTRY_UPSTREAM_TYPE": "aws_ecr",
            "NP_REGISTRY_UPSTREAM_MAX_CATALOG_ENTRIES": "1000",
            "NP_REGISTRY_AUTH_URL": "https://test_auth",
            "NP_REGISTRY_AUTH_TOKEN": "test_auth_token",
        }
        config = EnvironConfigFactory(environ=environ).create()
        assert config == Config(
            server=ServerConfig(),
            upstream_registry=UpstreamRegistryConfig(
                endpoint_url=URL("https://test_host"),
                project="test_project",
                type=UpstreamType.AWS_ECR,
                max_catalog_entries=1000,
            ),
            auth=AuthConfig(
                server_endpoint_url=URL("https://test_auth"),
                service_token="test_auth_token",
            ),
        )
        assert not config.upstream_registry.is_oauth
