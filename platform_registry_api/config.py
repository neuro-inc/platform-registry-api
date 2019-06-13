import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from yarl import URL


@dataclass(frozen=True)
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    name: str = "Docker Registry"


@dataclass(frozen=True)
class AuthConfig:
    server_endpoint_url: URL
    service_token: str = field(repr=False)


class UpstreamType(str, Enum):
    OAUTH = "oauth"
    AWS_ECR = "aws_ecr"


@dataclass(frozen=True)
class UpstreamRegistryConfig:
    endpoint_url: URL
    project: str

    type: UpstreamType = UpstreamType.OAUTH

    # TODO: should be derived from the WWW-Authenticate header instead
    token_endpoint_url: URL = URL()
    token_service: str = ""
    token_endpoint_username: str = field(repr=False, default="")
    token_endpoint_password: str = field(repr=False, default="")

    sock_connect_timeout_s: Optional[float] = 30.0
    sock_read_timeout_s: Optional[float] = 30.0

    # https://github.com/docker/distribution/blob/dcfe05ce6cff995f419f8df37b59987257ffb8c1/registry/handlers/catalog.go#L16
    max_catalog_entries: int = 100

    @property
    def is_oauth(self) -> bool:
        return self.type == UpstreamType.OAUTH


@dataclass(frozen=True)
class Config:
    server: ServerConfig
    upstream_registry: UpstreamRegistryConfig
    auth: AuthConfig


class EnvironConfigFactory:
    def __init__(self, environ: Optional[Dict[str, str]] = None) -> None:
        self._environ = environ or os.environ

    def create_server(self) -> ServerConfig:
        port = int(self._environ.get("NP_REGISTRY_API_PORT", ServerConfig.port))
        return ServerConfig(port=port)  # type: ignore

    def create_upstream_registry(self) -> UpstreamRegistryConfig:
        endpoint_url = URL(self._environ["NP_REGISTRY_UPSTREAM_URL"])
        project = self._environ["NP_REGISTRY_UPSTREAM_PROJECT"]
        max_catalog_entries = int(
            self._environ.get(
                "NP_REGISTRY_UPSTREAM_MAX_CATALOG_ENTRIES",
                UpstreamRegistryConfig.max_catalog_entries,
            )
        )

        upstream_type = UpstreamType(
            self._environ.get("NP_REGISTRY_UPSTREAM_TYPE", UpstreamType.OAUTH.value)
        )
        upstream: Dict[str, Any] = dict(
            endpoint_url=endpoint_url,
            project=project,
            max_catalog_entries=max_catalog_entries,
            type=upstream_type,
        )
        if upstream_type == UpstreamType.OAUTH:
            upstream.update(
                dict(
                    token_endpoint_url=URL(
                        self._environ["NP_REGISTRY_UPSTREAM_TOKEN_URL"]
                    ),
                    token_service=self._environ["NP_REGISTRY_UPSTREAM_TOKEN_SERVICE"],
                    token_endpoint_username=self._environ[
                        "NP_REGISTRY_UPSTREAM_TOKEN_USERNAME"
                    ],
                    token_endpoint_password=self._environ[
                        "NP_REGISTRY_UPSTREAM_TOKEN_PASSWORD"
                    ],
                )
            )
        return UpstreamRegistryConfig(**upstream)  # type: ignore

    def create_auth(self) -> AuthConfig:
        url = URL(self._environ["NP_REGISTRY_AUTH_URL"])
        token = self._environ["NP_REGISTRY_AUTH_TOKEN"]
        return AuthConfig(server_endpoint_url=url, service_token=token)  # type: ignore

    def create(self) -> Config:
        server_config = self.create_server()
        upstream_registry_config = self.create_upstream_registry()
        auth_config = self.create_auth()
        return Config(  # type: ignore
            server=server_config,
            upstream_registry=upstream_registry_config,
            auth=auth_config,
        )
