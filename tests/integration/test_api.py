import pytest
from yarl import URL
from aiohttp import BasicAuth

from platform_registry_api.api import create_app
from platform_registry_api.config import (
    Config, ServerConfig, UpstreamRegistryConfig, EnvironConfigFactory
)


@pytest.fixture
def config(in_docker):
    if in_docker:
        return EnvironConfigFactory().create()

    upstream_registry = UpstreamRegistryConfig(
        endpoint_url=URL('http://localhost:5002'),
        project='testproject',
        token_endpoint_url=URL('http://localhost:5001/auth'),
        token_endpoint_username='testuser',
        token_endpoint_password='testpassword',
    )
    return Config(server=ServerConfig(), upstream_registry=upstream_registry)


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
        auth = BasicAuth(login='neuromation', password='')
        async with client.get('/v2/', auth=auth) as resp:
            assert resp.status == 200

    @pytest.mark.asyncio
    async def test_catalog(self, aiohttp_client, config):
        app = await create_app(config)
        client = await aiohttp_client(app)
        async with client.get('/v2/_catalog') as resp:
            assert resp.status == 403
