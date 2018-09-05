import pytest
from aiohttp import BasicAuth
from yarl import URL

from platform_registry_api.config import (
    AuthConfig, Config, ServerConfig, UpstreamRegistryConfig
)
from platform_registry_api.user import (
    InMemoryUserService, User, UserServiceException
)


@pytest.fixture
def config():
    return Config(
        server=ServerConfig(),
        auth=AuthConfig(username='testuser', password='testpassword'),
        upstream_registry=UpstreamRegistryConfig(
            endpoint_url=URL('http://example.com'),
            project='testproject',
            token_endpoint_url=URL('http://example.com/token'),
            token_service='example.com',
            token_endpoint_username='tokenusername',
            token_endpoint_password='tokenpassword',
        )
    )


class TestInMemoryUserService:
    @pytest.mark.asyncio
    async def test_get_user_by_name(self, config):
        service = InMemoryUserService(config=config)
        user = await service.get_user_by_name('testuser')
        assert user == User(name='testuser', password='testpassword')

    @pytest.mark.asyncio
    async def test_get_user_by_name_not_found(self, config):
        service = InMemoryUserService(config=config)
        with pytest.raises(
                UserServiceException, match='User "unknown" was not found'):
            await service.get_user_by_name('unknown')

    @pytest.mark.asyncio
    async def test_get_user_with_credentials(self, config):
        service = InMemoryUserService(config=config)
        creds = BasicAuth(login='testuser', password='testpassword')
        user = await service.get_user_with_credentials(creds)
        assert user == User(name='testuser', password='testpassword')

    @pytest.mark.asyncio
    async def test_get_user_with_credentials_invalid(self, config):
        service = InMemoryUserService(config=config)
        creds = BasicAuth(login='testuser', password='invalid')
        with pytest.raises(
                UserServiceException, match='User "testuser" was not found'):
            await service.get_user_with_credentials(creds)
