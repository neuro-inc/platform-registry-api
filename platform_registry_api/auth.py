import base64
import binascii
from dataclasses import dataclass, field


@dataclass
class BasicCredentials:
    username: str
    password: str = field(repr=False)

    @classmethod
    def from_authorization_header(cls, value: str) -> 'BasicCredentials':
        auth_type, credentials_payload = value.split(' ', 1)
        if auth_type != 'Basic':
            raise ValueError(f'unexpected authentication type "{auth_type}"')

        try:
            credentials = base64.b64decode(credentials_payload, validate=True)
        except binascii.Error:
            raise ValueError('invalid base64 credentials payload')
        username, password = credentials.decode().split(':', 1)
        return cls(username=username, password=password)  # type: ignore
