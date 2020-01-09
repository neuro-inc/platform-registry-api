import asyncio
import logging
import re
import time
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, ClassVar, Dict, Iterable, Iterator, List, Tuple

import aiobotocore
import aiohttp.web
import aiohttp_remotes
import aiozipkin
from aiohttp.hdrs import CONTENT_LENGTH, CONTENT_TYPE
from aiohttp.web import (
    Application,
    HTTPBadRequest,
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
from platform_logging import init_logging
from yarl import URL

from platform_registry_api.helpers import check_image_catalog_permission

from .aws_ecr import AWSECRUpstream
from .config import Config, EnvironConfigFactory, UpstreamRegistryConfig
from .oauth import OAuthClient, OAuthUpstream
from .typedefs import TimeFactory
from .upstream import Upstream


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RepoURL:
    _path_re: ClassVar[re.Pattern] = re.compile(
        r"/v2/(?P<repo>.+)/(?P<path_suffix>(tags|manifests|blobs)/.*)"
    )

    repo: str
    url: URL

    @classmethod
    def from_url(cls, url: URL) -> "RepoURL":
        # validating the url
        repo, _ = cls._parse(url)
        return cls(repo=repo, url=url)  # type: ignore

    @classmethod
    def _parse(cls, url: URL) -> Tuple[str, URL]:
        match = cls._path_re.fullmatch(url.path)
        if not match:
            raise ValueError(f"unexpected path in a registry URL: {url}")
        path_suffix = URL.build(path=match.group("path_suffix"), query=url.query)
        assert not path_suffix.is_absolute()
        return match.group("repo"), path_suffix

    def with_repo(self, repo: str) -> "RepoURL":
        _, url_suffix = self._parse(self.url)
        rel_url = URL(f"/v2/{repo}/").join(url_suffix)
        url = self.url.join(rel_url)
        # TODO: dataclasses.replace turns out out be buggy :D
        return self.__class__(repo=repo, url=url)

    def with_origin(self, origin_url: URL) -> "RepoURL":
        url = self.url
        if url.is_absolute():
            url = url.relative()
        url = origin_url.join(url)
        return self.__class__(repo=self.repo, url=url)


class URLFactory:
    def __init__(
        self,
        registry_endpoint_url: URL,
        upstream_endpoint_url: URL,
        upstream_project: str,
    ) -> None:
        self._registry_endpoint_url = registry_endpoint_url
        self._upstream_endpoint_url = upstream_endpoint_url
        self._upstream_project = upstream_project

    @property
    def upstream_project(self):
        return self._upstream_project

    @classmethod
    def from_config(cls, registry_endpoint_url: URL, config: Config) -> "URLFactory":
        return cls(
            registry_endpoint_url=registry_endpoint_url,
            upstream_endpoint_url=config.upstream_registry.endpoint_url,
            upstream_project=config.upstream_registry.project,
        )

    def create_registry_version_check_url(self) -> URL:
        return self._upstream_endpoint_url.with_path("/v2/")

    def create_upstream_catalog_url(self) -> URL:
        return self._upstream_endpoint_url.with_path("/v2/_catalog")

    def create_upstream_repo_url(self, registry_url: RepoURL) -> RepoURL:
        repo = f"{self._upstream_project}/{registry_url.repo}"
        return registry_url.with_repo(repo).with_origin(self._upstream_endpoint_url)

    def create_registry_repo_url(self, upstream_url: RepoURL) -> RepoURL:
        upstream_repo = upstream_url.repo
        try:
            upstream_project, repo = upstream_repo.split("/", 1)
        except ValueError:
            upstream_project, repo = "", upstream_repo
        if upstream_project != self._upstream_project:
            raise ValueError(
                f'Upstream project "{upstream_project}" does not match '
                f'the one configured "{self._upstream_project}"'
            )
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

    def register(self, app):
        app.add_routes(
            (
                aiohttp.web.get("/", self.handle_version_check),
                aiohttp.web.get("/_catalog", self.handle_catalog),
                aiohttp.web.get(r"/{repo:.+}/tags/list", self.handle_repo_tags_list),
                aiohttp.web.route(
                    "*",
                    r"/{repo:.+}/{path_suffix:(tags|manifests|blobs)/.*}",
                    self.handle,
                ),
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
    def parse_catalog_repositories(cls, payload: Dict[str, Any]) -> List[str]:
        return payload.get("repositories") or []

    @classmethod
    def filter_images(
        cls, images_names: Iterable[str], tree: ClientSubTreeViewRoot, project_name: str
    ) -> Iterator[str]:
        project_prefix = project_name + "/"
        len_project_prefix = len(project_prefix)
        for image in images_names:
            if image.startswith(project_prefix):
                image = image[len_project_prefix:]
                if check_image_catalog_permission(image, tree):
                    yield image
            else:
                msg = f'expected project "{project_name}" in image "{image}"'
                logger.info(f"Bad image: {msg} (skipping)")

    async def handle_catalog(self, request: Request) -> Response:
        logger.debug("registry request: %s; headers: %s", request, request.headers)

        user = await self._get_user_from_request(request)

        url_factory = self._create_url_factory(request)
        url = url_factory.create_upstream_catalog_url()

        auth_headers = await self._upstream.get_headers_for_catalog()
        headers = self._prepare_request_headers(request.headers, auth_headers)
        params = {"n": self._config.upstream_registry.max_catalog_entries}

        timeout = self._create_registry_client_timeout(request)

        async with self._registry_client.request(
            method="GET", url=url, headers=headers, params=params, timeout=timeout
        ) as client_response:
            logger.debug("upstream response: %s", client_response)
            client_response.raise_for_status()

            # passing content_type=None here to disable the strict content
            # type check. GCR sends application/json, whereas ECR sends
            # text/plan.
            result_dict = await client_response.json(content_type=None)
            images_list = self.parse_catalog_repositories(result_dict)
            logger.debug(
                f"Received {len(images_list)} images "
                f"(limit: {self._config.upstream_registry.max_catalog_entries})"
            )

            tree = await self._auth_client.get_permissions_tree(
                user.name, f"image://{self._config.cluster_name}"
            )
            project_name = url_factory.upstream_project
            filtered = [
                img for img in self.filter_images(images_list, tree, project_name)
            ]

            result_dict = {"repositories": filtered}

            response = aiohttp.web.json_response(data=result_dict)

            logger.debug(
                "registry response: %s; headers: %s", response, response.headers
            )

            return response

    async def handle_repo_tags_list(self, request: Request) -> StreamResponse:
        # TODO: prevent leaking sensitive headers
        logger.debug("registry request: %s; headers: %s", request, request.headers)

        registry_repo_url = RepoURL.from_url(request.url)

        await self._check_user_permissions(request, registry_repo_url.repo)

        url_factory = self._create_url_factory(request)
        upstream_repo_url = url_factory.create_upstream_repo_url(registry_repo_url)

        logger.info(
            "converted registry repo URL to upstream repo URL: %s -> %s",
            registry_repo_url,
            upstream_repo_url,
        )

        auth_headers = await self._upstream.get_headers_for_repo(upstream_repo_url.repo)
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

            # See the comment in handle_catalog() about content_type=None.
            data = await client_response.json(content_type=None)
            self._fixup_repo_name(data, registry_repo_url.repo)
            response = aiohttp.web.json_response(
                data, status=client_response.status, headers=response_headers
            )
            logger.debug(
                "registry response: %s; headers: %s", response, response.headers
            )
            return response

    async def handle(self, request: Request) -> StreamResponse:
        # TODO: prevent leaking sensitive headers
        logger.debug("registry request: %s; headers: %s", request, request.headers)

        registry_repo_url = RepoURL.from_url(request.url)

        await self._check_user_permissions(request, registry_repo_url.repo)

        url_factory = self._create_url_factory(request)
        upstream_repo_url = url_factory.create_upstream_repo_url(registry_repo_url)

        logger.info(
            "converted registry repo URL to upstream repo URL: %s -> %s",
            registry_repo_url,
            upstream_repo_url,
        )

        if not self._is_pull_request(request):
            await self._upstream.create_repo(upstream_repo_url.repo)

        auth_headers = await self._upstream.get_headers_for_repo(upstream_repo_url.repo)

        return await self._proxy_request(
            request,
            url_factory=url_factory,
            url=upstream_repo_url.url,
            auth_headers=auth_headers,
        )

    def _is_pull_request(self, request: Request) -> bool:
        return request.method in ("HEAD", "GET")

    async def _check_user_permissions(self, request, repo: str) -> None:
        uri = f"image://{self._config.cluster_name}/{repo}"
        if self._is_pull_request(request):
            action = "read"
        else:  # POST, PUT, PATCH, DELETE
            action = "write"
        permission = Permission(uri=uri, action=action)
        logger.info(f"Checking {permission}")
        try:
            await check_permission(request, action, [permission])
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

    async def _proxy_request(
        self,
        request: Request,
        url_factory: URLFactory,
        url: URL,
        auth_headers: Dict[str, str],
    ) -> StreamResponse:
        request_headers = self._prepare_request_headers(request.headers, auth_headers)

        timeout = self._create_registry_client_timeout(request)

        if request.method == "HEAD":
            data = None
        else:
            data = request.content.iter_any()

        async with self._registry_client.request(
            method=request.method,
            url=url,
            headers=request_headers,
            skip_auto_headers=("Content-Type",),
            data=data,
            timeout=timeout,
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

            async for chunk in client_response.content.iter_any():
                await response.write(chunk)

            await response.write_eof()
            return response

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
        self, headers: CIMultiDictProxy, auth_headers: Dict[str, str]
    ) -> CIMultiDict:
        request_headers: CIMultiDict = headers.copy()  # type: ignore

        for name in ("Host", "Transfer-Encoding", "Connection"):
            request_headers.pop(name, None)

        request_headers.update(auth_headers)
        return request_headers

    def _prepare_response_headers(
        self, headers: CIMultiDictProxy, url_factory: URLFactory
    ) -> CIMultiDict:
        response_headers: CIMultiDict = headers.copy()  # type: ignore

        for name in ("Transfer-Encoding", "Content-Encoding", "Connection"):
            response_headers.pop(name, None)

        if "Location" in response_headers:
            response_headers["Location"] = self._convert_location_header(
                response_headers["Location"], url_factory
            )
        return response_headers

    def _convert_location_header(self, url_str: str, url_factory: URLFactory) -> str:
        upstream_repo_url = RepoURL.from_url(URL(url_str))
        registry_repo_url = url_factory.create_registry_repo_url(upstream_repo_url)
        logger.info(
            "converted upstream repo URL to registry repo URL: %s -> %s",
            upstream_repo_url,
            registry_repo_url,
        )
        return str(registry_repo_url.url)


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
    session = aiobotocore.get_session()
    async with session.create_client("ecr", **kwargs) as client:
        yield AWSECRUpstream(client=client, time_factory=time_factory)


async def create_tracer(config: Config) -> aiozipkin.Tracer:
    endpoint = aiozipkin.create_endpoint(
        "platformregistryapi",  # the same name as pod prefix on a cluster
        ipv4=config.server.host,
        port=config.server.port,
    )

    zipkin_address = config.zipkin.url / "api/v2/spans"
    tracer = await aiozipkin.create(
        str(zipkin_address), endpoint, sample_rate=config.zipkin.sample_rate
    )
    return tracer


async def create_app(config: Config) -> aiohttp.web.Application:
    app = aiohttp.web.Application()

    await aiohttp_remotes.setup(app, aiohttp_remotes.XForwardedRelaxed())
    tracer = await create_tracer(config)

    async def _init_app(app: aiohttp.web.Application):
        async with AsyncExitStack() as exit_stack:

            async def on_request_redirect(session, ctx, params):
                logger.debug("upstream redirect response: %s", params.response)

            trace_config = aiohttp.TraceConfig()
            trace_config.on_request_redirect.append(on_request_redirect)

            auth_trace_config = aiozipkin.make_trace_config(tracer)

            logger.info("Initializing Registry Client Session")

            session = await exit_stack.enter_async_context(
                aiohttp.ClientSession(
                    trace_configs=[trace_config, auth_trace_config],
                    connector=aiohttp.TCPConnector(force_close=True),
                )
            )
            app["v2_app"]["registry_client"] = session

            if config.upstream_registry.is_oauth:
                upstream_cm = create_oauth_upstream(
                    config=config.upstream_registry, client=session
                )
            else:
                upstream_cm = create_aws_ecr_upstream(config=config.upstream_registry)
            app["v2_app"]["upstream"] = await exit_stack.enter_async_context(
                upstream_cm
            )

            auth_client = await exit_stack.enter_async_context(
                AuthClient(
                    url=config.auth.server_endpoint_url,
                    token=config.auth.service_token,
                    trace_config=auth_trace_config,
                )
            )
            app["v2_app"]["auth_client"] = auth_client

            await setup_security(
                app=app, auth_client=auth_client, auth_scheme=AuthScheme.BASIC
            )

            yield

    aiozipkin.setup(app, tracer)
    app.cleanup_ctx.append(_init_app)

    v2_app = aiohttp.web.Application()
    v2_handler = V2Handler(app=v2_app, config=config)
    v2_handler.register(v2_app)

    app["v2_app"] = v2_app
    app.add_subapp("/v2", v2_app)
    return app


def main():
    init_logging()

    loop = asyncio.get_event_loop()

    config = EnvironConfigFactory().create()
    logger.info("Loaded config: %r", config)

    app = loop.run_until_complete(create_app(config))
    aiohttp.web.run_app(app, host=config.server.host, port=config.server.port)
