from yarl import URL

from platform_registry_api.config import (
    AuthConfig,
    Config,
    EnvironConfigFactory,
    SentryConfig,
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
            "NP_REGISTRY_AUTH_URL": "-",
            "NP_REGISTRY_AUTH_TOKEN": "test_auth_token",
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
                server_endpoint_url=None,
                service_token="test_auth_token",
            ),
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
            "NP_REGISTRY_UPSTREAM_TOKEN_REGISTRY_SCOPE": "",
            "NP_REGISTRY_UPSTREAM_TOKEN_REPO_SCOPE_ACTIONS": "push,pull",
            "NP_CLUSTER_NAME": "test-cluster",
            "NP_ZIPKIN_URL": "http://zipkin.io:9411/",
            "NP_SENTRY_DSN": "https://sentry",
            "NP_SENTRY_CLUSTER_NAME": "test",
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
            cluster_name="test-cluster",
            zipkin=ZipkinConfig(URL("http://zipkin.io:9411/")),
            sentry=SentryConfig(dsn=URL("https://sentry"), cluster_name="test"),
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
            cluster_name="test-cluster",
        )
        assert config.upstream_registry.is_basic
        assert not config.upstream_registry.is_oauth

    def test_create_zipkin_none(self) -> None:
        result = EnvironConfigFactory({}).create_zipkin()

        assert result is None

    def test_create_zipkin_default(self) -> None:
        env = {"NP_ZIPKIN_URL": "https://zipkin:9411"}
        result = EnvironConfigFactory(env).create_zipkin()

        assert result == ZipkinConfig(url=URL("https://zipkin:9411"))

    def test_create_zipkin_custom(self) -> None:
        env = {
            "NP_ZIPKIN_URL": "https://zipkin:9411",
            "NP_ZIPKIN_APP_NAME": "api",
            "NP_ZIPKIN_SAMPLE_RATE": "1",
        }
        result = EnvironConfigFactory(env).create_zipkin()

        assert result == ZipkinConfig(
            url=URL("https://zipkin:9411"), app_name="api", sample_rate=1
        )

    def test_create_sentry_none(self) -> None:
        result = EnvironConfigFactory({}).create_sentry()

        assert result is None

    def test_create_sentry_default(self) -> None:
        env = {
            "NP_SENTRY_DSN": "https://sentry",
            "NP_SENTRY_CLUSTER_NAME": "test",
        }
        result = EnvironConfigFactory(env).create_sentry()

        assert result == SentryConfig(dsn=URL("https://sentry"), cluster_name="test")

    def test_create_sentry_custom(self) -> None:
        env = {
            "NP_SENTRY_DSN": "https://sentry",
            "NP_SENTRY_APP_NAME": "api",
            "NP_SENTRY_CLUSTER_NAME": "test",
            "NP_SENTRY_SAMPLE_RATE": "1",
        }
        result = EnvironConfigFactory(env).create_sentry()

        assert result == SentryConfig(
            dsn=URL("https://sentry"),
            app_name="api",
            cluster_name="test",
            sample_rate=1,
        )
