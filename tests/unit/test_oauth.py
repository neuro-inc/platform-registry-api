import time

import jwt
import pytest

from platform_registry_api.auth_strategies import OAuthToken


class TestOAuthToken:
    def test_create_from_payload_no_token(self) -> None:
        with pytest.raises(ValueError, match="no access token"):
            OAuthToken.create_from_payload({})

    def test_create_from_payload_access_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(time, "time", lambda: 1560000000.0)
        access_token = jwt.encode({"sub": "without-exp"}, "secret", algorithm="HS256")
        token = OAuthToken.create_from_payload({"access_token": access_token})
        assert token == OAuthToken(access_token=access_token, expires_at=1560000045.0)

        access_token = jwt.encode({"exp": 1560000060}, "secret", algorithm="HS256")
        token = OAuthToken.create_from_payload({"access_token": access_token})
        assert token == OAuthToken(access_token=access_token, expires_at=1560000045.0)
