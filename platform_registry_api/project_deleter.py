import asyncio
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

SUBSCRIBE_RETRY_DELAY = 60.0


class ProjectDeleter:
    ADMIN_STREAM = StreamType("platform-admin")
    PROJECT_REMOVE = EventType("project-remove")

    def __init__(
        self, upstream_client: UpstreamV2ApiClient, config: EventsClientConfig | None
    ) -> None:
        self._upstream_client = upstream_client
        self._client = from_config(config)
        self._subscribe_task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> Self:
        if not await self._subscribe():
            self._subscribe_task = asyncio.create_task(self._subscribe_later())
        return self

    async def __aexit__(self, exc_typ: object, exc_val: object, exc_tb: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._subscribe_task is not None:
            self._subscribe_task.cancel()
            try:
                await self._subscribe_task
            except asyncio.CancelledError:
                pass
            self._subscribe_task = None
        await self._client.aclose()

    async def _subscribe(self) -> bool:
        try:
            logger.info("Subscribe for %r", self.ADMIN_STREAM)
            await self._client.subscribe_group(
                self.ADMIN_STREAM, self._on_admin_event, auto_ack=True
            )
        except Exception:
            logger.exception("Failed to subscribe for %r", self.ADMIN_STREAM)
            return False
        logger.info("Subscribed")
        return True

    async def _subscribe_later(self) -> None:
        while True:
            await asyncio.sleep(SUBSCRIBE_RETRY_DELAY)
            if await self._subscribe():
                return

    async def _on_admin_event(self, ev: RecvEvent) -> None:
        if ev.event_type == self.PROJECT_REMOVE:
            assert ev.org
            assert ev.project
            await self._upstream_client.delete_project_images(
                org=ev.org, project=ev.project
            )
