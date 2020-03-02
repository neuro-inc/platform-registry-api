from typing import Dict

from aiohttp import BasicAuth
from aiohttp.hdrs import AUTHORIZATION

from .upstream import Upstream


class BasicUpstream(Upstream):
    def __init__(self, *, username: str, password: str,) -> None:
        self._username = username
        self._password = password

    async def _get_headers(self) -> Dict[str, str]:
        return {
            str(AUTHORIZATION): BasicAuth(
                login=self._username, password=self._password
            ).encode()
        }

    async def get_headers_for_version(self) -> Dict[str, str]:
        return await self._get_headers()

    async def get_headers_for_catalog(self) -> Dict[str, str]:
        return await self._get_headers()

    async def get_headers_for_repo(self, repo: str) -> Dict[str, str]:
        return await self._get_headers()
