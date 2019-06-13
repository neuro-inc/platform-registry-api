from abc import ABC, abstractmethod
from typing import Dict


class Upstream(ABC):
    async def create_repo(self, repo: str) -> None:
        pass

    @abstractmethod
    async def get_headers_for_version(self) -> Dict[str, str]:
        pass

    @abstractmethod
    async def get_headers_for_catalog(self) -> Dict[str, str]:
        pass

    @abstractmethod
    async def get_headers_for_repo(self, repo: str) -> Dict[str, str]:
        pass
