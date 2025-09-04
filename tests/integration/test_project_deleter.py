from datetime import UTC, datetime
from uuid import uuid4

import pytest
from aiohttp import BasicAuth
from apolo_events_client import (
    Ack,
    EventsClientConfig,
    EventType,
    RecvEvent,
    RecvEvents,
    StreamType,
    Tag,
)
from apolo_events_client.pytest import EventsQueues
from yarl import URL

from platform_registry_api.api import create_app
from platform_registry_api.config import (
    AdminClientConfig,
    AuthConfig,
    Config,
    ServerConfig,
    UpstreamRegistryConfig,
)
from tests import _TestClientFactory


@pytest.fixture
def config(
    admin_token: str, cluster_name: str, events_config: EventsClientConfig
) -> Config:
    upstream_registry = UpstreamRegistryConfig(
        endpoint_url=URL("http://localhost:5002"),
        project="testproject",
        token_endpoint_url=URL("http://localhost:5001/auth"),
        token_service="upstream",
        token_endpoint_username="testuser",
        token_endpoint_password="testpassword",
    )
    auth = AuthConfig(
        server_endpoint_url=URL("http://localhost:5003"), service_token=admin_token
    )
    admin_client = AdminClientConfig(
        endpoint_url=URL("http://admin-api"), token=admin_token
    )
    return Config(
        server=ServerConfig(),
        upstream_registry=upstream_registry,
        auth=auth,
        admin_client=admin_client,
        cluster_name=cluster_name,
        events=events_config,
    )


async def test_deleter(
    aiohttp_client: _TestClientFactory,
    config: Config,
    events_queues: EventsQueues,
) -> None:
    app = await create_app(config)
    client = await aiohttp_client(app)
    auth = BasicAuth(login="admin", password=config.auth.service_token)
    # check that image pushed by project_deleter_fixture.sh with tags exists
    async with client.get("/v2/org/project/alpine/tags/list", auth=auth) as response:
        resp = await response.json()
        assert response.status == 200
        assert set(resp["tags"]) == {"latest", "v1"}
        assert resp["name"] == "org/project/alpine"

    await events_queues.outcome.put(
        RecvEvents(
            subscr_id=uuid4(),
            events=[
                RecvEvent(
                    tag=Tag("123"),
                    timestamp=datetime.now(tz=UTC),
                    sender="platform-admin",
                    stream=StreamType("platform-admin"),
                    event_type=EventType("project-remove"),
                    org="org",
                    cluster="cluster",
                    project="project",
                    user="user",
                ),
            ],
        )
    )

    ev = await events_queues.income.get()

    assert isinstance(ev, Ack)
    assert ev.events[StreamType("platform-admin")] == ["123"]

    # check that image manifests are deleted
    async with client.get("/v2/org/project/alpine/tags/list", auth=auth) as response:
        resp = await response.json()
        assert response.status == 200
        assert not resp["tags"]
        assert resp["name"] == "org/project/alpine"
