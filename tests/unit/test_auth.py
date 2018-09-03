import base64

import pytest

from platform_registry_api.auth import BasicCredentials


class TestBasicCredentials:
    def test_from_header_empty(self):
        header = ''
        with pytest.raises(ValueError, match='not enough values to unpack'):
            BasicCredentials.from_authorization_header(header)

    def test_from_header_invalid_auth_type(self):
        header = 'Bearer WHATEVER'
        with pytest.raises(
                ValueError, match='unexpected authentication type "Bearer"'):
            BasicCredentials.from_authorization_header(header)

    def test_from_header_no_credentials_payload(self):
        header = 'Basic '
        with pytest.raises(ValueError, match='not enough values to unpack'):
            BasicCredentials.from_authorization_header(header)

    def test_from_header_invalid_base64_payload(self):
        header = 'Basic ???'
        with pytest.raises(
                ValueError, match='invalid base64 credentials payload'):
            BasicCredentials.from_authorization_header(header)

    def test_from_header_no_credentials_separator(self):
        header = 'Basic ' + base64.b64encode(b'testuser').decode()
        with pytest.raises(ValueError, match='not enough values to unpack'):
            BasicCredentials.from_authorization_header(header)

    def test_from_header_empty_password(self):
        header = 'Basic ' + base64.b64encode(b'testuser:').decode()
        creds = BasicCredentials.from_authorization_header(header)
        assert creds == BasicCredentials(username='testuser', password='')

    def test_from_header(self):
        header = 'Basic ' + base64.b64encode(b'testuser:testpassword').decode()
        creds = BasicCredentials.from_authorization_header(header)
        assert creds == BasicCredentials(
            username='testuser', password='testpassword')
