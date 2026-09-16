from datetime import UTC, datetime
from typing import cast

from apolo_events_client import EventType, RecvEvent, StreamType, Tag

from platform_registry_api.project_deleter import ProjectDeleter
from platform_registry_api.upstream_client import UpstreamV2ApiClient


class FakeUpstreamClient:
    def __init__(self) -> None:
        self.deleted: list[tuple[str, str]] = []

    async def delete_project_images(self, *, org: str, project: str) -> None:
        self.deleted.append((org, project))


def make_event(cluster: str) -> RecvEvent:
    return RecvEvent(
        tag=Tag("1"),
        timestamp=datetime.now(tz=UTC),
        sender="platform-admin",
        stream=StreamType("platform-admin"),
        event_type=EventType("project-remove"),
        cluster=cluster,
        org="org",
        project="project",
        user="user",
    )


async def test_deletes_images_of_own_cluster() -> None:
    upstream = FakeUpstreamClient()
    deleter = ProjectDeleter(cast(UpstreamV2ApiClient, upstream), None, "apolo-main")

    await deleter._on_admin_event(make_event("apolo-main"))

    assert upstream.deleted == [("org", "project")]


async def test_ignores_project_of_other_cluster() -> None:
    upstream = FakeUpstreamClient()
    deleter = ProjectDeleter(cast(UpstreamV2ApiClient, upstream), None, "apolo-main")

    await deleter._on_admin_event(make_event("alfa"))

    assert upstream.deleted == []
