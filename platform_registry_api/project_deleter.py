import logging
from typing import Self

from apolo_events_client import (
    EventsClientConfig,
    EventType,
    RecvEvent,
    StreamType,
    from_config,
)

from .registry_client import RegistryApiClient


logger = logging.getLogger(__name__)


class ProjectDeleter:
    ADMIN_STREAM = StreamType("platform-admin")
    PROJECT_REMOVE = EventType("project-remove")

    def __init__(
        self, registry_client: RegistryApiClient, config: EventsClientConfig | None
    ) -> None:
        self._registry_client = registry_client
        self._client = from_config(config)

    async def __aenter__(self) -> Self:
        logger.info("Subscribe for %r", self.ADMIN_STREAM)
        await self._client.subscribe_group(self.ADMIN_STREAM, self._on_admin_event)
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
            await self._registry_client.delete_project_images(
                org=ev.org, project=ev.project
            )
            await self._client.ack({self.ADMIN_STREAM: [ev.tag]})
