import logging
from typing import Self

from apolo_events_client import (
    EventsClientConfig,
    EventType,
    RecvEvent,
    StreamType,
    from_config,
)

from .upstream_client import UpstreamV2ApiClient


logger = logging.getLogger(__name__)


class ProjectDeleter:
    ADMIN_STREAM = StreamType("platform-admin")
    PROJECT_REMOVE = EventType("project-remove")

    def __init__(
        self, upstream_client: UpstreamV2ApiClient, config: EventsClientConfig | None
    ) -> None:
        self._upstream_client = upstream_client
        self._client = from_config(config)

    async def __aenter__(self) -> Self:
        logger.info("Subscribe for %r", self.ADMIN_STREAM)
        await self._client.subscribe_group(
            self.ADMIN_STREAM, self._on_admin_event, auto_ack=True
        )
        logger.info("Subscribed")
        return self

    async def __aexit__(self, exc_typ: object, exc_val: object, exc_tb: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _on_admin_event(self, ev: RecvEvent) -> None:
        if ev.event_type == self.PROJECT_REMOVE:
            assert ev.org
            assert ev.project
            await self._upstream_client.delete_project_images(
                org=ev.org, project=ev.project
            )
