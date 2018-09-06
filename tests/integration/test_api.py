import pytest
from aiohttp import BasicAuth
from yarl import URL

from platform_registry_api.api import create_app
from platform_registry_api.config import (
    AuthConfig, Config, EnvironConfigFactory, ServerConfig,
    UpstreamRegistryConfig
)


@pytest.fixture
def config(in_docker):
    if in_docker:
        return EnvironConfigFactory().create()

    upstream_registry = UpstreamRegistryConfig(
        endpoint_url=URL('http://localhost:5002'),
        project='testproject',
        token_endpoint_url=URL('http://localhost:5001/auth'),
        token_service='upstream',
        token_endpoint_username='testuser',
        token_endpoint_password='testpassword',
    )
    auth = AuthConfig(username='neuromation', password='neuromation')
    return Config(
        server=ServerConfig(), upstream_registry=upstream_registry, auth=auth)


class TestV2Api:
    @pytest.mark.asyncio
    async def test_unauthorized(self, aiohttp_client, config):
        app = await create_app(config)
        client = await aiohttp_client(app)
        async with client.get('/v2/') as resp:
            assert resp.status == 401
            assert resp.headers['WWW-Authenticate'] == (
                'Basic realm="Docker Registry"')

    @pytest.mark.asyncio
    async def test_invalid_credentials(self, aiohttp_client, config):
        app = await create_app(config)
        client = await aiohttp_client(app)
        headers = {
            'Authorization': 'Basic ab',
        }
        async with client.get('/v2/', headers=headers) as resp:
            assert resp.status == 400

    @pytest.mark.asyncio
    async def test_version_check(self, aiohttp_client, config):
        app = await create_app(config)
        client = await aiohttp_client(app)
        auth = BasicAuth(login='neuromation', password='neuromation')
        async with client.get('/v2/', auth=auth) as resp:
            assert resp.status == 200

    @pytest.mark.asyncio
    async def test_catalog(self, aiohttp_client, config):
        app = await create_app(config)
        client = await aiohttp_client(app)
        async with client.get('/v2/_catalog') as resp:
            assert resp.status == 403

    @pytest.mark.asyncio
    async def test_repo_unauthorized(self, aiohttp_client, config):
        app = await create_app(config)
        client = await aiohttp_client(app)
        async with client.get('/v2/neuromation/unknown/tags/list') as resp:
            assert resp.status == 401
            assert resp.headers['WWW-Authenticate'] == (
                'Basic realm="Docker Registry"')

    @pytest.mark.asyncio
    async def test_unknown_repo(self, aiohttp_client, config):
        app = await create_app(config)
        client = await aiohttp_client(app)
        auth = BasicAuth(login='neuromation', password='neuromation')
        async with client.get(
                '/v2/neuromation/unknown/tags/list', auth=auth) as resp:
            assert resp.status == 404
            payload = await resp.json()
            assert payload == {'errors': [{
                'code': 'NAME_UNKNOWN',
                # TODO: this has to be fixed ASAP:
                'detail': {'name': 'testproject/neuromation/unknown'},
                'message': 'repository name not known to registry',
            }]}

    @pytest.mark.asyncio
    async def test_x_forwarded_proto(self, aiohttp_client, config):
        app = await create_app(config)
        client = await aiohttp_client(app)
        auth = BasicAuth(login='neuromation', password='neuromation')
        headers = {'X-Forwarded-Proto': 'https'}
        async with client.post(
                '/v2/neuromation/image/blobs/uploads/', auth=auth,
                headers=headers) as resp:
            assert resp.status == 202
            location_url = URL(resp.headers['Location'])
            assert location_url.scheme == 'https'
