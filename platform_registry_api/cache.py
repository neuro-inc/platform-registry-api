import time
from typing import Generic, TypeVar

from .typedefs import TimeFactory


T = TypeVar("T")


class ExpiringCache(Generic[T]):
    def __init__(self, *, time_factory: TimeFactory = time.time) -> None:
        self._time_factory = time_factory
        self._cache: dict[str | None, tuple[T, float]] = {}

    def get(self, key: str | None) -> T | None:
        record = self._cache.get(key)
        if record is not None:
            value, expires_at = record
            if self._time_factory() < expires_at:
                return value
        return None

    def put(self, key: str | None, value: T, expires_at: float) -> None:
        self._cache[key] = value, expires_at
