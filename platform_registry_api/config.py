from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from apolo_events_client import EventsClientConfig
from yarl import URL


@dataclass(frozen=True)
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    name: str = "Docker Registry"


@dataclass(frozen=True)
class AdminClientConfig:
    endpoint_url: URL | None
    token: str = field(repr=False)


@dataclass(frozen=True)
class AuthConfig:
    server_endpoint_url: URL | None
    service_token: str = field(repr=False)


class UpstreamType(str, Enum):
    BASIC = "basic"
    OAUTH = "oauth"
    AWS_ECR = "aws_ecr"


@dataclass(frozen=True)
class UpstreamRegistryConfig:
    endpoint_url: URL
    project: str
    repo: str = ""

    type: UpstreamType = UpstreamType.OAUTH

    basic_username: str = field(repr=False, default="")
    basic_password: str = field(repr=False, default="")

    # TODO: should be derived from the WWW-Authenticate header instead
    token_endpoint_url: URL = URL()
    token_service: str = ""
    token_endpoint_username: str = field(repr=False, default="")
    token_endpoint_password: str = field(repr=False, default="")
    token_registry_catalog_scope: str = "registry:catalog:*"
    token_repository_scope_actions: str = "*"

    sock_connect_timeout_s: float | None = 30.0
    sock_read_timeout_s: float | None = 30.0

    # https://github.com/docker/distribution/blob/dcfe05ce6cff995f419f8df37b59987257ffb8c1/registry/handlers/catalog.go#L16
    max_catalog_entries: int = 1000

    @property
    def is_basic(self) -> bool:
        return self.type == UpstreamType.BASIC

    @property
    def is_oauth(self) -> bool:
        return self.type == UpstreamType.OAUTH


@dataclass(frozen=True)
class Config:
    server: ServerConfig
    upstream_registry: UpstreamRegistryConfig
    auth: AuthConfig
    admin_client: AdminClientConfig
    cluster_name: str
    events: EventsClientConfig | None = None


class EnvironConfigFactory:
    def __init__(self, environ: dict[str, str] | None = None) -> None:
        self._environ = environ or os.environ

    def _get_url(self, name: str) -> URL | None:
        value = self._environ[name]
        if value == "-":
            return None
        return URL(value)

    def create_server(self) -> ServerConfig:
        port = int(self._environ.get("NP_REGISTRY_API_PORT", ServerConfig.port))
        return ServerConfig(port=port)

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
        upstream: dict[str, Any] = {
            "endpoint_url": endpoint_url,
            "project": project,
            "max_catalog_entries": max_catalog_entries,
            "type": upstream_type,
        }
        if upstream_type == UpstreamType.OAUTH:
            upstream.update(
                {
                    "token_endpoint_url": URL(
                        self._environ["NP_REGISTRY_UPSTREAM_TOKEN_URL"]
                    ),
                    "token_service": self._environ[
                        "NP_REGISTRY_UPSTREAM_TOKEN_SERVICE"
                    ],
                    "token_endpoint_username": self._environ[
                        "NP_REGISTRY_UPSTREAM_TOKEN_USERNAME"
                    ],
                    "token_endpoint_password": self._environ[
                        "NP_REGISTRY_UPSTREAM_TOKEN_PASSWORD"
                    ],
                }
            )
            if "NP_REGISTRY_UPSTREAM_REPO" in self._environ:
                upstream["repo"] = self._environ["NP_REGISTRY_UPSTREAM_REPO"]
            if "NP_REGISTRY_UPSTREAM_TOKEN_REGISTRY_SCOPE" in self._environ:
                upstream["token_registry_catalog_scope"] = self._environ[
                    "NP_REGISTRY_UPSTREAM_TOKEN_REGISTRY_SCOPE"
                ]
            if "NP_REGISTRY_UPSTREAM_TOKEN_REPO_SCOPE_ACTIONS" in self._environ:
                upstream["token_repository_scope_actions"] = self._environ[
                    "NP_REGISTRY_UPSTREAM_TOKEN_REPO_SCOPE_ACTIONS"
                ]
        if upstream_type == UpstreamType.BASIC:
            basic_username = self._environ.get("NP_REGISTRY_UPSTREAM_BASIC_USERNAME")
            if basic_username is not None:
                upstream["basic_username"] = basic_username
            basic_password = self._environ.get("NP_REGISTRY_UPSTREAM_BASIC_PASSWORD")
            if basic_password is not None:
                upstream["basic_password"] = basic_password
        return UpstreamRegistryConfig(**upstream)

    def create_auth(self) -> AuthConfig:
        url = self._get_url("NP_REGISTRY_AUTH_URL")
        token = self._environ["NP_REGISTRY_AUTH_TOKEN"]
        return AuthConfig(server_endpoint_url=url, service_token=token)

    def create_admin_client(self) -> AdminClientConfig:
        url = URL(self._environ["NP_REGISTRY_ADMIN_CLIENT_URL"])
        token = self._environ["NP_REGISTRY_ADMIN_CLIENT_TOKEN"]
        return AdminClientConfig(endpoint_url=url, token=token)

    def create_events(self) -> EventsClientConfig | None:
        if "NP_REGISTRY_EVENTS_URL" in self._environ:
            url = URL(self._environ["NP_REGISTRY_EVENTS_URL"])
            token = self._environ["NP_REGISTRY_EVENTS_TOKEN"]
            return EventsClientConfig(url=url, token=token, name="platform-registry")
        return None

    def create(self) -> Config:
        server_config = self.create_server()
        upstream_registry_config = self.create_upstream_registry()
        auth_config = self.create_auth()
        admin_client = self.create_admin_client()
        cluster_name = self._environ["NP_CLUSTER_NAME"]
        events = self.create_events()
        assert cluster_name
        return Config(
            server=server_config,
            upstream_registry=upstream_registry_config,
            auth=auth_config,
            admin_client=admin_client,
            cluster_name=cluster_name,
            events=events,
        )
