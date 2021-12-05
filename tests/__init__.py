from collections.abc import Awaitable, Callable

from aiohttp.test_utils import TestClient as _TestClient
from aiohttp.web import Application


_TestClientFactory = Callable[[Application], Awaitable[_TestClient]]
