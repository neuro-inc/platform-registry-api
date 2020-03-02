from yarl import URL

from platform_registry_api.config import (
    AuthConfig,
    Config,
    EnvironConfigFactory,
    ServerConfig,
    UpstreamRegistryConfig,
    UpstreamType,
    ZipkinConfig,
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
            "NP_REGISTRY_ZIPKIN_URL": "http://zipkin.io:9411/",
            "NP_REGISTRY_ZIPKIN_SAMPLE_RATE": "0.3",
            "NP_CLUSTER_NAME": "test-cluster",
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
                token_registry_catalog_scope="registry:catalog:*",
                token_repository_scope_actions="*",
                max_catalog_entries=100,
            ),
            auth=AuthConfig(
                server_endpoint_url=URL("https://test_auth"),
                service_token="test_auth_token",
            ),
            zipkin=ZipkinConfig(URL("http://zipkin.io:9411/"), 0.3),
            cluster_name="test-cluster",
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
            "NP_REGISTRY_ZIPKIN_URL": "http://zipkin.io:9411/",
            "NP_REGISTRY_ZIPKIN_SAMPLE_RATE": "0.3",
            "NP_REGISTRY_UPSTREAM_TOKEN_REGISTRY_SCOPE": "",
            "NP_REGISTRY_UPSTREAM_TOKEN_REPO_SCOPE_ACTIONS": "push,pull",
            "NP_CLUSTER_NAME": "test-cluster",
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
                token_registry_catalog_scope="",
                token_repository_scope_actions="push,pull",
                max_catalog_entries=10000,
            ),
            auth=AuthConfig(
                server_endpoint_url=URL("https://test_auth"),
                service_token="test_auth_token",
            ),
            zipkin=ZipkinConfig(URL("http://zipkin.io:9411/"), 0.3),
            cluster_name="test-cluster",
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
            "NP_REGISTRY_ZIPKIN_URL": "http://zipkin.io:9411/",
            "NP_REGISTRY_ZIPKIN_SAMPLE_RATE": "0.3",
            "NP_CLUSTER_NAME": "test-cluster",
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
            zipkin=ZipkinConfig(URL("http://zipkin.io:9411/"), 0.3),
            cluster_name="test-cluster",
        )
        assert not config.upstream_registry.is_oauth

    def test_defaults_basic(self) -> None:
        environ = {
            "NP_REGISTRY_UPSTREAM_URL": "https://test_host",
            "NP_REGISTRY_UPSTREAM_PROJECT": "test_project",
            "NP_REGISTRY_UPSTREAM_TYPE": "basic",
            "NP_REGISTRY_UPSTREAM_MAX_CATALOG_ENTRIES": "1000",
            "NP_REGISTRY_AUTH_URL": "https://test_auth",
            "NP_REGISTRY_AUTH_TOKEN": "test_auth_token",
            "NP_REGISTRY_ZIPKIN_URL": "http://zipkin.io:9411/",
            "NP_REGISTRY_ZIPKIN_SAMPLE_RATE": "0.3",
            "NP_CLUSTER_NAME": "test-cluster",
        }
        config = EnvironConfigFactory(environ=environ).create()
        assert config == Config(
            server=ServerConfig(),
            upstream_registry=UpstreamRegistryConfig(
                endpoint_url=URL("https://test_host"),
                project="test_project",
                type=UpstreamType.BASIC,
                max_catalog_entries=1000,
            ),
            auth=AuthConfig(
                server_endpoint_url=URL("https://test_auth"),
                service_token="test_auth_token",
            ),
            zipkin=ZipkinConfig(URL("http://zipkin.io:9411/"), 0.3),
            cluster_name="test-cluster",
        )
        assert config.upstream_registry.is_basic
        assert not config.upstream_registry.is_oauth

    def test_basic(self) -> None:
        environ = {
            "NP_REGISTRY_UPSTREAM_URL": "https://test_host",
            "NP_REGISTRY_UPSTREAM_PROJECT": "test_project",
            "NP_REGISTRY_UPSTREAM_TYPE": "basic",
            "NP_REGISTRY_UPSTREAM_MAX_CATALOG_ENTRIES": "1000",
            "NP_REGISTRY_AUTH_URL": "https://test_auth",
            "NP_REGISTRY_AUTH_TOKEN": "test_auth_token",
            "NP_REGISTRY_ZIPKIN_URL": "http://zipkin.io:9411/",
            "NP_REGISTRY_ZIPKIN_SAMPLE_RATE": "0.3",
            "NP_CLUSTER_NAME": "test-cluster",
            "NP_REGISTRY_UPSTREAM_BASIC_USERNAME": "testuser",
            "NP_REGISTRY_UPSTREAM_BASIC_PASSWORD": "testpassword",
        }
        config = EnvironConfigFactory(environ=environ).create()
        assert config == Config(
            server=ServerConfig(),
            upstream_registry=UpstreamRegistryConfig(
                endpoint_url=URL("https://test_host"),
                project="test_project",
                type=UpstreamType.BASIC,
                max_catalog_entries=1000,
                basic_username="testuser",
                basic_password="testpassword",
            ),
            auth=AuthConfig(
                server_endpoint_url=URL("https://test_auth"),
                service_token="test_auth_token",
            ),
            zipkin=ZipkinConfig(URL("http://zipkin.io:9411/"), 0.3),
            cluster_name="test-cluster",
        )
        assert config.upstream_registry.is_basic
        assert not config.upstream_registry.is_oauth
