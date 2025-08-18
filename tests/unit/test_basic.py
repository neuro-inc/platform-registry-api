from unittest import mock

from aiohttp import BasicAuth
from aiohttp.hdrs import AUTHORIZATION

from platform_registry_api.auth_strategies import BasicAuthStrategy


class TestBasicAuthStrategy:
    async def test_get_headers(self) -> None:
        bacis_auth = BasicAuthStrategy(username="testname", password="testpassword")
        expected_headers = {AUTHORIZATION: mock.ANY}

        headers = await bacis_auth.get_headers()
        assert headers == expected_headers
        assert BasicAuth.decode(headers[AUTHORIZATION]) == BasicAuth(
            login="testname", password="testpassword"
        )
