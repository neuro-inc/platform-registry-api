import time
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Self

import iso8601
from aiobotocore.client import AioBaseClient
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


@dataclass(frozen=True)
class AWSECRAuthToken:
    token: str
    expires_at: float

    @classmethod
    def create_from_payload(
        cls,
        payload: dict[str, Any],
        *,
        expiration_ratio: float = 0.75,
    ) -> Self:
        try:
            token_payload = payload["authorizationData"][0]
            token = token_payload["authorizationToken"]
            issued_at = time.time()
            expires_in = token_payload["expiresAt"].timestamp() - issued_at
            expires_at = issued_at + expires_in * expiration_ratio
        except (KeyError, IndexError, AttributeError, TypeError) as exc:
            raise ValueError("invalid payload") from exc
        if issued_at >= expires_at:
            raise ValueError("already expired")
        return cls(token=token, expires_at=expires_at)


class AWSECRAuthStrategy(AbstractAuthStrategy):
    def __init__(self, client: AioBaseClient) -> None:
        self._client = client
        self._cache = ExpiringCache[dict[str, str]]()

    async def _get_token(self) -> AWSECRAuthToken:
        payload = await self._client.get_authorization_token()
        return AWSECRAuthToken.create_from_payload(payload)

    async def get_headers(self, scopes: Sequence[str] = ()) -> dict[str, str]:
        scope = "*"
        headers = self._cache.get(scope)
        if headers is None:
            token = await self._get_token()
            headers = {str(AUTHORIZATION): f"Basic {token.token}"}
            self._cache.put(scope, headers, token.expires_at)
        return dict(headers)

    async def create_repo(self, repo: str) -> None:
        try:
            await self._client.create_repository(repositoryName=repo)
        except self._client.exceptions.RepositoryAlreadyExistsException:
            pass

    async def convert_upstream_response(
        self, upstream_response: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        response_metadata = upstream_response.pop("ResponseMetadata")
        failures = upstream_response.pop("failures", [])
        assert response_metadata["HTTPStatusCode"] == 200
        content: dict[str, Any] = upstream_response
        if len(failures) == 0:
            status = 202
        else:
            failure = failures[0]
            if failure["failureCode"] == "ImageNotFound":
                status = 404
                content = {
                    "errors": [
                        {
                            "code": "NAME_INVALID",
                            "message": "Invalid image name",
                            "detail": failure["failureReason"],
                        }
                    ]
                }
            elif failure["failureCode"] == "RepositoryNotFound":
                status = 404
                content = {
                    "errors": [
                        {
                            "code": "NAME_UNKNOWN",
                            "message": "Repository name not known to registry",
                            "detail": failure["failureReason"],
                        }
                    ]
                }
            else:
                status = 500
                content = {
                    "errors": [
                        {
                            "code": 0,
                            "message": failure["failureCode"],
                            "detail": failure["failureReason"],
                        }
                    ]
                }

        content.pop("failures", None)
        content.pop("ResponseMetadata", None)
        content.pop("repository", None)
        return (status, content)
