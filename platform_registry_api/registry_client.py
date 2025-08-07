import asyncio
import base64
import json
import logging
from collections import defaultdict
from collections.abc import AsyncIterator
from types import TracebackType
from typing import Self

import aiohttp
from yarl import URL


LOGGER = logging.getLogger(__name__)


class RegistryApiException(Exception):
    def __init__(self, *, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class RegistryApiClient:
    def __init__(
        self,
        url: URL,
        token: str,
        del_sem_size: int = 5,
        timeout: aiohttp.ClientTimeout = aiohttp.client.DEFAULT_TIMEOUT,
        trace_configs: list[aiohttp.TraceConfig] | None = None,
    ):
        self._url = url
        self._token = token
        self._timeout = timeout
        self._trace_configs = trace_configs
        self._sem = asyncio.Semaphore(del_sem_size)

    @property
    def _v2_url(self) -> URL:
        return self._url / "v2"

    def _v2_catalog_url(self) -> URL:
        return self._v2_url / "_catalog"

    def _v2_tags_list_url(self, image: str) -> URL:
        return self._v2_url / image / "tags" / "list"

    def _v2_image_manifests_tag_url(self, image: str, tag: str) -> URL:
        return self._v2_url / image / "manifests" / tag

    def _v2_image_manifests_digest_url(self, image: str, digest: str) -> URL:
        return self._v2_url / image / "manifests" / digest

    async def __aenter__(self) -> Self:
        self._client = self._create_http_client()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    def _create_http_client(self) -> aiohttp.ClientSession:
        return aiohttp.ClientSession(
            headers=self.default_headers,
            timeout=self._timeout,
            trace_configs=self._trace_configs,
            raise_for_status=raise_for_status,
        )

    async def aclose(self) -> None:
        assert self._client
        await self._client.close()

    def _is_upstream_gar(self) -> bool:
        assert self._url.host
        return self._url.host.endswith(".pkg.dev")

    def _get_token_identity(self) -> str:
        payload_b64 = self._token.split(".")[1]
        padding = "=" * (-len(payload_b64) % 4)
        payload_b64 += padding
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        return json.loads(payload_bytes)["identity"]

    @property
    def default_headers(self) -> dict[str, str]:
        return {
            "Authorization": "Basic "
            + base64.b64encode(
                f"{self._get_token_identity()}:{self._token}".encode()
            ).decode()
        }

    async def list_images(
        self, org: str, project: str, page_size: int = 1000
    ) -> AsyncIterator[str]:
        url = self._v2_catalog_url().with_query(n=page_size)
        while True:
            async with self._client.get(url) as response:
                response_json = await response.json()

                if not response_json.get("repositories"):
                    break

                for image in response_json["repositories"]:
                    if image.startswith(f"{org}/{project}/"):
                        yield image

                url = response.links.get("next", {}).get("url")  # type: ignore
                if not url:
                    break
                url = url.update_query(n=page_size)

    async def image_tags_list(self, image: str) -> list[str]:
        async with self._client.get(self._v2_tags_list_url(image)) as response:
            response_json = await response.json()
            return response_json["tags"] or []

    async def image_digest(self, image: str, tag: str) -> str:
        headers = self.default_headers
        headers["Accept"] = "application/vnd.docker.distribution.manifest.v2+json"
        async with self._client.get(
            self._v2_image_manifests_tag_url(image, tag),
            headers=headers,
        ) as response:
            return response.headers["Docker-Content-Digest"]

    async def delete_tag(self, image: str, tag: str) -> None:
        async with self._sem:
            async with self._client.delete(
                self._v2_image_manifests_tag_url(image, tag)
            ) as response:
                assert response.status == 202

    async def delete_image_manifest(
        self, image: str, digest: str, tags: list[str]
    ) -> None:
        async with self._sem:
            if self._is_upstream_gar():
                # GAR requires deleting tags before deleting the image manifest
                await asyncio.gather(*[self.delete_tag(image, tag) for tag in tags])

            async with self._client.delete(
                self._v2_image_manifests_digest_url(image, digest)
            ) as response:
                assert response.status == 202

    async def _get_images_for_delete(
        self, org: str, project: str
    ) -> AsyncIterator[tuple[str, str, list[str]]]:
        async for image in self.list_images(org, project):
            digest_tags = defaultdict(list)
            for tag in await self.image_tags_list(image):
                digest = await self.image_digest(image, tag)
                digest_tags[digest].append(tag)
            for digest, tags in digest_tags.items():
                yield image, digest, tags

    async def delete_project_images(self, org: str, project: str) -> None:
        await asyncio.gather(
            *[
                self.delete_image_manifest(image, digest, tags)
                async for image, digest, tags in self._get_images_for_delete(
                    org, project
                )
            ]
        )


async def raise_for_status(response: aiohttp.ClientResponse) -> None:
    exc_text = None
    match response.status:
        case 401:
            exc_text = "Platform Registry: Unauthorized"
        case 402:
            exc_text = "Platform Registry: Payment Required"
        case 403:
            exc_text = "Platform Registry: Forbidden"
        case 404:
            exc_text = "Platform Registry: Not Found"
        case _ if not 200 <= response.status < 300:
            text = await response.text()
            exc_text = (
                f"Platform Registry api response status is not 2xx. "
                f"Status: {response.status} Response: {text}"
            )
    if exc_text:
        raise RegistryApiException(code=response.status, message=exc_text)
    return
