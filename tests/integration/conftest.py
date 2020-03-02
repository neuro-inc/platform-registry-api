import os
import uuid
from dataclasses import dataclass
from typing import Optional

import pytest
from aiohttp import BasicAuth
from jose import jwt
from neuro_auth_client import AuthClient, User


@pytest.fixture
def event_loop(loop):
    """
    This fixture mitigates the compatibility issues between
    pytest-asyncio and pytest-aiohttp.
    """
    return loop


@pytest.fixture
def cluster_name():
    return "test-cluster"


@dataclass
class _User:
    name: str
    token: str

    def to_basic_auth(self) -> BasicAuth:
        return BasicAuth(login=self.name, password=self.token)  # type: ignore


@pytest.fixture
async def auth_client(config, admin_token):
    async with AuthClient(
        url=config.auth.server_endpoint_url, token=admin_token
    ) as client:
        yield client


@pytest.fixture
async def regular_user_factory(auth_client, token_factory, admin_token, cluster_name):
    async def _factory(name: Optional[str] = None) -> User:
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
        return _User(name=user.name, token=token_factory(user.name))  # type: ignore

    return _factory


@pytest.fixture(scope="session")
def in_docker():
    return os.path.isfile("/.dockerenv")


@pytest.fixture
def token_factory():
    def _factory(name: str):
        payload = {"identity": name}
        return jwt.encode(payload, "secret", algorithm="HS256")

    return _factory


@pytest.fixture
def admin_token(token_factory):
    return token_factory("admin")
