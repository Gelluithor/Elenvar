"""Klient pro interní go2rtc (převod RTSP na MSE pro prohlížeč)."""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote

import httpx

from .config import settings

log = logging.getLogger("elenvar.go2rtc")

_client: httpx.AsyncClient | None = None
_lock = asyncio.Lock()


class Go2rtcError(Exception):
    pass


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=settings.go2rtc_url, timeout=httpx.Timeout(10.0, connect=3.0))
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def ws_url(name: str) -> str:
    base = settings.go2rtc_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
    return f"{base}/api/ws?src={quote(name, safe='')}"


async def list_streams() -> dict:
    try:
        resp = await _http().get("/api/streams")
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise Go2rtcError("Služba pro video (go2rtc) není dostupná.") from exc
    return data if isinstance(data, dict) else {}


def _current_source(streams: dict, name: str) -> str | None:
    info = streams.get(name)
    if not isinstance(info, dict):
        return None
    producers = info.get("producers") or []
    if not producers or not isinstance(producers[0], dict):
        return None
    return producers[0].get("url")


async def ensure_stream(name: str, source: str) -> None:
    """Zaregistruje stream; existující se stejným zdrojem se nemění.

    Přepsání běžícího streamu by vytvořilo druhé spojení na NVR, proto se
    nejdřív porovná aktuální zdroj.
    """
    async with _lock:
        streams = await list_streams()
        if _current_source(streams, name) == source:
            return
        try:
            resp = await _http().put("/api/streams", params={"name": name, "src": source})
        except httpx.HTTPError as exc:
            raise Go2rtcError("Služba pro video (go2rtc) není dostupná.") from exc
        if resp.status_code >= 400:
            log.error("go2rtc odmítl stream %s: HTTP %s %s", name, resp.status_code, resp.text[:200])
            raise Go2rtcError("Nepodařilo se připravit video stream.")


async def delete_stream(name: str) -> None:
    try:
        await _http().delete("/api/streams", params={"src": name})
    except httpx.HTTPError as exc:
        log.warning("Nelze odstranit stream %s z go2rtc: %s", name, exc)


async def delete_streams_with_prefix(prefix: str) -> None:
    try:
        streams = await list_streams()
    except Go2rtcError:
        return
    for name in streams:
        if name.startswith(prefix):
            await delete_stream(name)
