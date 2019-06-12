import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from aiohttp import BasicAuth
from aiohttp.hdrs import AUTHORIZATION

from .cache import ExpiringCache
from .typedefs import TimeFactory
from .upstream import Upstream


@dataclass(frozen=True)
class AWSECRAuthToken:
    token: str
    expires_at: float

    @classmethod
    def create_from_payload(
        cls,
        payload: Dict[str, Any],
        *,
        expiration_ratio: float = 0.75,
        time_factory: TimeFactory = time.time,
    ) -> "AWSECRAuthToken":
        try:
            token_payload = payload["authorizationData"][0]
            token = token_payload["authorizationToken"]
            issued_at = time_factory()
            expires_in = token_payload["expiresAt"].timestamp() - issued_at
            expires_at = issued_at + expires_in * expiration_ratio
        except Exception as exc:
            raise ValueError("invalid payload") from exc
        if issued_at >= expires_at:
            raise ValueError("already expired")
        return cls(token=token, expires_at=expires_at)
