"""WebSocket proxy mezi prohlížečem a interním go2rtc (MSE)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable

from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import WebSocketException

from . import go2rtc
from .deps import session_still_valid

log = logging.getLogger("elenvar.stream")

SESSION_CHECK_INTERVAL = 30
MAX_CLIENT_MESSAGE = 2048


async def _send_error(websocket: WebSocket, message: str) -> None:
    with contextlib.suppress(Exception):
        await websocket.send_text(json.dumps({"type": "error", "value": message}))


async def proxy_stream(
    websocket: WebSocket,
    stream_name: str,
    session_id: int,
    on_close: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """Přeposílá MSE data z go2rtc. Websocket musí být již přijatý (accept)."""
    try:
        try:
            upstream_cm = ws_connect(
                go2rtc.ws_url(stream_name),
                max_size=None,
                open_timeout=10,
                ping_interval=20,
                ping_timeout=20,
                compression=None,
            )
            upstream = await upstream_cm
        except (OSError, WebSocketException, asyncio.TimeoutError) as exc:
            log.warning("Nelze se připojit ke go2rtc: %s", exc)
            await _send_error(websocket, "Služba pro video není dostupná.")
            return

        async def client_to_upstream() -> None:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    return
                text = message.get("text")
                if text is None or len(text) > MAX_CLIENT_MESSAGE:
                    continue
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    continue
                # Prohlížeč smí požádat pouze o MSE stream se seznamem kodeků.
                if isinstance(data, dict) and data.get("type") == "mse" and isinstance(data.get("value", ""), str):
                    await upstream.send(json.dumps({"type": "mse", "value": data.get("value", "")}))

        async def upstream_to_client() -> None:
            async for message in upstream:
                if isinstance(message, str):
                    await websocket.send_text(message)
                else:
                    await websocket.send_bytes(message)

        async def session_watchdog() -> None:
            while True:
                await asyncio.sleep(SESSION_CHECK_INTERVAL)
                if not await session_still_valid(session_id):
                    await _send_error(websocket, "Relace vypršela. Přihlaste se znovu.")
                    return

        tasks = [
            asyncio.create_task(client_to_upstream()),
            asyncio.create_task(upstream_to_client()),
            asyncio.create_task(session_watchdog()),
        ]
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                exc = task.exception()
                if exc is not None and not isinstance(exc, (WebSocketDisconnect, WebSocketException, RuntimeError)):
                    log.warning("Chyba streamu %s: %r", stream_name, exc)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            with contextlib.suppress(Exception):
                await upstream.close()
    finally:
        if websocket.application_state == WebSocketState.CONNECTED and websocket.client_state == WebSocketState.CONNECTED:
            with contextlib.suppress(Exception):
                await websocket.close(code=1000)
        if on_close is not None:
            with contextlib.suppress(Exception):
                await on_close()
