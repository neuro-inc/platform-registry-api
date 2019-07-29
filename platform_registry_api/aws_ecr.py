import time
from dataclasses import dataclass
from typing import Any, Dict, Set

from aiobotocore.client import AioBaseClient
from aiohttp.hdrs import AUTHORIZATION

from .cache import ExpiringCache
from .typedefs import TimeFactory
from .upstream import Upstream


@dataclass(frozen=True)
class AWSECRAuthToken:
    token: str
    expires_at: float

    @classmethod
    def create_from_payload(
        cls,
        payload: Dict[str, Any],
        *,
        expiration_ratio: float = 0.75,
        time_factory: TimeFactory = time.time,
    ) -> "AWSECRAuthToken":
        try:
            token_payload = payload["authorizationData"][0]
            token = token_payload["authorizationToken"]
            issued_at = time_factory()
            expires_in = token_payload["expiresAt"].timestamp() - issued_at
            expires_at = issued_at + expires_in * expiration_ratio
        except (KeyError, IndexError, AttributeError, TypeError) as exc:
            raise ValueError("invalid payload") from exc
        if issued_at >= expires_at:
            raise ValueError("already expired")
        return cls(token=token, expires_at=expires_at)


class AWSECRUpstream(Upstream):
    def __init__(
        self, client: AioBaseClient, time_factory: TimeFactory = time.time
    ) -> None:
        self._client = client
        self._time_factory = time_factory
        self._cache = ExpiringCache[Dict[str, str]](time_factory=time_factory)
        self._existing_repos: Set[str] = set()

    async def _get_token(self) -> AWSECRAuthToken:
        payload = await self._client.get_authorization_token()
        return AWSECRAuthToken.create_from_payload(
            payload, time_factory=self._time_factory
        )

    async def _get_headers(self) -> Dict[str, str]:
        scope = "*"
        headers = self._cache.get(scope)
        if headers is None:
            token = await self._get_token()
            headers = {str(AUTHORIZATION): f"Basic {token.token}"}
            self._cache.put(scope, headers, token.expires_at)
        return dict(headers)

    async def create_repo(self, repo: str) -> None:
        if repo in self._existing_repos:
            return

        try:
            await self._client.create_repository(repositoryName=repo)
        except self._client.exceptions.RepositoryAlreadyExistsException:
            pass

        self._existing_repos.add(repo)

    async def get_headers_for_version(self) -> Dict[str, str]:
        return await self._get_headers()

    async def get_headers_for_catalog(self) -> Dict[str, str]:
        return await self._get_headers()

    async def get_headers_for_repo(self, repo: str) -> Dict[str, str]:
        return await self._get_headers()