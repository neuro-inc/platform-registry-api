import base64
from unittest import mock

from aiohttp.hdrs import AUTHORIZATION

from platform_registry_api.auth_strategies import BasicAuthStrategy


class TestBasicAuthStrategy:
    async def test_get_headers(self) -> None:
        bacis_auth = BasicAuthStrategy(username="testname", password="testpassword")
        expected_headers = {AUTHORIZATION: mock.ANY}

        headers = await bacis_auth.get_headers()
        assert headers == expected_headers
        basic_auth = base64.b64encode(b"testname:testpassword").decode()
        assert headers[AUTHORIZATION] == f"Basic {basic_auth}"
