import asyncio
import logging

import aiohttp.web
from aiohttp import BasicAuth, ClientSession
from aiohttp.web import Application, Request, Response, StreamResponse
from yarl import URL

from .config import Config, EnvironConfigFactory, UpstreamRegistryConfig


logger = logging.getLogger(__name__)


def convert_from_upstream_url(base_url: URL, upstream_url: URL) -> URL:
    parts = upstream_url.parts[1:]
    parts = parts[:1] + parts[2:]
    path = '/' + '/'.join(parts)
    url = base_url.join(
        upstream_url.relative().with_path(path).with_query(upstream_url.query))
    return url


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
                '*', r'/{repo:.*}/{path:(tags|manifests|blobs)/.*}',
                self.handle),
        ))

    async def handle_version_check(self, request: Request) -> StreamResponse:
        base_url = self._upstream_registry_config.endpoint_url
        url = base_url.join(request.rel_url)
        token = await self._upstream_token_manager.get_token_without_scope()
        return await self._proxy_request(request, url=url, token=token)

    async def handle_catalog(self, request: Request) -> StreamResponse:
        return Response(status=403)

    async def handle(self, request: Request) -> StreamResponse:
        base_url = self._upstream_registry_config.endpoint_url

        logger.debug('REQUEST: %s, %s', request, request.headers)

        # TODO: check whether the name is correct
        downstream_repo = request.match_info['repo']

        logger.debug('DOWN REPO: %s', downstream_repo)

        upstream_project = self._upstream_registry_config.project
        upstream_repo = f'{upstream_project}/{downstream_repo}'

        logger.debug('UP REPO: %s', upstream_repo)

        rest = request.match_info['path']
        url = base_url.join(
            URL(f'/v2/{upstream_repo}/{rest}').with_query(request.query))

        token = await self._upstream_token_manager.get_token_for_repo(
            upstream_repo)

        return await self._proxy_request(request, url=url, token=token)

    async def _proxy_request(
            self, request: Request, url: URL, token: str) -> StreamResponse:
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
                response_headers['Location'] = str(
                    convert_from_upstream_url(
                        base_url=request.url,
                        upstream_url=URL(response_headers['Location'])))
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
