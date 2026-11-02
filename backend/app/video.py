"""Volba zdroje videa pro go2rtc: přímé RTSP, čtení přes FFmpeg, nebo převod na H.264."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time

from .config import settings
from .hikvision import Connection
from .models import Nvr
from .nvr_service import connection_for
from .rtsp_probe import ProbeResult, probe

log = logging.getLogger("elenvar.video")

STREAM_MODES = ("auto", "direct", "compat")
AUTO_TTL_OK = 30 * 60
AUTO_TTL_FAIL = 2 * 60

# nvr_id -> (platnost do, otisk připojení, číst přes FFmpeg)
_auto: dict[int, tuple[float, str, bool]] = {}
_locks: dict[int, asyncio.Lock] = {}


def _fingerprint(conn: Connection) -> str:
    raw = f"{conn.host}|{conn.rtsp_port}|{conn.username}|{conn.password}"
    return hashlib.sha256(raw.encode()).hexdigest()


def needs_ffmpeg(result: ProbeResult) -> bool:
    """Přímé spojení go2rtc selže, plnohodnotné přihlášení projde."""
    return result.reachable and not result.direct_ok and result.compat_ok


def remember(nvr_id: int, conn: Connection, result: ProbeResult) -> None:
    ttl = AUTO_TTL_OK if result.direct_ok or result.compat_ok else AUTO_TTL_FAIL
    _auto[nvr_id] = (time.monotonic() + ttl, _fingerprint(conn), needs_ffmpeg(result))


def forget(nvr_id: int) -> None:
    _auto.pop(nvr_id, None)


async def _auto_ffmpeg(nvr: Nvr, conn: Connection, path: str) -> bool:
    fingerprint = _fingerprint(conn)
    cached = _auto.get(nvr.id)
    if cached and cached[0] > time.monotonic() and cached[1] == fingerprint:
        return cached[2]
    async with _locks.setdefault(nvr.id, asyncio.Lock()):
        cached = _auto.get(nvr.id)
        if cached and cached[0] > time.monotonic() and cached[1] == fingerprint:
            return cached[2]
        result = await probe(conn, path)
        remember(nvr.id, conn, result)
        if needs_ffmpeg(result):
            log.info("NVR %s: direct RTSP login fails, reading video through FFmpeg", nvr.id)
        return needs_ffmpeg(result)


async def uses_ffmpeg(nvr: Nvr, conn: Connection, path: str) -> bool:
    if nvr.stream_mode == "compat":
        return True
    if nvr.stream_mode == "direct":
        return False
    return await _auto_ffmpeg(nvr, conn, path)


async def source_for(nvr: Nvr, path: str, *, playback: bool = False) -> str:
    conn = connection_for(nvr)
    url = conn.rtsp_url(path)
    if nvr.transcode:
        return f"ffmpeg:{url}#video=h264"
    if await uses_ffmpeg(nvr, conn, path):
        return f"ffmpeg:{url}#video=copy"
    if playback and settings.playback_source == "ffmpeg":
        return f"ffmpeg:{url}#video=copy"
    return f"{url}#backchannel=0"
