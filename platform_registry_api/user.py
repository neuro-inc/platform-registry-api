import abc
from dataclasses import dataclass, field

from aiohttp import BasicAuth

from .config import Config


@dataclass
class User:
    name: str
    password: str = field(repr=False)


class UserServiceException(Exception):
    pass


class UserService(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    async def get_user_by_name(self, name: str) -> User:
        pass

    async def get_user_with_credentials(self, credentials: BasicAuth) -> User:
        user = await self.get_user_by_name(credentials.login)
        if user.password != credentials.password:
            raise UserServiceException(
                f'User "{credentials.login}" was not found')
        return user


class InMemoryUserService(UserService):
    def __init__(self, config: Config) -> None:
        self._users = {
            user.name: user
            for user in (
                User(  # type: ignore
                    name='neuromation', password='neuromation'),
            )
        }

    async def get_user_by_name(self, name: str) -> User:
        user = self._users.get(name)
        if not user:
            raise UserServiceException(f'User "{name}" was not found')
        return user
