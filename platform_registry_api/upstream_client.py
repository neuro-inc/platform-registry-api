import asyncio
import logging
from collections import defaultdict
from collections.abc import AsyncIterator, Sequence
from types import TracebackType
from typing import Self

import aiohttp
from aiohttp.web import Request, StreamResponse
from yarl import URL

from .auth_strategies import AbstractAuthStrategy, BasicAuthStrategy, OAuthStrategy
from .config import UpstreamRegistryConfig


LOGGER = logging.getLogger(__name__)


class UpstreamApiException(Exception):
    def __init__(self, *, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class UpstreamV2ApiClient:
    def __init__(self, config: UpstreamRegistryConfig) -> None:
        self._url = config.endpoint_url
        self._repo_prefix = (
            URL(config.project) / config.repo / ""
        )  # Ensure slash at the end

        self._sem = asyncio.Semaphore(5)
        self._sock_connect_timeout_s = config.sock_connect_timeout_s
        self._sock_read_timeout_s = config.sock_read_timeout_s
        self._config = config

    def _upstream_repo_name(self, repo: str) -> str:
        if repo.startswith(str(self._repo_prefix)):
            return repo
        return str(self._repo_prefix / repo)

    def _registry_repo_name(self, repo: str) -> str:
        if repo.startswith(str(self._repo_prefix)):
            return repo[len(str(self._repo_prefix)) :]
        return repo

    @property
    def _v2_url(self) -> URL:
        return self._url / "v2/"

    def _v2_catalog_url(self) -> URL:
        return self._v2_url / "_catalog"

    def _v2_tags_list_url(self, repo: str) -> URL:
        return self._v2_url / self._upstream_repo_name(repo) / "tags" / "list"

    def _v2_image_manifests_tag_url(self, repo: str, tag: str) -> URL:
        return self._v2_url / self._upstream_repo_name(repo) / "manifests" / tag

    def _v2_image_manifests_digest_url(self, repo: str, digest: str) -> URL:
        return self._v2_url / self._upstream_repo_name(repo) / "manifests" / digest

    def _v2_repo_with_suffix(self, repo: str, suffix: str) -> URL:
        suffix_url = URL(suffix)
        return self._v2_url / self._upstream_repo_name(repo) / suffix_url.path

    def _get_catalog_scopes(self) -> Sequence[str]:
        return ("registry:catalog:*",)

    def _get_repo_scopes(
        self, repo: str, mounted_repo: str | None = None
    ) -> Sequence[str]:
        scopes = []
        scopes.append(f"repository:{self._upstream_repo_name(repo)}:*")
        if mounted_repo:
            scopes.append(f"repository:{self._upstream_repo_name(mounted_repo)}:*")
        return scopes

    async def get_auth_strategy(self) -> AbstractAuthStrategy:
        if self._config.is_basic:
            return BasicAuthStrategy(
                username=self._config.basic_username,
                password=self._config.basic_password,
            )
        if self._config.is_oauth:
            return OAuthStrategy(
                client=self._client,
                token_url=self._config.token_endpoint_url,
                token_service=self._config.token_service,
                token_username=self._config.token_endpoint_username,
                token_password=self._config.token_endpoint_password,
            )
        ext_txt = f"Unsupported upstream type: {self._config.type}"
        raise Exception(ext_txt)

    async def __aenter__(self) -> Self:
        self._client = await self._create_http_client()
        self._auth_strategy = await self.get_auth_strategy()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def _create_http_client(self) -> aiohttp.ClientSession:
        return aiohttp.ClientSession(raise_for_status=raise_for_status)

    async def aclose(self) -> None:
        assert self._client
        await self._client.close()

    def _is_upstream_gar(self) -> bool:
        assert self._url.host
        return self._url.host.endswith(".pkg.dev")

    async def auth_headers(self, scopes: Sequence[str] = ()) -> dict[str, str]:
        return await self._auth_strategy.get_headers(scopes)

    async def v2(self) -> dict[str, str]:
        headers = await self.auth_headers()
        async with self._client.get(self._v2_url, headers=headers) as response:
            return await response.json()

    async def list_images(
        self, org: str, project: str, n: int | None = None, last: str | None = None
    ) -> AsyncIterator[str]:
        page_size = n or self._config.max_catalog_entries
        url = self._v2_catalog_url().with_query(n=page_size)
        if last:
            url = url.update_query(last=last)
        scopes = self._get_catalog_scopes()
        while True:
            headers = await self.auth_headers(scopes)
            async with self._client.get(url, headers=headers) as response:
                response_json = await response.json()

                if not response_json.get("repositories"):
                    break

                for image in response_json["repositories"]:
                    if image.startswith(str(self._repo_prefix / org / project)):
                        yield image[len(str(self._repo_prefix)) :]

                url = response.links.get("next", {}).get("url")  # type: ignore
                if not url:
                    break
                url = url.update_query(n=page_size)

    async def image_tags_list(self, repo: str) -> list[str]:
        scopes = self._get_repo_scopes(repo)
        headers = await self.auth_headers(scopes)
        async with self._client.get(
            self._v2_tags_list_url(repo), headers=headers
        ) as response:
            response_json = await response.json()
            return response_json["tags"] or []

    async def image_digest(self, repo: str, tag: str) -> str:
        scopes = self._get_repo_scopes(repo)
        headers = await self.auth_headers(scopes)
        headers["Accept"] = "application/vnd.docker.distribution.manifest.v2+json"
        async with self._client.get(
            self._v2_image_manifests_tag_url(repo, tag),
            headers=headers,
        ) as response:
            return response.headers["Docker-Content-Digest"]

    async def delete_tag(self, repo: str, tag: str) -> None:
        async with self._sem:
            scopes = self._get_repo_scopes(repo)
            headers = await self.auth_headers(scopes)
            async with self._client.delete(
                self._v2_image_manifests_tag_url(repo, tag), headers=headers
            ) as response:
                assert response.status == 202

    async def delete_image_manifest(
        self, repo: str, digest: str, tags: list[str]
    ) -> None:
        async with self._sem:
            if self._is_upstream_gar():
                # GAR requires deleting tags before deleting the repo manifest
                await asyncio.gather(*[self.delete_tag(repo, tag) for tag in tags])
            scopes = self._get_repo_scopes(repo)
            headers = await self.auth_headers(scopes)
            async with self._client.delete(
                self._v2_image_manifests_digest_url(repo, digest), headers=headers
            ) as response:
                assert response.status == 202

    async def _get_images_for_delete(
        self, org: str, project: str
    ) -> AsyncIterator[tuple[str, str, list[str]]]:
        async for repo in self.list_images(org, project):
            digest_tags = defaultdict(list)
            for tag in await self.image_tags_list(repo):
                digest = await self.image_digest(repo, tag)
                digest_tags[digest].append(tag)
            for digest, tags in digest_tags.items():
                yield repo, digest, tags

    async def delete_project_images(self, org: str, project: str) -> None:
        await asyncio.gather(
            *[
                self.delete_image_manifest(repo, digest, tags)
                async for repo, digest, tags in self._get_images_for_delete(
                    org, project
                )
            ]
        )

    def _is_pull_request(self, request: Request) -> bool:
        return request.method in ("HEAD", "GET")

    def _client_timeout(self, request: Request) -> aiohttp.ClientTimeout:
        sock_read_timeout_s = None
        if self._is_pull_request(request):
            sock_read_timeout_s = self._sock_read_timeout_s
        return aiohttp.ClientTimeout(
            total=None,
            connect=None,
            sock_connect=self._sock_connect_timeout_s,
            sock_read=sock_read_timeout_s,
        )

    async def proxy_request(self, request: Request) -> StreamResponse:
        """
        This method works only for /{repo:.+}/{path_suffix:(tags|manifests|blobs)/.*
        """
        repo = request.match_info["repo"]
        path_suffix = request.match_info["path_suffix"]

        headers = request.headers.copy()
        for name in ("Host", "Transfer-Encoding", "Connection"):
            headers.pop(name, None)

        if request.method == "HEAD":
            data = None
        else:
            data = request.content.iter_any()

        params = dict(request.query)
        mounted_repo = params.get("from")
        if mounted_repo:
            upstream_mounted_repo = self._upstream_repo_name(mounted_repo)
            params["from"] = upstream_mounted_repo
        scopes = self._get_repo_scopes(repo, mounted_repo)
        auth_headers = await self.auth_headers(scopes)
        headers.update(auth_headers)
        url = self._v2_repo_with_suffix(repo, path_suffix)
        if params:
            url = url.update_query(params)

        async with self._client.request(
            method=request.method,
            url=url,
            headers=headers,
            skip_auto_headers=("Content-Type",),
            data=data,
            timeout=self._client_timeout(request),
        ) as client_response:
            response_headers = client_response.headers.copy()
            for name in ("Transfer-Encoding", "Content-Encoding", "Connection"):
                response_headers.pop(name, None)

            if "Location" in response_headers:
                location_url = URL(response_headers["Location"])
                if location_url.host:
                    response_headers["Location"] = str(
                        request.url.origin().join(location_url.relative())
                    )
                else:
                    response_headers["Location"] = str(self._url.join(location_url))

            response = StreamResponse(
                status=client_response.status, headers=response_headers
            )

            await response.prepare(request)

            async for chunk, _ in client_response.content.iter_chunks():
                if chunk:
                    await response.write(chunk)
                else:
                    break

            await response.write_eof()
            return response


async def raise_for_status(response: aiohttp.ClientResponse) -> None:
    if not 200 <= response.status < 300:
        raise UpstreamApiException(code=response.status, message=await response.text())
    return
