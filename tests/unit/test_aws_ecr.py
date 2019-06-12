from datetime import datetime
from typing import Any, Dict

import pytest

from platform_registry_api.aws_ecr import AWSECRAuthToken


class TestAWSECRAuthToken:
    @pytest.mark.parametrize(
        "payload",
        (
            {},
            {"authorizationData": []},
            {"authorizationData": [{"authorizationToken": "testtoken"}]},
            {
                "authorizationData": [
                    {"authorizationToken": "testtoken", "expiresAt": "invalid"}
                ]
            },
        ),
    )
    def test_create_from_payload_invalid_payload(self, payload: Dict[str, Any]) -> None:
        with pytest.raises(ValueError, match="invalid payload"):
            AWSECRAuthToken.create_from_payload(payload)

    def test_create_from_payload_expires_at(self):
        token = AWSECRAuthToken.create_from_payload(
            {
                "authorizationData": [
                    {
                        "authorizationToken": "testtoken",
                        "expiresAt": datetime.fromtimestamp(1560000100.0),
                    }
                ]
            },
            time_factory=(lambda: 1560000000.0),
        )
        assert token == AWSECRAuthToken(token="testtoken", expires_at=1560000075.0)

    def test_create_from_payload_already_expired(self):
        with pytest.raises(ValueError, match="already expired"):
            AWSECRAuthToken.create_from_payload(
                {
                    "authorizationData": [
                        {
                            "authorizationToken": "testtoken",
                            "expiresAt": datetime.fromtimestamp(1560000100.0),
                        }
                    ]
                },
                time_factory=(lambda: 1560000100.0),
            )
