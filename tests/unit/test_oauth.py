from datetime import datetime

import pytest

from platform_registry_api.api import OAuthToken


class TestOAuthToken:
    def test_create_from_payload_no_token(self) -> None:
        with pytest.raises(ValueError, match="no access token"):
            OAuthToken.create_from_payload({})

    def test_create_from_payload_token(self) -> None:
        token = OAuthToken.create_from_payload(
            {"token": "testtoken"}, time_factory=(lambda: 1560000000.0)
        )
        assert token == OAuthToken(access_token="testtoken", expires_at=1560000045.0)

    def test_create_from_payload_access_token(self) -> None:
        token = OAuthToken.create_from_payload(
            {"access_token": "testtoken"}, time_factory=(lambda: 1560000000.0)
        )
        assert token == OAuthToken(access_token="testtoken", expires_at=1560000045.0)

    def test_create_from_payload_expires_at(self) -> None:
        issued_at = datetime.utcfromtimestamp(1560000000.0).isoformat()
        token = OAuthToken.create_from_payload(
            {"token": "testtoken", "expires_in": 100, "issued_at": issued_at}
        )
        assert token == OAuthToken(access_token="testtoken", expires_at=1560000075.0)

    def test_create_from_payload_expires_in(self) -> None:
        token = OAuthToken.create_from_payload(
            {"token": "testtoken", "expires_in": 100},
            time_factory=(lambda: 1560000000.0),
        )
        assert token == OAuthToken(access_token="testtoken", expires_at=1560000075.0)

    @pytest.mark.parametrize(
        "issued_at",
        (
            datetime.utcfromtimestamp(1560000000.0).isoformat(),
            "2019-06-08T13:20:00Z",
            "2019-06-08T13:20:00+00:00",
            "2019-06-08T14:20:00+01:00",
        ),
    )
    def test_create_from_payload_issued_at(self, issued_at: str) -> None:
        token = OAuthToken.create_from_payload(
            {"token": "testtoken", "issued_at": issued_at}
        )
        assert token == OAuthToken(access_token="testtoken", expires_at=1560000045.0)
