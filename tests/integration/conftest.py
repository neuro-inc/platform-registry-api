import uuid
from asyncio.base_events import BaseEventLoop
from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Callable, Optional

import pytest
from aiohttp import BasicAuth
from jose import jwt
from neuro_auth_client import AuthClient, User

from platform_registry_api.config import Config


@pytest.fixture
def event_loop(loop: BaseEventLoop) -> BaseEventLoop:
    """
    This fixture mitigates the compatibility issues between
    pytest-asyncio and pytest-aiohttp.
    """
    return loop


@pytest.fixture
def cluster_name() -> str:
    return "test-cluster"


@dataclass
class _User:
    name: str
    token: str

    def to_basic_auth(self) -> BasicAuth:
        return BasicAuth(login=self.name, password=self.token)


@pytest.fixture
async def auth_client(config: Config, admin_token: str) -> AsyncIterator[AuthClient]:
    async with AuthClient(
        url=config.auth.server_endpoint_url, token=admin_token
    ) as client:
        yield client


@pytest.fixture
async def regular_user_factory(
    auth_client: AuthClient,
    token_factory: Callable[[str], str],
    admin_token: str,
    cluster_name: str,
) -> Callable[[Optional[str]], Awaitable[_User]]:
    async def _factory(name: Optional[str] = None) -> _User:
        if not name:
            name = str(uuid.uuid4())
        user = User(name=name)
        await auth_client.add_user(user)
        # Grant permissions to the user images
        headers = auth_client._generate_headers(admin_token)
        payload = [
            {"uri": f"image://{cluster_name}/{name}", "action": "manage"},
        ]
        async with auth_client._request(
            "POST", f"/api/v1/users/{name}/permissions", headers=headers, json=payload
        ) as p:
            assert p.status == 201
        return _User(name=user.name, token=token_factory(user.name))

    return _factory


@pytest.fixture
def token_factory() -> Callable[[str], str]:
    def _factory(name: str) -> str:
        payload = {"identity": name}
        return jwt.encode(payload, "secret", algorithm="HS256")

    return _factory


@pytest.fixture
def admin_token(token_factory: Callable[[str], str]) -> str:
    return token_factory("admin")
