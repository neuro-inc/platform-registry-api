import time
from typing import Dict, Generic, Optional, Tuple, TypeVar

from .typedefs import TimeFactory


T = TypeVar("T")


class ExpiringCache(Generic[T]):
    def __init__(self, *, time_factory: TimeFactory = time.time) -> None:
        self._time_factory = time_factory
        self._cache: Dict[Optional[str], Tuple[T, float]] = {}

    def get(self, key: Optional[str]) -> Optional[T]:
        record = self._cache.get(key)
        if record is not None:
            value, expires_at = record
            if self._time_factory() < expires_at:
                return value
        return None

    def put(self, key: Optional[str], value: T, expires_at: float) -> None:
        self._cache[key] = value, expires_at
