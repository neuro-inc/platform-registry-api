import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any, ClassVar, Tuple

import aiohttp.web
from aiohttp import BasicAuth, ClientSession
from aiohttp.web import Application, Request, Response, StreamResponse
from yarl import URL

from .config import Config, EnvironConfigFactory, UpstreamRegistryConfig


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RegistryRepoURL:
    # TODO: ClassVar[re.Pattern] in 3.7
    _path_re: ClassVar[Any] = re.compile(
        r'/v2/(?P<repo>.+)/(?P<path_suffix>(tags|manifests|blobs)/.*)')

    repo: str
    url: URL

    @classmethod
    def from_url(cls, url: URL) -> 'RegistryRepoURL':
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

    def with_repo(self, repo: str) -> 'RegistryRepoURL':
        _, url_suffix = self._parse(self.url)
        rel_url = URL(f'/v2/{repo}/').join(url_suffix)
        url = self.url.join(rel_url)
        # TODO: dataclasses.replace turns out out be buggy :D
        return self.__class__(repo=repo, url=url)

    def with_origin(self, origin_url: URL) -> 'RegistryRepoURL':
        url = origin_url.join(self.url.relative())
        return self.__class__(repo=self.repo, url=url)


class URLFactory:
    def __init__(
            self, registry_endpoint_url: URL, upstream_endpoint_url: URL,
            upstream_project: str) -> None:
        self._registry_endpoint_url = registry_endpoint_url
        self._upstream_endpoint_url = upstream_endpoint_url
        self._upstream_project = upstream_project

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

    def create_upstream_repo_url(
            self, registry_url: RegistryRepoURL) -> RegistryRepoURL:
        repo = f'{self._upstream_project}/{registry_url.repo}'
        return (
            registry_url
            .with_repo(repo)
            .with_origin(self._upstream_endpoint_url))

    def create_registry_repo_url(
            self, upstream_url: RegistryRepoURL) -> RegistryRepoURL:
        upstream_repo = upstream_url.repo
        try:
            upstream_project, repo = upstream_repo.split('/', 1)
        except ValueError:
            upstream_project, repo = '', upstream_repo
        if upstream_project != self._upstream_project:
            raise ValueError(
                f'Upstream project "{upstream_project}" does not match '
                f'the one configured "{self._upstream_project}"')
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
        async with self._client.get(url, auth=self._auth) as response:
            # TODO: check the status code
            # TODO: raise exceptions
            payload = await response.json()
            return payload['token']

    async def get_token_without_scope(self) -> str:
        url = self._base_url
        return await self._request(url)

    async def get_token_for_catalog(self) -> str:
        url = self._base_url.update_query({
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

        self._user = config.upstream_registry.token_endpoint_username
        self._password = config.upstream_registry.token_endpoint_password

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

    async def handle_version_check(self, request: Request) -> StreamResponse:
        url_factory = self._create_url_factory(request)
        url = url_factory.create_registry_version_check_url()
        token = await self._upstream_token_manager.get_token_without_scope()
        return await self._proxy_request(
            request, url_factory=url_factory, url=url, token=token)

    async def handle_catalog(self, request: Request) -> StreamResponse:
        # TODO: compose proper payload
        # see https://docs.docker.com/registry/spec/api/#errors
        return Response(status=403)

    async def handle(self, request: Request) -> StreamResponse:
        logger.debug('REQUEST: %s, %s', request, request.headers)

        reg_repo_url = RegistryRepoURL.from_url(request.url)
        downstream_repo = reg_repo_url.repo

        url_factory = self._create_url_factory(request)

        up_repo_url = url_factory.create_upstream_repo_url(reg_repo_url)
        upstream_repo = up_repo_url.repo

        logger.debug('DOWN REPO: %s', downstream_repo)
        logger.debug('UP REPO: %s', upstream_repo)

        token = await self._upstream_token_manager.get_token_for_repo(
            upstream_repo)

        return await self._proxy_request(
            request, url_factory=url_factory,
            url=up_repo_url.url, token=token)

    async def _proxy_request(
            self, request: Request, url_factory: URLFactory, url: URL,
            token: str) -> StreamResponse:
        request_headers = request.headers.copy()
        request_headers.pop('Host', None)
        request_headers.pop('Transfer-Encoding', None)
        request_headers['Authorization'] = f'Bearer {token}'

        logger.debug('REQUEST HEADERS: %s', request_headers)

        async with self._registry_client.request(
                method=request.method,
                url=url,
                headers=request_headers,
                skip_auto_headers=('Content-Type',),
                data=request.content.iter_any()) as client_response:

            if client_response.status in (400, 403):
                if client_response.content_type == 'application/json':
                    logger.info('UPSTREAM RESPONSE BODY: %s', await client_response.json())
                elif client_response.content_type == 'application/xml':
                    logger.info('UPSTREAM RESPONSE BODY: %s', await client_response.text())

            logger.debug('UPSTREAM RESPONSE: %s', client_response)
            logger.debug('Response Headers: %s', client_response.headers)

            response_headers = client_response.headers.copy()
            response_headers.pop('Transfer-Encoding', None)
            response_headers.pop('Content-Encoding', None)
            response_headers.pop('Connection', None)
            if 'Location' in response_headers:
                up_repo_url = RegistryRepoURL.from_url(
                    URL(response_headers['Location']))
                response_headers['Location'] = str(
                    url_factory.create_registry_repo_url(up_repo_url))
            logger.debug('Converted Response Headers: %s', response_headers)
            response = aiohttp.web.StreamResponse(
                status=client_response.status,
                headers=response_headers)
            await response.prepare(request)

            async for chunk in client_response.content.iter_any():
                await response.write(chunk)

            await response.write_eof()
            return response


async def create_app(config: Config) -> aiohttp.web.Application:
    app = aiohttp.web.Application()

    async def _init_app(app: aiohttp.web.Application):

        async def on_request_redirect(session, ctx, params):
            logger.debug('REDIRECT %s', params.response)

        trace_config = aiohttp.TraceConfig()
        trace_config.on_request_redirect.append(on_request_redirect)

        async with aiohttp.ClientSession(
                trace_configs=[trace_config]) as session:
            app['v2_app']['registry_client'] = session
            app['v2_app']['upstream_token_manager'] = UpstreamTokenManager(
                client=session,
                registry_config=config.upstream_registry,
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
