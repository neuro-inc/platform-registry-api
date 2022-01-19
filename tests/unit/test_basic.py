from unittest import mock

import pytest
from aiohttp import BasicAuth
from aiohttp.hdrs import AUTHORIZATION

from platform_registry_api.basic import BasicUpstream


class TestBasicUpstream:
    async def test_get_headers(self) -> None:
        upstream = BasicUpstream(username="testname", password="testpassword")
        expected_headers = {AUTHORIZATION: mock.ANY}

        headers = await upstream.get_headers_for_version()
        assert headers == expected_headers
        assert BasicAuth.decode(headers[AUTHORIZATION]) == BasicAuth(
            login="testname", password="testpassword"
        )

    async def test_get_headers_for_catalog(self) -> None:
        upstream = BasicUpstream(username="testname", password="testpassword")
        expected_headers = {AUTHORIZATION: mock.ANY}
        headers = await upstream.get_headers_for_catalog()
        assert headers == expected_headers
        assert BasicAuth.decode(headers[AUTHORIZATION]) == BasicAuth(
            login="testname", password="testpassword"
        )

    async def test_get_headers_for_repo(self) -> None:
        upstream = BasicUpstream(username="testname", password="testpassword")
        expected_headers = {AUTHORIZATION: mock.ANY}
        headers = await upstream.get_headers_for_repo("testrepo")
        assert headers == expected_headers
        assert BasicAuth.decode(headers[AUTHORIZATION]) == BasicAuth(
            login="testname", password="testpassword"
        )
