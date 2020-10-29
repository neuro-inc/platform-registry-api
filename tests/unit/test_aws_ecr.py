from datetime import datetime
from typing import Any, AsyncIterator, Awaitable, Callable, Dict

import botocore
import pytest
from aiohttp.test_utils import TestServer as _TestServer
from aiohttp.web import Application, Request, StreamResponse, json_response
from yarl import URL

from platform_registry_api.api import create_aws_ecr_upstream
from platform_registry_api.aws_ecr import AWSECRAuthToken, AWSECRUpstream
from platform_registry_api.config import UpstreamRegistryConfig
from platform_registry_api.upstream import Upstream


_TestServerFactory = Callable[[Application], Awaitable[_TestServer]]


class TestAWSECRAuthToken:
    @pytest.mark.parametrize(
        "payload",
        (
            {},
            {"authorizationData": []},
            {"authorizationData": [{"authorizationToken": "testtoken"}]},
            {
                "authorizationData": [
                    {"authorizationToken": "testtoken", "expiresAt": "invalid"}
                ]
            },
            {"authorizationData": 123},
            {"authorizationData": {}},
            {"authorizationData": [123]},
            {"authorizationData": [[]]},
            {"authorizationData": [{}]},
            {"authorizationData": [{"authorizationToken": 123}]},
            {
                "authorizationData": [
                    {"authorizationToken": "testtoken", "expiresAt": 123}
                ]
            },
        ),
    )
    def test_create_from_payload_invalid_payload(self, payload: Dict[str, Any]) -> None:
        with pytest.raises(ValueError, match="invalid payload"):
            AWSECRAuthToken.create_from_payload(payload)

    def test_create_from_payload_expires_at(self) -> None:
        token = AWSECRAuthToken.create_from_payload(
            {
                "authorizationData": [
                    {
                        "authorizationToken": "testtoken",
                        "expiresAt": datetime.fromtimestamp(1560000100.0),
                    }
                ]
            },
            time_factory=(lambda: 1560000000.0),
        )
        assert token == AWSECRAuthToken(token="testtoken", expires_at=1560000075.0)

    def test_create_from_payload_already_expired(self) -> None:
        with pytest.raises(ValueError, match="already expired"):
            AWSECRAuthToken.create_from_payload(
                {
                    "authorizationData": [
                        {
                            "authorizationToken": "testtoken",
                            "expiresAt": datetime.fromtimestamp(1560000100.0),
                        }
                    ]
                },
                time_factory=(lambda: 1560000100.0),
            )


class _TestAWSECRUpstreamHandler:
    def __init__(self) -> None:
        self._test_repo_is_created = False

    async def handle(self, request: Request) -> StreamResponse:
        target = request.headers["X-Amz-Target"]
        if target == "AmazonEC2ContainerRegistry_V20150921.GetAuthorizationToken":
            return await self._handle_get_auth_token(request)
        elif target == "AmazonEC2ContainerRegistry_V20150921.CreateRepository":
            return await self._handle_create_repo(request)
        return json_response({}, status=500)

    async def _handle_get_auth_token(self, request: Request) -> StreamResponse:
        return json_response(
            {
                "authorizationData": [
                    {"authorizationToken": "test_token", "expiresAt": 1560000100.0}
                ]
            }
        )

    def _already_exist_response(self, repo: str) -> StreamResponse:
        return json_response(
            {
                "__type": "RepositoryAlreadyExistsException",
                "message": (
                    f"The repository with name '{repo}' "
                    "already exists in the registry with id '1234567890'"
                ),
            },
            status=400,
        )

    async def _handle_create_repo(self, request: Request) -> StreamResponse:
        payload = await request.json()
        repo = payload["repositoryName"]
        if repo == "test_repo":
            if self._test_repo_is_created:
                return self._already_exist_response(repo)
            self._test_repo_is_created = True
            return json_response({})
        if repo == "test_repo_already_exists":
            return self._already_exist_response(repo)
        return json_response({}, status=500)


class TestAWSECRUpstream:
    @pytest.fixture
    async def upstream_server(
        self, aiohttp_server: _TestServerFactory
    ) -> AsyncIterator[URL]:
        app = Application()
        handler = _TestAWSECRUpstreamHandler()
        app.router.add_post("/", handler.handle)
        server = await aiohttp_server(app)
        yield server.make_url("")

    @pytest.fixture
    async def upstream(self, upstream_server: URL) -> AsyncIterator[Upstream]:
        config = UpstreamRegistryConfig(endpoint_url=URL(), project="test_project")
        async with create_aws_ecr_upstream(
            config=config,
            endpoint_url=str(upstream_server),
            time_factory=(lambda: 1560000000.0),
            use_ssl=False,
            region_name="us-east-1",
            aws_access_key_id="test_access_key_id",
            aws_secret_access_key="test_secret_access_key",
        ) as up:
            yield up

    @pytest.mark.asyncio
    async def test_create_repo(self, upstream: Upstream) -> None:
        # simply should not fail
        await upstream.create_repo("test_repo")
        await upstream.create_repo("test_repo")

    @pytest.mark.asyncio
    async def test_create_repo_already_exists(self, upstream: Upstream) -> None:
        await upstream.create_repo("test_repo_already_exists")

    @pytest.mark.asyncio
    async def test_create_repo_unexpected(self, upstream: Upstream) -> None:
        with pytest.raises(botocore.exceptions.ClientError):
            await upstream.create_repo("test_invalid_repo")

    @pytest.mark.asyncio
    async def test_get_headers(self, upstream: Upstream) -> None:
        headers = await upstream.get_headers_for_version()
        assert headers == {"Authorization": "Basic test_token"}

        headers = await upstream.get_headers_for_catalog()
        assert headers == {"Authorization": "Basic test_token"}

        headers = await upstream.get_headers_for_repo("test_repo")
        assert headers == {"Authorization": "Basic test_token"}

    @pytest.mark.asyncio
    async def test_get_image_delete_response_success(
        self, upstream: AWSECRUpstream
    ) -> None:
        upstream_response: Dict[str, Any] = {
            "ResponseMetadata": {"HTTPStatusCode": 200},
            "failures": [],
        }
        response_status, response_content = await upstream.get_image_delete_response(
            upstream_response
        )
        assert response_status == 202
        assert response_content == {}

    @pytest.mark.asyncio
    async def test_get_image_delete_response_image_not_found(
        self, upstream: AWSECRUpstream
    ) -> None:
        upstream_response: Dict[str, Any] = {
            "ResponseMetadata": {"HTTPStatusCode": 200},
            "failures": [
                {"failureCode": "ImageNotFound", "failureReason": "Can't find image"}
            ],
        }
        response_status, response_content = await upstream.get_image_delete_response(
            upstream_response
        )
        assert response_status == 404
        assert response_content == {
            "errors": [
                {
                    "code": "NAME_INVALID",
                    "detail": "Can't find image",
                    "message": "Invalid image name",
                }
            ]
        }

    @pytest.mark.asyncio
    async def test_get_image_delete_response_repository_not_found(
        self, upstream: AWSECRUpstream
    ) -> None:
        upstream_response: Dict[str, Any] = {
            "ResponseMetadata": {"HTTPStatusCode": 200},
            "failures": [
                {
                    "failureCode": "RepositoryNotFound",
                    "failureReason": "Can't find repository",
                }
            ],
        }
        response_status, response_content = await upstream.get_image_delete_response(
            upstream_response
        )
        assert response_status == 404
        assert response_content == {
            "errors": [
                {
                    "code": "NAME_UNKNOWN",
                    "detail": "Can't find repository",
                    "message": "Repository name not known to registry",
                }
            ]
        }

    @pytest.mark.asyncio
    async def test_get_image_delete_response_unknown_error(
        self, upstream: AWSECRUpstream
    ) -> None:
        upstream_response: Dict[str, Any] = {
            "ResponseMetadata": {"HTTPStatusCode": 200},
            "failures": [
                {"failureCode": "Some other error", "failureReason": "Unknown error"}
            ],
        }
        response_status, response_content = await upstream.get_image_delete_response(
            upstream_response
        )
        assert response_status == 500
        assert response_content == {
            "errors": [
                {
                    "code": 0,
                    "detail": "Unknown error",
                    "message": "Some other error",
                }
            ]
        }
