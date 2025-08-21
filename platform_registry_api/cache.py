import time
from typing import Generic, TypeVar


T = TypeVar("T")


class ExpiringCache(Generic[T]):
    def __init__(self) -> None:
        self._cache: dict[str | None, tuple[T, float]] = {}

    def get(self, key: str | None) -> T | None:
        record = self._cache.get(key)
        if record is not None:
            value, expires_at = record
            if time.time() < expires_at:
                return value
        return None

    def put(self, key: str | None, value: T, expires_at: float) -> None:
        self._cache[key] = value, expires_at
