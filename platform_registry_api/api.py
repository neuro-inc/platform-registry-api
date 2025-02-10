import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator, Iterable, Iterator, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, replace
from json import JSONDecodeError
from re import Pattern
from types import SimpleNamespace
from typing import Any, ClassVar, Optional

import aiobotocore.session
import aiohttp.web
import aiohttp_remotes
import botocore.exceptions
import pkg_resources
import trafaret as t
from aiohttp import ClientResponseError, ClientSession
from aiohttp.hdrs import (
    CONTENT_LENGTH,
    CONTENT_TYPE,
    LINK,
    METH_DELETE,
    METH_GET,
    METH_HEAD,
    METH_PATCH,
    METH_POST,
    METH_PUT,
)
from aiohttp.web import (
    Application,
    HTTPBadRequest,
    HTTPForbidden,
    HTTPNotFound,
    HTTPUnauthorized,
    Request,
    Response,
    StreamResponse,
)
from aiohttp_security import check_authorized, check_permission
from multidict import CIMultiDict, CIMultiDictProxy
from neuro_auth_client import AuthClient, Permission, User
from neuro_auth_client.client import ClientSubTreeViewRoot
from neuro_auth_client.security import AuthScheme, setup_security
from neuro_logging import (
    init_logging,
    setup_sentry,
    trace,
)
from yarl import URL

from platform_registry_api.helpers import check_image_catalog_permission

from .aws_ecr import AWSECRUpstream
from .basic import BasicUpstream
from .config import (
    Config,
    EnvironConfigFactory,
    UpstreamRegistryConfig,
    UpstreamType,
)
from .oauth import OAuthClient, OAuthUpstream
from .typedefs import TimeFactory
from .upstream import Upstream

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CatalogPage:
    number: int = 100
    last_token: str = ""

    def with_last_token(self, token: str) -> "CatalogPage":
        return replace(self, last_token=token)

    def with_number(self, number: int) -> "CatalogPage":
        return replace(self, number=number)

    @classmethod
    def create(cls, payload: dict[str, Any]) -> "CatalogPage":
        return cls(number=int(payload["n"]), last_token=payload.get("last", ""))

    @classmethod
    def default(cls) -> "CatalogPage":
        return cls()


CATALOG_PAGE_VALIDATOR = (
    t.Dict(
        {
            t.Key("n", default=CatalogPage.number): t.Int(gt=0),
            t.Key("last", optional=True): t.String(),
        }
    ).allow_extra("*")
    >> CatalogPage.create
)


@dataclass(frozen=True)
class RepoURL:
    repo: str
    url: URL
    mounted_repo: str = ""

    _v2_path_re: ClassVar[Pattern[str]] = re.compile(
        r"/v2/(?P<repo>.+)/(?P<path_suffix>(tags|manifests|blobs)/.*)"
    )
    _allowed_skip_perms_path_re: tuple[Pattern[str], Pattern[str]] = (
        # Urls that uses GAR and they without Authorization headers,
        # so we can't check permissions
        # /artifacts-uploads/namespaces/development-421920/
        # repositories/platform-registry-dev/uploads/AF2XiV ...
        # /v2/development-421920/platform-registry-dev/pkg/blobs/uploads/AJMTJPA ...
        re.compile(
            r"^/(artifacts-uploads|artifacts-downloads)/namespaces/(?P<project>.+)/"
            r"repositories/(?P<repo>.+)/(?P<path_suffix>(uploads|downloads))/"
            r"(?P<upload_id>[A-Za-z0-9_=-]+)"
        ),
        re.compile(r"^/v2/(?P<project>.+)/(?P<repo>.+)/pkg/(?P<path_suffix>blobs/.+)"),
    )

    @staticmethod
    def _get_match_skip_perms_path_re(url: URL) -> Optional[re.Match[str]]:
        for path_re in RepoURL._allowed_skip_perms_path_re:
            if match := path_re.fullmatch(url.path):
                return match
        return None

    @classmethod
    def from_url(cls, url: URL) -> "RepoURL":
        # validating the url
        repo, mounted_repo, _ = cls._parse(url)
        return cls(repo=repo, mounted_repo=mounted_repo, url=url)

    @classmethod
    def _parse(cls, url: URL) -> tuple[str, str, URL]:
        if match := cls._get_match_skip_perms_path_re(url):
            return (
                f"{match.group('project')}/{match.group('repo')}",
                "",
                URL(match.group("path_suffix")),
            )
        match = cls._v2_path_re.fullmatch(url.path)
        if not match:
            raise ValueError(f"unexpected path in a registry URL: {url}")
        path_suffix = URL.build(path=match.group("path_suffix"), query=url.query)
        assert not path_suffix.is_absolute()
        mounted_repo = ""
        if "blobs/uploads" in path_suffix.path and "from" in path_suffix.query:
            # Support cross repository blob mount
            mounted_repo = path_suffix.query["from"]
        return match.group("repo"), mounted_repo, path_suffix

    def allow_skip_perms(self) -> bool:
        return True if self._get_match_skip_perms_path_re(self.url) else False

    def with_project(
        self, project: str, upstream_repo: Optional[str] = None
    ) -> "RepoURL":
        _, _, url_suffix = self._parse(self.url)
        new_mounted_repo = ""
        if self.mounted_repo:
            new_mounted_repo = f"{project}/{self.mounted_repo}"
            url_suffix = url_suffix.update_query([("from", new_mounted_repo)])
        new_repo = (
            f"{project}/{upstream_repo + '/' if upstream_repo else ''}{self.repo}"
        )
        rel_url = URL(f"/v2/{new_repo}/").join(url_suffix)
        url = self.url.join(rel_url)
        # TODO: dataclasses.replace turns out out be buggy :D
        return self.__class__(repo=new_repo, mounted_repo=new_mounted_repo, url=url)

    def with_repo(self, repo: str) -> "RepoURL":
        _, _, url_suffix = self._parse(self.url)
        rel_url = URL(f"/v2/{repo}/").join(url_suffix)
        url = self.url.join(rel_url)
        # TODO: dataclasses.replace turns out out be buggy :D
        return self.__class__(repo=repo, mounted_repo=self.mounted_repo, url=url)

    def with_origin(self, origin_url: URL) -> "RepoURL":
        url = self.url
        if url.is_absolute():
            url = url.relative()
        url = origin_url.join(url)
        return self.__class__(repo=self.repo, mounted_repo=self.mounted_repo, url=url)

    def with_query(self, query: dict[str, str]) -> "RepoURL":
        query = {**self.url.query, **query}
        url = self.url.with_query(query)
        return self.__class__(repo=self.repo, mounted_repo=self.mounted_repo, url=url)


class URLFactory:
    def __init__(
        self,
        registry_endpoint_url: URL,
        upstream_endpoint_url: URL,
        upstream_project: str,
        upstream_repo: Optional[str] = None,  # for registries that have repo like GAR
    ) -> None:
        self._registry_endpoint_url = registry_endpoint_url
        self._upstream_endpoint_url = upstream_endpoint_url
        self._upstream_project = upstream_project
        self._upstream_repo = upstream_repo

    @property
    def registry_host(self) -> Optional[str]:
        return self._registry_endpoint_url.host

    @property
    def upstream_host(self) -> Optional[str]:
        return self._upstream_endpoint_url.host

    @property
    def upstream_project(self) -> str:
        return self._upstream_project

    @property
    def upstream_repo(self) -> Optional[str]:
        return self._upstream_repo

    @classmethod
    def from_config(cls, registry_endpoint_url: URL, config: Config) -> "URLFactory":
        return cls(
            registry_endpoint_url=registry_endpoint_url,
            upstream_endpoint_url=config.upstream_registry.endpoint_url,
            upstream_project=config.upstream_registry.project,
            upstream_repo=config.upstream_registry.repo,
        )

    def create_registry_version_check_url(self) -> URL:
        return self._upstream_endpoint_url.with_path("/v2/")

    def create_upstream_catalog_url(self, query: dict[str, str]) -> URL:
        return self._upstream_endpoint_url.with_path("/v2/_catalog").with_query(query)

    def create_registry_catalog_url(self, query: dict[str, str]) -> URL:
        return self._registry_endpoint_url.with_path("/v2/_catalog").with_query(query)

    def create_upstream_repo_url(self, registry_url: RepoURL) -> RepoURL:
        if registry_url.allow_skip_perms():
            return registry_url.with_origin(self._upstream_endpoint_url)
        else:
            return registry_url.with_project(
                self._upstream_project, self._upstream_repo
            ).with_origin(self._upstream_endpoint_url)

    def create_registry_repo_url(self, upstream_url: RepoURL) -> RepoURL:
        upstream_repo = upstream_url.repo
        prefix = self._upstream_project + "/"
        if not upstream_repo.startswith(prefix):
            raise ValueError(
                f"{upstream_repo!r} does not match the configured "
                f"upstream project {self._upstream_project!r}"
            )
        repo = upstream_repo[len(prefix) :]
        return upstream_url.with_repo(repo).with_origin(self._registry_endpoint_url)


class V2Handler:
    def __init__(self, app: Application, config: Config) -> None:
        self._app = app
        self._config = config
        self._upstream_registry_config = config.upstream_registry

    @property
    def _auth_client(self) -> AuthClient:
        return self._app["auth_client"]

    @property
    def _registry_client(self) -> aiohttp.ClientSession:
        return self._app["registry_client"]

    @property
    def _upstream(self) -> Upstream:
        return self._app["upstream"]

    def register(self, app: aiohttp.web.Application) -> None:
        app.add_routes(
            (
                aiohttp.web.get("/", self.handle_version_check),
                aiohttp.web.get("/_catalog", self.handle_catalog),
                aiohttp.web.get(r"/{repo:.+}/tags/list", self.handle_repo_tags_list),
            )
        )
        app.add_routes(
            aiohttp.web.route(
                method,
                r"/{repo:.+}/{path_suffix:(tags|manifests|blobs)/.*}",
                self.handle,
            )
            for method in (
                METH_HEAD,
                METH_GET,
                METH_POST,
                METH_DELETE,
                METH_PATCH,
                METH_PUT,
            )
        )

    def register_artifacts(self, app: aiohttp.web.Application) -> None:
        app.add_routes(
            aiohttp.web.route(
                method,
                r"/artifacts-{action:(uploads|downloads)}/namespaces/{project:.+}/"
                r"repositories/{repo:.+}/{path_suffix:(uploads|downloads)/?.*}",
                self.handle,
            )
            for method in (
                METH_HEAD,
                METH_GET,
                METH_POST,
                METH_DELETE,
                METH_PATCH,
                METH_PUT,
            )
        )

    def _create_url_factory(self, request: Request) -> URLFactory:
        return URLFactory.from_config(
            registry_endpoint_url=request.url.origin(), config=self._config
        )

    async def _get_user_from_request(self, request: Request) -> User:
        try:
            user_name = await check_authorized(request)
        except ValueError:
            raise HTTPBadRequest()
        except HTTPUnauthorized:
            self._raise_unauthorized()
        return User(name=user_name)

    def _raise_unauthorized(self) -> None:
        raise HTTPUnauthorized(
            headers={"WWW-Authenticate": f'Basic realm="{self._config.server.name}"'}
        )

    async def handle_version_check(self, request: Request) -> StreamResponse:
        # TODO: prevent leaking sensitive headers
        logger.debug("registry request: %s; headers: %s", request, request.headers)

        await self._get_user_from_request(request)

        url_factory = self._create_url_factory(request)
        url = url_factory.create_registry_version_check_url()
        auth_headers = await self._upstream.get_headers_for_version()
        return await self._proxy_request(
            request, url_factory=url_factory, url=url, auth_headers=auth_headers
        )

    @classmethod
    def parse_catalog_repositories(cls, payload: dict[str, Any]) -> list[str]:
        return payload.get("repositories") or []

    @classmethod
    def filter_images_1_indexed(
        cls,
        images_names: Iterable[str],
        tree: ClientSubTreeViewRoot,
        project_name: str,
        upstream_repo: Optional[str] = None,
    ) -> Iterator[tuple[int, str]]:
        upstream_repo_prefix = f"{upstream_repo}/" if upstream_repo else ""
        project_prefix = f"{project_name}/{upstream_repo_prefix}"
        len_project_prefix = len(project_prefix)
        for index, image in enumerate(images_names, 1):
            if image.startswith(project_prefix):
                image = image[len_project_prefix:]
                if check_image_catalog_permission(image, tree):
                    yield index, image
            else:
                msg = f'expected project "{project_name}" in image "{image}"'
                logger.info(f"Bad image: {msg} (skipping)")

    def _prepare_catalog_request_params(self, page: CatalogPage) -> dict[str, str]:
        params = {"n": str(page.number)}
        if page.last_token:
            params["last"] = page.last_token
        return params

    async def handle_catalog(self, request: Request) -> Response:
        logger.debug("registry request: %s; headers: %s", request, request.headers)

        page: CatalogPage = CATALOG_PAGE_VALIDATOR.check(request.query)

        logger.debug(f"requested catalog page: {page}")

        user = await self._get_user_from_request(request)
        tree = await self._auth_client.get_permissions_tree(
            user.name, f"image://{self._config.cluster_name}"
        )

        url_factory = self._create_url_factory(request)
        project_name = url_factory.upstream_project
        paging_url: Optional[URL] = url_factory.create_upstream_catalog_url(
            self._prepare_catalog_request_params(page)
        )

        auth_headers = await self._upstream.get_headers_for_catalog()
        headers = self._prepare_request_headers(request.headers, auth_headers)
        timeout = self._create_registry_client_timeout(request)

        filtered: list[str] = []
        index: int = 0
        more_images = False
        last_token_is_correct = False
        last_token: str = ""
        while paging_url and len(filtered) < page.number:
            number = max(
                page.number - len(filtered),
                self._config.upstream_registry.max_catalog_entries,
            )
            paging_url = paging_url.update_query(number=str(number))
            last_token = paging_url.query.get("last", "")
            images_list, paging_url = await self._get_next_catalog_items(
                paging_url, headers, timeout
            )
            if not images_list:
                break
            for index, image in self.filter_images_1_indexed(
                images_list, tree, project_name, url_factory.upstream_repo
            ):
                filtered.append(image)
                if len(filtered) == page.number:
                    if paging_url or index != len(images_list):
                        more_images = True
                    if index == len(images_list):
                        last_token_is_correct = True
                        if paging_url:
                            last_token = paging_url.query.get("last", "")
                        else:
                            last_token = ""
                    break

        response_headers: dict[str, str] = {}

        if more_images:
            if not last_token_is_correct:
                # We have to make one more request to get correct
                # last token from upstream
                page_exact_last = CatalogPage(number=index, last_token=last_token)
                url_exact_last = url_factory.create_upstream_catalog_url(
                    self._prepare_catalog_request_params(page_exact_last)
                )

                _, url_last_token = await self._get_next_catalog_items(
                    url_exact_last, headers, timeout
                )

                if url_last_token:
                    last_token = url_last_token.query.get("last", "")
                else:
                    last_token = ""

            if last_token:
                next_registry_url = url_factory.create_registry_catalog_url(
                    {
                        "n": str(self._config.upstream_registry.max_catalog_entries),
                        "last": last_token,
                    }
                )
                response_headers[LINK] = f'<{next_registry_url!s}>; rel="next"'

        result_dict = {"repositories": filtered}

        response = aiohttp.web.json_response(data=result_dict, headers=response_headers)

        logger.debug("registry response: %s; headers: %s", response, response.headers)

        return response

    async def _get_next_catalog_items(
        self, url: URL, headers: CIMultiDict[str], timeout: aiohttp.ClientTimeout
    ) -> tuple[list[str], Optional[URL]]:
        async with self._registry_client.request(
            method="GET", url=url, headers=headers, timeout=timeout
        ) as client_response:
            logger.debug("upstream response: %s", client_response)
            result_text = await client_response.text()
            try:
                client_response.raise_for_status()
            except ClientResponseError as exc:
                if exc.status == HTTPNotFound.status_code:
                    result_text = result_text.replace(
                        self._config.upstream_registry.project, ""
                    )
                    raise HTTPNotFound(
                        text=result_text, content_type="application/json"
                    )
                raise

            # passing content_type=None here to disable the strict content
            # type check. GCR sends application/json, whereas ECR sends
            # text/plan.
            result_dict = await client_response.json(content_type=None)
            next_upstream_url: Optional[URL] = None
            if client_response.links.get("next"):
                next_upstream_url = URL(client_response.links["next"]["url"])

            return (self.parse_catalog_repositories(result_dict), next_upstream_url)

    async def handle_repo_tags_list(self, request: Request) -> StreamResponse:
        # TODO: prevent leaking sensitive headers
        logger.debug("registry request: %s; headers: %s", request, request.headers)

        registry_repo_url = RepoURL.from_url(request.url)

        await self._check_user_permissions(
            request,
            [
                Permission(
                    uri=self._create_image_uri(registry_repo_url.repo), action="read"
                )
            ],
        )

        url_factory = self._create_url_factory(request)

        if self._config.upstream_registry.type == UpstreamType.AWS_ECR:
            response = await self._handle_aws_ecr_tags_list(
                registry_repo_url, request, url_factory
            )
        else:
            response = await self._handle_generic_tags_list(
                registry_repo_url, request, url_factory
            )
        logger.debug("registry response: %s; headers: %s", response, response.headers)
        return response

    async def _handle_generic_tags_list(
        self, registry_repo_url: RepoURL, request: Request, url_factory: URLFactory
    ) -> Response:
        upstream_repo_url = url_factory.create_upstream_repo_url(registry_repo_url)

        logger.info(
            "converted registry repo URL to upstream repo URL: %s -> %s",
            registry_repo_url,
            upstream_repo_url,
        )

        auth_headers = await self._upstream.get_headers_for_repo(
            upstream_repo_url.repo, upstream_repo_url.mounted_repo
        )
        request_headers = self._prepare_request_headers(request.headers, auth_headers)

        timeout = self._create_registry_client_timeout(request)

        async with self._registry_client.request(
            method=request.method,
            url=upstream_repo_url.url,
            headers=request_headers,
            skip_auto_headers=("Content-Type",),
            data=request.content.iter_any(),
            timeout=timeout,
        ) as client_response:
            logger.debug("upstream response: %s", client_response)

            response_headers = self._prepare_response_headers(
                client_response.headers, url_factory
            )
            response_headers.pop(CONTENT_LENGTH, None)
            # Content-Type in headers conflicts with the explicit content_type
            # added in json_response()
            response_headers.pop(CONTENT_TYPE, None)

            if "next" in client_response.links:
                next_upstream_url = client_response.links["next"]["url"]
                next_registry_url = registry_repo_url.url.with_query(
                    URL(next_upstream_url).query
                )
                response_headers[LINK] = f'<{next_registry_url!s}>; rel="next"'
            else:
                response_headers.pop(LINK, None)

            try:
                # See the comment in handle_catalog() about content_type=None.
                data = await client_response.json(content_type=None)
            except JSONDecodeError:
                return Response(
                    body=await client_response.text(),
                    headers=response_headers,
                    status=client_response.status,
                )
            else:
                self._fixup_repo_name(data, registry_repo_url.repo)
                response = aiohttp.web.json_response(
                    data, headers=response_headers, status=client_response.status
                )
        return response

    async def _handle_aws_ecr_tags_list(
        self, registry_repo_url: RepoURL, request: Request, url_factory: URLFactory
    ) -> Response:
        _, _, user, *repository_components, _, _ = request.path.split("/")
        repository = "/".join(repository_components)
        aws_repository = f"{self._upstream_registry_config.project}/{user}/{repository}"
        args = {
            "repositoryName": aws_repository,
            "filter": {"tagStatus": "TAGGED"},
        }
        if "next" in registry_repo_url.url.query:
            args["nextToken"] = registry_repo_url.url.query["next"]
        response_headers: CIMultiDict[str] = CIMultiDict()
        client = self._upstream._client  # type: ignore
        try:
            client_response = await client.list_images(**args)
            logger.debug("upstream response: %s", client_response)

            if (
                len(client_response.get("imageIds", [])) == 0
                and "next" not in registry_repo_url.url.query
            ):
                # This is repo without tags, lets clean up it
                await self._delete_aws_ecr_repository(aws_repository)

            response_headers = self._prepare_response_headers(
                client_response["ResponseMetadata"]["HTTPHeaders"], url_factory
            )
            for header in ("content-length", "content-type", "x-amzn-requestid"):
                response_headers.pop(header, None)

            (
                status,
                data,
            ) = await self._upstream.convert_upstream_response(  # type: ignore
                client_response
            )

            logger.debug("status: %d, client data: %s", status, data)

            data = {
                "name": registry_repo_url.repo,
                "tags": [image["imageTag"] for image in data.get("imageIds", [])],
            }

            if "nextToken" in client_response.keys():
                next_token = client_response["nextToken"]
                next_registry_url = registry_repo_url.url.with_query(next=next_token)
                response_headers[LINK] = f'<{next_registry_url!s}>; rel="next"'
            else:
                response_headers.pop(LINK, None)
        except client.exceptions.RepositoryNotFoundException:
            status = 404
            data = {
                "errors": [
                    {
                        "code": "NAME_UNKNOWN",
                        "message": f"Repository {registry_repo_url.repo} not found",
                        "detail": "",
                    }
                ]
            }
        except botocore.exceptions.ClientError as e:
            status = 400
            data = {
                "errors": [
                    {
                        "code": "UNSUPPORTED",
                        "message": f"AWS list_images failed",
                        "detail": str(e),
                    }
                ]
            }

        response = aiohttp.web.json_response(
            data, status=status, headers=response_headers
        )
        return response

    async def handle(self, request: Request) -> StreamResponse:
        # TODO: prevent leaking sensitive headers
        logger.debug("registry request: %s; headers: %s", request, request.headers)

        registry_repo_url = RepoURL.from_url(request.url)

        if not registry_repo_url.allow_skip_perms():
            permissions = [
                Permission(
                    uri=self._create_image_uri(registry_repo_url.repo),
                    action="read" if self._is_pull_request(request) else "write",
                )
            ]
            if registry_repo_url.mounted_repo:
                permissions.append(
                    Permission(
                        uri=self._create_image_uri(registry_repo_url.mounted_repo),
                        action="read",
                    )
                )
            await self._check_user_permissions(request, permissions)

        url_factory = self._create_url_factory(request)
        upstream_repo_url = url_factory.create_upstream_repo_url(registry_repo_url)

        logger.info(
            "converted registry repo URL to upstream repo URL: %s -> %s",
            registry_repo_url,
            upstream_repo_url,
        )

        if not self._is_pull_request(request):
            await self._upstream.create_repo(upstream_repo_url.repo)

        auth_headers = await self._upstream.get_headers_for_repo(
            upstream_repo_url.repo, upstream_repo_url.mounted_repo
        )

        return await self._proxy_request(
            request,
            url_factory=url_factory,
            url=upstream_repo_url.url,
            auth_headers=auth_headers,
        )

    def _is_pull_request(self, request: Request) -> bool:
        return request.method in ("HEAD", "GET")

    def _create_image_uri(self, repo: str) -> str:
        return f"image://{self._config.cluster_name}/{repo}"

    @trace
    async def _check_user_permissions(
        self, request: Request, permissions: Sequence[Permission]
    ) -> None:
        assert self._config.cluster_name
        logger.info(f"Checking {permissions}")
        try:
            await check_permission(request, "ignored", permissions)
        except HTTPUnauthorized:
            self._raise_unauthorized()

    def _create_registry_client_timeout(
        self, request: Request
    ) -> aiohttp.ClientTimeout:
        sock_read_timeout_s = None
        if self._is_pull_request(request):
            sock_read_timeout_s = self._upstream_registry_config.sock_read_timeout_s
        return aiohttp.ClientTimeout(
            total=None,
            connect=None,
            sock_connect=self._upstream_registry_config.sock_connect_timeout_s,
            sock_read=sock_read_timeout_s,
        )

    @trace
    async def _proxy_request(
        self,
        request: Request,
        url_factory: URLFactory,
        url: URL,
        auth_headers: dict[str, str],
    ) -> StreamResponse:
        request_headers = self._prepare_request_headers(request.headers, auth_headers)
        timeout = self._create_registry_client_timeout(request)

        if request.method == "HEAD":
            data = None
        else:
            data = request.content.iter_any()

        path_components = request.path.split("/")

        if (
            request.method == "DELETE"
            and self._config.upstream_registry.type == UpstreamType.AWS_ECR
            and path_components[-2] == "manifests"
        ):
            _, _, *repository_components, _, reference = path_components
            repository = "/".join(repository_components)
            repository_name = f"{self._upstream_registry_config.project}/{repository}"

            upstream_response = await self._delete_aws_ecr_image(
                repository_name, reference
            )
            await self._delete_aws_ecr_repository(repository_name)

            response = await self._convert_upstream_response(
                upstream_response, url_factory
            )
            logger.debug(
                "registry response: %s; headers: %s", response, response.headers
            )
            if response.status >= 500:
                logger.error(
                    "Upstream failed with %d, headers=%r",
                    response.status,
                    response.headers,
                )
            return response
        else:
            aws_blob_request = (
                request.method == "GET"
                and self._config.upstream_registry.type == UpstreamType.AWS_ECR
                and path_components[-1] == "blobs"
            )
            async with self._registry_client.request(
                method=request.method,
                url=url,
                headers=request_headers,
                skip_auto_headers=("Content-Type",),
                data=data,
                timeout=timeout,
                allow_redirects=aws_blob_request,
            ) as client_response:
                logger.debug("upstream response: %s", client_response)

                response_headers = self._prepare_response_headers(
                    client_response.headers, url_factory
                )
                response = aiohttp.web.StreamResponse(
                    status=client_response.status, headers=response_headers
                )

                await response.prepare(request)

                logger.debug(
                    "registry response: %s; headers: %s", response, response.headers
                )

                if response.status >= 500:
                    logger.error(
                        "Upstream failed with %d, headers=%r",
                        response.status,
                        response.headers,
                    )

                async for chunk, end_http in client_response.content.iter_chunks():
                    if chunk:
                        await response.write(chunk)
                    else:
                        break

                await response.write_eof()
                return response

    async def _delete_aws_ecr_image(self, repository_name: str, reference: str) -> Any:
        upstream: AWSECRUpstream = self._upstream  # type: ignore
        if reference.startswith("sha256:"):
            image_ids = [{"imageDigest": reference}]
        else:
            image_ids = [{"imageTag": reference}]
        response = await upstream._client.batch_delete_image(
            repositoryName=repository_name,
            imageIds=image_ids,
        )
        logger.debug("upstream response to batchDeleteImage: %s", response)
        return response

    async def _delete_aws_ecr_repository(self, repository_name: str) -> None:
        upstream: AWSECRUpstream = self._upstream  # type: ignore
        try:
            response = await upstream._client.delete_repository(
                repositoryName=repository_name,
                force=False,  # Will fail if there are some images
            )
            logger.debug("upstream response to deleteRepository: %s", response)
        except upstream._client.exceptions.RepositoryNotEmptyException:
            pass

    async def _convert_upstream_response(
        self, response: Any, url_factory: URLFactory
    ) -> aiohttp.web.StreamResponse:
        response_headers = self._prepare_response_headers(
            response["ResponseMetadata"]["HTTPHeaders"], url_factory
        )
        for header in ("content-length", "content-type", "x-amzn-requestid"):
            response_headers.pop(header, None)
        (
            status,
            content,
        ) = await self._upstream.convert_upstream_response(  # type: ignore
            response
        )
        return aiohttp.web.json_response(
            content, headers=response_headers, status=status
        )

    def _fixup_repo_name(self, data: Any, repo: str) -> None:
        if isinstance(data, dict):
            if "errors" in data:
                errors = data["errors"]
                if isinstance(errors, list):
                    for error in errors:
                        if isinstance(error, dict) and "detail" in error:
                            detail = error["detail"]
                            if isinstance(detail, dict) and "name" in detail:
                                detail["name"] = repo
            if "name" in data:
                data["name"] = repo

    def _prepare_request_headers(
        self, headers: CIMultiDictProxy[str], auth_headers: dict[str, str]
    ) -> CIMultiDict[str]:
        request_headers: CIMultiDict[str] = headers.copy()

        for name in ("Host", "Transfer-Encoding", "Connection"):
            request_headers.pop(name, None)

        request_headers.update(auth_headers)
        return request_headers

    def _prepare_response_headers(
        self, headers: CIMultiDictProxy[str], url_factory: URLFactory
    ) -> CIMultiDict[str]:
        response_headers: CIMultiDict[str] = headers.copy()

        for name in ("Transfer-Encoding", "Content-Encoding", "Connection"):
            response_headers.pop(name, None)

        if "Location" in response_headers:
            response_headers["Location"] = self._convert_location_header(
                response_headers["Location"], url_factory
            )
        return response_headers

    def _convert_location_header(self, url_str: str, url_factory: URLFactory) -> str:
        url_raw = URL(url_str)
        if (
            url_raw.host is not None
            and url_raw.host != url_factory.upstream_host
            and url_raw.host != url_factory.registry_host
        ):
            return url_str  # Redirect to outer service, maybe AWS S3 redirect

        upstream_repo_url = RepoURL.from_url(URL(url_str))

        if upstream_repo_url.allow_skip_perms():
            return url_str

        registry_repo_url = url_factory.create_registry_repo_url(upstream_repo_url)
        logger.info(
            "converted upstream repo URL to registry repo URL: %s -> %s",
            upstream_repo_url,
            registry_repo_url,
        )
        return str(registry_repo_url.url)


@asynccontextmanager
async def create_basic_upstream(
    *, config: UpstreamRegistryConfig
) -> AsyncIterator[Upstream]:
    yield BasicUpstream(username=config.basic_username, password=config.basic_password)


@asynccontextmanager
async def create_oauth_upstream(
    *, config: UpstreamRegistryConfig, client: aiohttp.ClientSession
) -> AsyncIterator[Upstream]:
    yield OAuthUpstream(
        client=OAuthClient(
            client=client,
            url=config.token_endpoint_url,
            service=config.token_service,
            username=config.token_endpoint_username,
            password=config.token_endpoint_password,
        ),
        registry_catalog_scope=config.token_registry_catalog_scope,
        repository_scope_actions=config.token_repository_scope_actions,
    )


@asynccontextmanager
async def create_aws_ecr_upstream(
    *,
    config: UpstreamRegistryConfig,
    time_factory: TimeFactory = time.time,
    **kwargs: Any,
) -> AsyncIterator[Upstream]:
    session = aiobotocore.session.get_session()
    async with session.create_client("ecr", **kwargs) as client:
        yield AWSECRUpstream(client=client, time_factory=time_factory)


package_version = pkg_resources.get_distribution("platform-registry-api").version


async def add_version_to_header(request: Request, response: StreamResponse) -> None:
    response.headers["X-Service-Version"] = f"platform-registry-api/{package_version}"


async def create_app(config: Config) -> aiohttp.web.Application:
    app = aiohttp.web.Application()

    await aiohttp_remotes.setup(app, aiohttp_remotes.XForwardedRelaxed())

    async def _init_app(app: aiohttp.web.Application) -> AsyncIterator[None]:
        async with AsyncExitStack() as exit_stack:

            async def on_request_redirect(
                session: ClientSession, ctx: SimpleNamespace, params: Any
            ) -> None:
                logger.debug("upstream redirect response: %s", params.response)

            trace_config = aiohttp.TraceConfig()
            trace_config.on_request_redirect.append(on_request_redirect)

            logger.info("Initializing Registry Client Session")

            session = await exit_stack.enter_async_context(
                aiohttp.ClientSession(
                    connector=aiohttp.TCPConnector(force_close=True),
                )
            )
            app["v2_app"]["registry_client"] = session

            is_aws = False
            if config.upstream_registry.is_basic:
                upstream_cm = create_basic_upstream(config=config.upstream_registry)
            elif config.upstream_registry.is_oauth:
                upstream_cm = create_oauth_upstream(
                    config=config.upstream_registry, client=session
                )
            else:
                upstream_cm = create_aws_ecr_upstream(config=config.upstream_registry)
                is_aws = True
            app["v2_app"]["upstream"] = await exit_stack.enter_async_context(
                upstream_cm
            )

            if is_aws:
                app["v2_app"]["upstream"]._client

            auth_client = await exit_stack.enter_async_context(
                AuthClient(
                    url=config.auth.server_endpoint_url,
                    token=config.auth.service_token,
                )
            )
            app["v2_app"]["auth_client"] = auth_client

            await setup_security(
                app=app, auth_client=auth_client, auth_scheme=AuthScheme.BASIC
            )

            yield

    app.cleanup_ctx.append(_init_app)

    v2_app = aiohttp.web.Application()
    v2_handler = V2Handler(app=v2_app, config=config)
    v2_handler.register(v2_app)
    v2_handler.register_artifacts(app)
    app["v2_app"] = v2_app
    app.add_subapp("/v2", v2_app)

    app.on_response_prepare.append(add_version_to_header)

    return app


def main() -> None:
    init_logging()

    loop = asyncio.get_event_loop()

    config = EnvironConfigFactory().create()
    logger.info("Loaded config: %r", config)
    setup_sentry(ignore_errors=[HTTPUnauthorized, HTTPForbidden])
    app = loop.run_until_complete(create_app(config))
    aiohttp.web.run_app(app, host=config.server.host, port=config.server.port)


if __name__ == "__main__":
    main()
