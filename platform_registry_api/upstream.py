from abc import ABC, abstractmethod


class Upstream(ABC):
    @abstractmethod
    async def get_headers_for_version(self) -> dict[str, str]:
        pass

    @abstractmethod
    async def get_headers_for_catalog(self) -> dict[str, str]:
        pass

    @abstractmethod
    async def get_headers_for_repo(
        self, repo: str, mounted_repo: str = ""
    ) -> dict[str, str]:
        pass
