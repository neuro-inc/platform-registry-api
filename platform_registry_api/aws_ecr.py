import logging
import time
from dataclasses import dataclass
from typing import Any

from aiobotocore.client import AioBaseClient
from aiohttp.hdrs import AUTHORIZATION
from neuro_logging import trace

from .cache import ExpiringCache
from .typedefs import TimeFactory
from .upstream import Upstream


logger = logging.getLogger(__name__)


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
        self._cache = ExpiringCache[dict[str, str]](time_factory=time_factory)

    async def _get_token(self) -> AWSECRAuthToken:
        payload = await self._client.get_authorization_token()
        return AWSECRAuthToken.create_from_payload(
            payload, time_factory=self._time_factory
        )

    async def _get_headers(self) -> dict[str, str]:
        scope = "*"
        headers = self._cache.get(scope)
        if headers is None:
            token = await self._get_token()
            headers = {str(AUTHORIZATION): f"Basic {token.token}"}
            self._cache.put(scope, headers, token.expires_at)
        return dict(headers)

    @trace
    async def create_repo(self, repo: str) -> None:
        try:
            await self._client.create_repository(repositoryName=repo)
        except self._client.exceptions.RepositoryAlreadyExistsException:
            pass

    @trace
    async def get_headers_for_version(self) -> dict[str, str]:
        return await self._get_headers()

    @trace
    async def get_headers_for_catalog(self) -> dict[str, str]:
        return await self._get_headers()

    @trace
    async def get_headers_for_repo(
        self, repo: str, mounted_repo: str = ""
    ) -> dict[str, str]:
        return await self._get_headers()

    async def convert_upstream_response(
        self, upstream_response: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        response_metadata = upstream_response.pop("ResponseMetadata")
        failures = upstream_response.pop("failures", [])
        assert response_metadata["HTTPStatusCode"] == 200
        content: dict[str, Any] = upstream_response
        logger.debug("content: %s", content)
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
        logger.debug("content after pop: %s", content)
        return (status, content)
