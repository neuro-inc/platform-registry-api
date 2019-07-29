import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import iso8601
from aiohttp import BasicAuth, ClientSession
from aiohttp.hdrs import AUTHORIZATION
from neuro_auth_client.bearer_auth import BearerAuth
from yarl import URL

from .cache import ExpiringCache
from .config import UpstreamRegistryConfig
from .typedefs import TimeFactory
from .upstream import Upstream


@dataclass(frozen=True)
class OAuthToken:
    access_token: str
    expires_at: float

    @classmethod
    def create_from_payload(
        cls,
        payload: Dict[str, Any],
        *,
        default_expires_in: int = 60,
        expiration_ratio: float = 0.75,
        time_factory: TimeFactory = time.time,
    ) -> "OAuthToken":
        return OAuthToken(
            access_token=cls._parse_access_token(payload),
            expires_at=cls._parse_expires_at(
                payload,
                default_expires_in=default_expires_in,
                expiration_ratio=expiration_ratio,
                time_factory=time_factory,
            ),
        )

    @classmethod
    def _parse_access_token(cls, payload: Dict[str, Any]) -> str:
        access_token = payload.get("token") or payload.get("access_token")
        if not access_token:
            raise ValueError("no access token")
        return access_token

    @classmethod
    def _parse_expires_at(
        cls,
        payload: Dict[str, Any],
        *,
        default_expires_in: int,
        expiration_ratio: float,
        time_factory: TimeFactory,
    ) -> float:
        expires_in = payload.get("expires_in", default_expires_in)
        issued_at_str = payload.get("issued_at")
        if issued_at_str:
            issued_at = iso8601.parse_date(issued_at_str).timestamp()
        else:
            issued_at = time_factory()
        return issued_at + expires_in * expiration_ratio


class OAuthClient:
    def __init__(
        self,
        *,
        client: ClientSession,
        url: URL,
        service: str,
        username: str,
        password: str,
        time_factory: TimeFactory = time.time,
    ) -> None:
        self._client = client
        self._url = url.with_query({"service": service})
        self._auth = BasicAuth(login=username, password=password)
        self._time_factory = time_factory

    async def get_token(self, scope: Optional[str] = None) -> OAuthToken:
        url = self._url
        if scope is not None:
            url = url.update_query({"scope": scope})
        async with self._client.get(url, auth=self._auth) as response:
            # TODO: check the status code
            # TODO: raise exceptions
            payload = await response.json()
        return OAuthToken.create_from_payload(payload, time_factory=self._time_factory)


class OAuthUpstream(Upstream):
    def __init__(
        self,
        *,
        client: OAuthClient,
        registry_catalog_scope: str = (
            UpstreamRegistryConfig.token_registry_catalog_scope
        ),
        repository_scope_actions: str = (
            UpstreamRegistryConfig.token_repository_scope_actions
        ),
        time_factory: TimeFactory = time.time,
    ) -> None:
        self._client = client
        self._registry_catalog_scope = registry_catalog_scope
        self._repository_scope_template = (
            "repository:{repo}:" + repository_scope_actions
        )
        self._cache = ExpiringCache[Dict[str, str]](time_factory=time_factory)

    async def _get_headers(self, scope: Optional[str] = None) -> Dict[str, str]:
        headers = self._cache.get(scope)
        if headers is None:
            token = await self._client.get_token(scope)
            headers = {str(AUTHORIZATION): BearerAuth(token.access_token).encode()}
            self._cache.put(scope, headers, token.expires_at)
        return dict(headers)

    async def get_headers_for_version(self) -> Dict[str, str]:
        return await self._get_headers()

    async def get_headers_for_catalog(self) -> Dict[str, str]:
        return await self._get_headers(self._registry_catalog_scope)

    async def get_headers_for_repo(self, repo: str) -> Dict[str, str]:
        scope = self._repository_scope_template.format(repo=repo)
        return await self._get_headers(scope)
