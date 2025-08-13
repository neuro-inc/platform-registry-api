import time
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import iso8601
from aiohttp import BasicAuth, ClientSession
from aiohttp.hdrs import AUTHORIZATION
from neuro_auth_client.bearer_auth import BearerAuth
from yarl import URL

from .cache import ExpiringCache


class AbstractAuthStrategy(ABC):
    @abstractmethod
    async def get_headers(self, scopes: Sequence[str] = ()) -> dict[str, str]:
        """Return headers for authentication."""
        raise NotImplementedError


class BasicAuthStrategy(AbstractAuthStrategy):
    def __init__(self, *, username: str, password: str) -> None:
        self._username = username
        self._password = password

    async def get_headers(self, scopes: Sequence[str] = ()) -> dict[str, str]:
        auth = BasicAuth(login=self._username, password=self._password)
        return {str(AUTHORIZATION): auth.encode()}


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
    ) -> "OAuthToken":
        return OAuthToken(
            access_token=cls._parse_access_token(payload),
            expires_at=cls._parse_expires_at(
                payload,
                default_expires_in=default_expires_in,
                expiration_ratio=expiration_ratio,
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
    ) -> float:
        expires_in = payload.get("expires_in", default_expires_in)
        issued_at_str = payload.get("issued_at")
        if issued_at_str:
            issued_at = iso8601.parse_date(issued_at_str).timestamp()
        else:
            issued_at = time.time()
        return issued_at + expires_in * expiration_ratio


class OAuthStrategy(AbstractAuthStrategy):
    def __init__(
        self,
        *,
        client: ClientSession,
        token_url: URL,
        token_service: str,
        token_username: str,
        token_password: str,
    ) -> None:
        self._client = client
        self._token_url = token_url.with_query({"service": token_service})
        self._auth = BasicAuth(login=token_username, password=token_password)
        self._cache = ExpiringCache[dict[str, str]]()

    async def get_token(self, scopes: Sequence[str] = ()) -> OAuthToken:
        url = self._token_url
        if scopes:
            url = url.update_query([("scope", s) for s in scopes])
        async with self._client.get(url, auth=self._auth) as response:
            # check the status code, raise exceptions
            payload = await response.json()
        return OAuthToken.create_from_payload(payload)

    async def get_headers(self, scopes: Sequence[str] = ()) -> dict[str, str]:
        key = " ".join(scopes)
        headers = self._cache.get(key)
        if headers is None:
            token = await self.get_token(scopes)
            headers = {str(AUTHORIZATION): BearerAuth(token.access_token).encode()}
            self._cache.put(key, headers, token.expires_at)
        return dict(headers)
