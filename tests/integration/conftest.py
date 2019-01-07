import os

import pytest


@pytest.fixture
def event_loop(loop):
    """
    This fixture mitigates the compatibility issues between
    pytest-asyncio and pytest-aiohttp.
    """
    return loop


@pytest.fixture(scope="session")
def in_docker():
    return os.path.isfile("/.dockerenv")
