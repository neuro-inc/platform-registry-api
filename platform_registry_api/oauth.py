import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

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
        payload: dict[str, Any],
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
    def _parse_access_token(cls, payload: dict[str, Any]) -> str:
        access_token = payload.get("token") or payload.get("access_token")
        if not access_token:
            raise ValueError("no access token")
        return access_token

    @classmethod
    def _parse_expires_at(
        cls,
        payload: dict[str, Any],
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

    async def get_token(self, scopes: Sequence[str] = ()) -> OAuthToken:
        url = self._url
        if scopes:
            url = url.update_query([("scope", s) for s in scopes])
        print(2222222222, url, self._auth)
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
        self._cache = ExpiringCache[dict[str, str]](time_factory=time_factory)

    async def _get_headers(self, scopes: Sequence[str] = ()) -> dict[str, str]:
        key = " ".join(scopes)
        headers = self._cache.get(key)
        if headers is None:
            token = await self._client.get_token(scopes)
            headers = {str(AUTHORIZATION): BearerAuth(token.access_token).encode()}
            self._cache.put(key, headers, token.expires_at)
        return dict(headers)

    async def get_headers_for_version(self) -> dict[str, str]:
        return await self._get_headers()

    async def get_headers_for_catalog(self) -> dict[str, str]:
        return await self._get_headers([self._registry_catalog_scope])

    async def get_headers_for_repo(
        self, repo: str, mounted_repo: str = ""
    ) -> dict[str, str]:
        scopes = []
        scopes.append(self._repository_scope_template.format(repo=repo))
        if mounted_repo:
            scopes.append(self._repository_scope_template.format(repo=mounted_repo))
        return await self._get_headers(scopes)
