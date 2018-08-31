import os
from dataclasses import dataclass, field
from typing import Dict, Optional

from yarl import URL


@dataclass(frozen=True)
class ServerConfig:
    host: str = '0.0.0.0'
    port: int = 8080


@dataclass(frozen=True)
class UpstreamRegistryConfig:
    endpoint_url: URL
    project: str
    # TODO: should be derived from the WWW-Authenticate header instead
    token_endpoint_url: URL
    token_endpoint_username: str = field(repr=False)
    token_endpoint_password: str = field(repr=False)

    @property
    def token_service(self) -> str:
        assert self.endpoint_url.host
        return self.endpoint_url.host


@dataclass(frozen=True)
class Config:
    server: ServerConfig
    upstream_registry: UpstreamRegistryConfig


class EnvironConfigFactory:
    def __init__(self, environ: Optional[Dict[str, str]] = None) -> None:
        self._environ = environ or os.environ

    def create_server(self) -> ServerConfig:
        port = int(os.environ.get('NP_REGISTRY_API_PORT', ServerConfig.port))
        return ServerConfig(port=port)  # type: ignore

    def create_upstream_registry(self) -> UpstreamRegistryConfig:
        endpoint_url = URL(self._environ['NP_REGISTRY_UPSTREAM_URL'])
        project = self._environ['NP_REGISTRY_UPSTREAM_PROJECT']
        token_endpoint_url = URL(
            self._environ['NP_REGISTRY_UPSTREAM_TOKEN_URL'])
        token_endpoint_username = self._environ[
            'NP_REGISTRY_UPSTREAM_TOKEN_USERNAME']
        token_endpoint_password = self._environ[
            'NP_REGISTRY_UPSTREAM_TOKEN_PASSWORD']
        return UpstreamRegistryConfig(  # type: ignore
            endpoint_url=endpoint_url,
            project=project,
            token_endpoint_url=token_endpoint_url,
            token_endpoint_username=token_endpoint_username,
            token_endpoint_password=token_endpoint_password,
            )

    def create(self) -> Config:
        server_config = self.create_server()
        upstream_registry_config = self.create_upstream_registry()
        return Config(  # type: ignore
            server=server_config,
            upstream_registry=upstream_registry_config)
