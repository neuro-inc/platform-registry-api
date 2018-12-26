import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any, ClassVar, List, Tuple

import aiohttp.web
import aiohttp_remotes
from aiohttp import BasicAuth, ClientSession
from aiohttp.web import (
    Application, HTTPBadRequest, HTTPUnauthorized, Request, Response,
    StreamResponse
)
from aiohttp_security import check_authorized, check_permission
from async_exit_stack import AsyncExitStack
from multidict import CIMultiDict, CIMultiDictProxy
from neuro_auth_client import AuthClient, Permission, User
from neuro_auth_client.security import AuthScheme, setup_security
from yarl import URL

from .config import Config, EnvironConfigFactory, UpstreamRegistryConfig


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RepoURL:
    # TODO: ClassVar[re.Pattern] in 3.7
    _path_re: ClassVar[Any] = re.compile(
        r'/v2/(?P<repo>.+)/(?P<path_suffix>(tags|manifests|blobs)/.*)')

    repo: str
    url: URL

    @classmethod
    def from_url(cls, url: URL) -> 'RepoURL':
        # validating the url
        repo, _ = cls._parse(url)
        return cls(repo=repo, url=url)  # type: ignore

    @classmethod
    def _parse(cls, url: URL) -> Tuple[str, URL]:
        match = cls._path_re.fullmatch(url.path)
        if not match:
            raise ValueError(f'unexpected path in a registry URL: {url}')
        path_suffix = URL.build(
            path=match.group('path_suffix'), query=url.query)
        assert not path_suffix.is_absolute()
        return match.group('repo'), path_suffix

    def with_repo(self, repo: str) -> 'RepoURL':
        _, url_suffix = self._parse(self.url)
        rel_url = URL(f'/v2/{repo}/').join(url_suffix)
        url = self.url.join(rel_url)
        # TODO: dataclasses.replace turns out out be buggy :D
        return self.__class__(repo=repo, url=url)

    def with_origin(self, origin_url: URL) -> 'RepoURL':
        url = origin_url.join(self.url.relative())
        return self.__class__(repo=self.repo, url=url)


class URLFactory:
    def __init__(
            self, registry_endpoint_url: URL, upstream_endpoint_url: URL,
            upstream_project: str) -> None:
        self._registry_endpoint_url = registry_endpoint_url
        self._upstream_endpoint_url = upstream_endpoint_url
        self._upstream_project = upstream_project

    @property
    def upstream_project(self):
        return self._upstream_project

    @classmethod
    def from_config(
            cls, registry_endpoint_url: URL, config: Config) -> 'URLFactory':
        return cls(
            registry_endpoint_url=registry_endpoint_url,
            upstream_endpoint_url=config.upstream_registry.endpoint_url,
            upstream_project=config.upstream_registry.project,
        )

    def create_registry_version_check_url(self) -> URL:
        return self._upstream_endpoint_url.with_path('/v2/')

    def create_upstream_catalog_url(self, request_url: URL) -> URL:
        return self._upstream_endpoint_url.with_path(request_url.path)

    def create_upstream_repo_url(self, registry_url: RepoURL) -> RepoURL:
        repo = f'{self.upstream_project}/{registry_url.repo}'
        return (
            registry_url
            .with_repo(repo)
            .with_origin(self._upstream_endpoint_url))

    def create_registry_repo_url(self, upstream_url: RepoURL) -> RepoURL:
        upstream_repo = upstream_url.repo
        try:
            upstream_project, repo = upstream_repo.split('/', 1)
        except ValueError:
            upstream_project, repo = '', upstream_repo
        if upstream_project != self.upstream_project:
            raise ValueError(
                f'Upstream project "{upstream_project}" does not match '
                f'the one configured "{self.upstream_project}"')
        return (
            upstream_url
            .with_repo(repo)
            .with_origin(self._registry_endpoint_url))


class UpstreamTokenManager:
    def __init__(
            self, client: ClientSession,
            registry_config: UpstreamRegistryConfig) -> None:
        self._client = client
        self._registry_config = registry_config

        self._auth = BasicAuth(
            login=self._registry_config.token_endpoint_username,
            password=self._registry_config.token_endpoint_password)

        self._base_url = (
            self._registry_config.token_endpoint_url.with_query({
                'service': self._registry_config.token_service,
            })
        )

    async def _request(self, url: URL) -> str:
        logger.debug(f'auth get token url: {url}, auth: {self._auth.encode()}')
        async with self._client.get(url, auth=self._auth) as response:
            # TODO: check the status code
            # TODO: raise exceptions
            payload = await response.json()
            logger.debug(f'auth response: {response}')
            return payload['token']

    async def get_token_without_scope(self) -> str:
        url = self._base_url
        return await self._request(url)

    async def get_token_for_catalog(self) -> str:
        url = self._base_url.update_query({
            'service': self._registry_config.token_service,
            'scope': 'registry:catalog:*',
        })
        return await self._request(url)

    async def get_token_for_repo(self, repo: str) -> str:
        url = self._base_url.update_query({
            'scope': f'repository:{repo}:*',
        })
        return await self._request(url)


class V2Handler:
    def __init__(self, app: Application, config: Config) -> None:
        self._app = app
        self._config = config
        self._upstream_registry_config = config.upstream_registry

    @property
    def _registry_client(self) -> aiohttp.ClientSession:
        return self._app['registry_client']

    @property
    def _upstream_token_manager(self) -> UpstreamTokenManager:
        return self._app['upstream_token_manager']

    def register(self, app):
        app.add_routes((
            aiohttp.web.get('/', self.handle_version_check),
            aiohttp.web.get('/_catalog', self.handle_catalog),
            aiohttp.web.route(
                '*', r'/{repo:.+}/{path_suffix:(tags|manifests|blobs)/.*}',
                self.handle),
        ))

    def _create_url_factory(self, request: Request) -> URLFactory:
        return URLFactory.from_config(
            registry_endpoint_url=request.url.origin(), config=self._config
        )

    async def _get_user_from_request(self, request: Request) -> User:
        try:
            user_name = await check_authorized(request)
        except ValueError:
            raise HTTPBadRequest(text='Cannot authorize')
        except HTTPUnauthorized:
            self._raise_unauthorized()
        return User(name=user_name)

    def _raise_unauthorized(self) -> None:
        raise HTTPUnauthorized(headers={
            'WWW-Authenticate': f'Basic realm="{self._config.server.name}"',
        })

    async def handle_version_check(self, request: Request) -> StreamResponse:
        # TODO: prevent leaking sensitive headers
        logger.debug(
            'registry request: %s; headers: %s', request, request.headers)

        await self._get_user_from_request(request)

        url_factory = self._create_url_factory(request)
        url = url_factory.create_registry_version_check_url()
        token = await self._upstream_token_manager.get_token_without_scope()
        return await self._proxy_request(
            request, url_factory=url_factory, url=url, token=token)

    @classmethod
    def _filter_images_by_repository(
            cls,
            project: str,
            repository: str,
            images: List[str],
    ) -> List[str]:
        if not project:
            raise ValueError('Empty project name')
        if not repository:
            raise ValueError('Empty repository name')
        start = f'{project}/{repository}/'
        return [img for img in images if img.startswith(start)]

    async def handle_catalog(self, request: Request) -> Response:
        logger.debug(
            'registry request: %s; headers: %s', request, request.headers)

        user = await self._get_user_from_request(request)

        url_factory = self._create_url_factory(request)
        url = url_factory.create_upstream_catalog_url(request.url)
        token = await self._upstream_token_manager.get_token_for_catalog()

        headers = self._prepare_request_headers(request.headers, token=token)
        timeout = self._create_registry_client_timeout(request)

        async with self._registry_client.request(
                method=request.method,
                url=url,
                headers=headers,
                skip_auto_headers=('Content-Type',),
                data=request.content.iter_any(),
                timeout=timeout) as client_response:
            logger.debug('upstream response: %s', client_response)

            content_type = client_response.content_type
            assert content_type == 'application/json', content_type

            json = await client_response.json()
            repositories_list = json.get('repositories')
            if repositories_list is not None:
                filtered = self._filter_images_by_repository(
                    url_factory.upstream_project,
                    user.name,
                    repositories_list,
                )
                json = {
                    'repositories': filtered
                }

            response = aiohttp.web.json_response(
                data=json,
                status=aiohttp.web.HTTPOk.status_code
            )
            await response.prepare(request)

            logger.debug(
                'registry response: %s; headers: %s',
                response, response.headers)

            return response

    async def handle(self, request: Request) -> StreamResponse:
        # TODO: prevent leaking sensitive headers
        logger.debug(
            'registry request: %s; headers: %s', request, request.headers)

        registry_repo_url = RepoURL.from_url(request.url)

        await self._check_user_permissions(request, registry_repo_url.repo)

        url_factory = self._create_url_factory(request)
        upstream_repo_url = url_factory.create_upstream_repo_url(
            registry_repo_url)

        logger.info(
            'converted registry repo URL to upstream repo URL: %s -> %s',
            registry_repo_url, upstream_repo_url)

        token = await self._upstream_token_manager.get_token_for_repo(
            upstream_repo_url.repo)

        return await self._proxy_request(
            request, url_factory=url_factory,
            url=upstream_repo_url.url, token=token)

    def _is_pull_request(self, request: Request) -> bool:
        return request.method in ('HEAD', 'GET')

    async def _check_user_permissions(self, request, repo: str) -> None:
        uri = 'image://' + repo
        if self._is_pull_request(request):
            action = 'read'
        else:  # POST, PUT, PATCH, DELETE
            action = 'write'
        permission = Permission(uri=uri, action=action)
        logger.info(f'Checking {permission}')
        try:
            await check_permission(request, action, [permission])
        except HTTPUnauthorized:
            self._raise_unauthorized()

    def _create_registry_client_timeout(
        self, request: Request
    ) -> aiohttp.ClientTimeout:
        sock_read_timeout_s = None
        if self._is_pull_request(request):
            sock_read_timeout_s = (
                self._upstream_registry_config.sock_read_timeout_s
            )
        return aiohttp.ClientTimeout(
            total=None,
            connect=None,
            sock_connect=self._upstream_registry_config.sock_connect_timeout_s,
            sock_read=sock_read_timeout_s,
        )

    async def _proxy_request(
            self, request: Request, url_factory: URLFactory, url: URL,
            token: str) -> StreamResponse:
        request_headers = self._prepare_request_headers(
            request.headers, token=token)

        timeout = self._create_registry_client_timeout(request)

        async with self._registry_client.request(
                method=request.method,
                url=url,
                headers=request_headers,
                skip_auto_headers=('Content-Type',),
                data=request.content.iter_any(),
                timeout=timeout) as client_response:

            logger.debug('upstream response: %s', client_response)

            response_headers = self._prepare_response_headers(
                client_response.headers, url_factory)
            response = aiohttp.web.StreamResponse(
                status=client_response.status,
                headers=response_headers)

            await response.prepare(request)

            logger.debug(
                'registry response: %s; headers: %s',
                response, response.headers)

            async for chunk in client_response.content.iter_any():
                await response.write(chunk)

            await response.write_eof()
            return response

    def _prepare_request_headers(
            self, headers: CIMultiDictProxy, token: str) -> CIMultiDict:
        request_headers: CIMultiDict = headers.copy()  # type: ignore

        for name in ('Host', 'Transfer-Encoding', 'Connection'):
            request_headers.pop(name, None)

        request_headers['Authorization'] = f'Bearer {token}'
        return request_headers

    def _prepare_response_headers(
            self, headers: CIMultiDictProxy, url_factory: URLFactory
            ) -> CIMultiDict:
        response_headers: CIMultiDict = headers.copy()  # type: ignore

        for name in ('Transfer-Encoding', 'Content-Encoding', 'Connection'):
            response_headers.pop(name, None)

        if 'Location' in response_headers:
            response_headers['Location'] = self._convert_location_header(
                response_headers['Location'], url_factory)
        return response_headers

    def _convert_location_header(
            self, url_str: str, url_factory: URLFactory) -> str:
        upstream_repo_url = RepoURL.from_url(URL(url_str))
        registry_repo_url = url_factory.create_registry_repo_url(
            upstream_repo_url)
        logger.info(
            'converted upstream repo URL to registry repo URL: %s -> %s',
            upstream_repo_url, registry_repo_url)
        return str(registry_repo_url.url)


async def create_app(config: Config) -> aiohttp.web.Application:
    app = aiohttp.web.Application()

    await aiohttp_remotes.setup(app, aiohttp_remotes.XForwardedRelaxed())

    async def _init_app(app: aiohttp.web.Application):
        async with AsyncExitStack() as exit_stack:

            async def on_request_redirect(session, ctx, params):
                logger.debug('upstream redirect response: %s', params.response)

            trace_config = aiohttp.TraceConfig()
            trace_config.on_request_redirect.append(on_request_redirect)

            logger.info('Initializing Registry Client Session')

            session = await exit_stack.enter_async_context(
                aiohttp.ClientSession(
                    trace_configs=[trace_config],
                )
            )

            app['v2_app']['registry_client'] = session
            app['v2_app']['upstream_token_manager'] = UpstreamTokenManager(
                client=session,
                registry_config=config.upstream_registry,
            )

            auth_client = await exit_stack.enter_async_context(AuthClient(
                url=config.auth.server_endpoint_url,
                token=config.auth.service_token,
            ))

            await setup_security(
                app=app,
                auth_client=auth_client,
                auth_scheme=AuthScheme.BASIC
            )

            yield

    app.cleanup_ctx.append(_init_app)

    v2_app = aiohttp.web.Application()
    v2_handler = V2Handler(app=v2_app, config=config)
    v2_handler.register(v2_app)

    app['v2_app'] = v2_app
    app.add_subapp('/v2', v2_app)
    return app


def init_logging():
    logging.basicConfig(
        # TODO (A Danshyn 06/01/18): expose in the Config
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


def main():
    init_logging()

    loop = asyncio.get_event_loop()

    config = EnvironConfigFactory().create()
    logger.info('Loaded config: %r', config)

    app = loop.run_until_complete(create_app(config))
    aiohttp.web.run_app(
        app, host=config.server.host, port=config.server.port)
