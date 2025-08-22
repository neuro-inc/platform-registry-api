import asyncio
import dataclasses
import logging
from collections.abc import AsyncIterator
from weakref import WeakSet

import aiohttp
import pytest
from aiohttp import web
from apolo_events_client import (
    ClientMessage,
    ClientMsgTypes,
    EventsClientConfig,
    ServerMsgTypes,
    Subscribe,
    Subscribed,
    SubscribeGroup,
)
from pytest_aiohttp import AiohttpServer
from yarl import URL


log = logging.getLogger()


@dataclasses.dataclass
class Queues:
    income: asyncio.Queue[ClientMsgTypes]
    outcome: asyncio.Queue[ServerMsgTypes]


@pytest.fixture
def queues() -> Queues:
    return Queues(asyncio.Queue(), asyncio.Queue())


@pytest.fixture
async def events_server(
    queues: Queues, aiohttp_server: AiohttpServer
) -> AsyncIterator[URL]:
    websockets: WeakSet[web.WebSocketResponse] = WeakSet()

    async def sender(ws: web.WebSocketResponse) -> None:
        while True:
            msg = await queues.outcome.get()
            await ws.send_str(msg.model_dump_json())

    async def stream(req: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(req)

        async with asyncio.TaskGroup() as tg:
            tg.create_task(sender(ws))
            async for ws_msg in ws:
                assert ws_msg.type == aiohttp.WSMsgType.TEXT
                msg = ClientMessage.model_validate_json(ws_msg.data)
                event = msg.root
                log.debug("Event %r", event)
                match event:
                    case Subscribe():
                        await ws.send_str(
                            Subscribed(subscr_id=event.id).model_dump_json()
                        )
                    case SubscribeGroup():
                        await ws.send_str(
                            Subscribed(subscr_id=event.id).model_dump_json()
                        )
                    case _:
                        await queues.income.put(event)
        return ws

    async def on_shutdown(app: web.Application) -> None:
        for ws in list(websockets):
            await ws.close()

    app = aiohttp.web.Application()
    app.router.add_get("/apis/events/v1/stream", stream)
    app.on_shutdown.append(on_shutdown)

    srv = await aiohttp_server(app)
    log.info("Started events test server at %r", srv.make_url("/apis/events"))

    yield srv.make_url("/apis/events")

    log.info("Exit events test server")
    await on_shutdown(app)


@pytest.fixture
def events_config(events_server: URL) -> EventsClientConfig:
    return EventsClientConfig(
        url=events_server, token="token", name="platform-registry"
    )
