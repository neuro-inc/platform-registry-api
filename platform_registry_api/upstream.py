from abc import ABC, abstractmethod


class Upstream(ABC):
    async def create_repo(self, repo: str) -> None:  # noqa: B027
        # TODO unabstract method for ABC
        pass

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
