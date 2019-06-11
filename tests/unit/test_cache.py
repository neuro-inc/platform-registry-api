import time

from platform_registry_api.api import ExpiringCache


class TestExpiringCache:
    def test_miss(self) -> None:
        cache = ExpiringCache[str]()
        assert cache.get("") is None

    def test_miss_expired(self) -> None:
        cache = ExpiringCache[str]()
        cache.put("key", "value", time.time() - 10)
        assert cache.get("key") is None

    def test_hit(self) -> None:
        cache = ExpiringCache[str]()
        cache.put("key", "value", time.time() + 10)
        assert cache.get("key") == "value"
