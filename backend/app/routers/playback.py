"""Vyhledávání, přehrávání a stahování záznamů."""

from __future__ import annotations

import re
import secrets
import unicodedata
from datetime import date, datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from .. import go2rtc
from ..audit import add_audit
from ..config import settings
from ..db import SessionLocal, get_db
from ..deps import AuthContext, require_operator, ws_authenticate
from ..hikvision import IsapiError, playback_rtsp_path
from ..models import Camera, Nvr
from ..nvr_service import client_for, connection_for
from ..streaming import proxy_stream

router = APIRouter(prefix="/api/playback", tags=["playback"])

MAX_PLAYBACKS_PER_USER = 4
PLAYBACK_WINDOW = timedelta(hours=6)
_active_playbacks: dict[int, int] = {}
_DATE_RE = r"^\d{4}-\d{2}-\d{2}$"
_DATETIME_RE = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$"


def _parse_dt(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Neplatný čas.") from exc


async def _camera_with_nvr(db: AsyncSession, camera_id: int) -> tuple[Camera, Nvr]:
    cam = await db.get(Camera, camera_id)
    nvr = await db.get(Nvr, cam.nvr_id) if cam else None
    if cam is None or nvr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kamera neexistuje.")
    if not nvr.enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Zařízení je vypnuté.")
    return cam, nvr


def _safe_filename(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", normalized).strip("_")
    return cleaned[:60] or "kamera"


@router.get("/{camera_id}/recordings")
async def recordings(
    camera_id: int,
    day: str = Query(alias="date", pattern=_DATE_RE),
    ctx: AuthContext = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    cam, nvr = await _camera_with_nvr(db, camera_id)
    try:
        selected = date.fromisoformat(day)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Neplatné datum.") from exc
    start = datetime.combine(selected, datetime.min.time())
    end = start + timedelta(days=1) - timedelta(seconds=1)
    try:
        segments = await client_for(nvr).search_recordings(cam.channel, start, end)
    except IsapiError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return {
        "camera_id": cam.id,
        "date": day,
        "segments": [
            {
                "start": s.start.isoformat(timespec="seconds"),
                "end": s.end.isoformat(timespec="seconds"),
                "type": s.record_type,
            }
            for s in segments
        ],
    }


@router.get("/{camera_id}/download")
async def download(
    camera_id: int,
    request: Request,
    start: str = Query(pattern=_DATETIME_RE),
    end: str = Query(pattern=_DATETIME_RE),
    ctx: AuthContext = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    cam, nvr = await _camera_with_nvr(db, camera_id)
    seg_start, seg_end = _parse_dt(start), _parse_dt(end)
    if seg_end <= seg_start:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Neplatný časový rozsah.")
    client = client_for(nvr)
    try:
        found = await client.search_recordings(cam.channel, seg_start, seg_end)
    except IsapiError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    segment = next((s for s in found if s.start == seg_start and s.end == seg_end), None)
    if segment is None:
        segment = next((s for s in found if s.start <= seg_start < s.end), None)
    if segment is None or not segment.playback_uri:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Záznam v zadaném čase nebyl nalezen.")

    add_audit(
        db, request, "recording_download",
        f"{nvr.name} / {cam.name}: {segment.start:%d.%m.%Y %H:%M:%S} – {segment.end:%H:%M:%S}", user=ctx.user,
    )
    await db.commit()

    filename = f"{_safe_filename(nvr.name)}_{_safe_filename(cam.name)}_{segment.start:%Y%m%d_%H%M%S}.mp4"
    context = client.download(segment.playback_uri)
    try:
        resp = await context.__aenter__()
    except IsapiError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    async def body():
        try:
            async for chunk in resp.aiter_bytes(64 * 1024):
                yield chunk
        finally:
            await context.__aexit__(None, None, None)

    headers = {
        "Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}",
        "Cache-Control": "no-store",
    }
    length = resp.headers.get("content-length")
    if length and length.isdigit():
        headers["Content-Length"] = length
    return StreamingResponse(body(), media_type="video/mp4", headers=headers)


def playback_source(nvr: Nvr, channel: int, start: datetime) -> str:
    url = connection_for(nvr).rtsp_url(playback_rtsp_path(channel, start, start + PLAYBACK_WINDOW))
    if nvr.transcode:
        return f"ffmpeg:{url}#video=h264"
    if settings.playback_source == "ffmpeg":
        return f"ffmpeg:{url}#video=copy"
    return f"{url}#backchannel=0"


@router.websocket("/{camera_id}/stream")
async def playback_stream(websocket: WebSocket, camera_id: int, start: str):
    ctx = await ws_authenticate(websocket, "operator")
    if ctx is None:
        await websocket.close(code=4401)
        return
    if not re.fullmatch(_DATETIME_RE, start):
        await websocket.close(code=4400)
        return
    try:
        start_dt = datetime.strptime(start, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        await websocket.close(code=4400)
        return

    async with SessionLocal() as db:
        cam = await db.get(Camera, camera_id)
        nvr = await db.get(Nvr, cam.nvr_id) if cam else None
        if cam is None or nvr is None or not nvr.enabled:
            await websocket.close(code=4404)
            return
        try:
            source = playback_source(nvr, cam.channel, start_dt)
        except RuntimeError:
            await websocket.close(code=1011)
            return
        add_audit(
            db, websocket, "recording_playback", f"{nvr.name} / {cam.name}: od {start_dt:%d.%m.%Y %H:%M:%S}",
            user=ctx.user,
        )
        await db.commit()

    user_id = ctx.user.id
    await websocket.accept()
    if _active_playbacks.get(user_id, 0) >= MAX_PLAYBACKS_PER_USER:
        await websocket.send_json(
            {"type": "error", "value": f"Najednou lze přehrávat nejvýše {MAX_PLAYBACKS_PER_USER} záznamy."}
        )
        await websocket.close(code=1008)
        return
    _active_playbacks[user_id] = _active_playbacks.get(user_id, 0) + 1
    name = f"pb_{nvr.id}_{secrets.token_hex(8)}"

    async def cleanup() -> None:
        remaining = _active_playbacks.get(user_id, 1) - 1
        if remaining > 0:
            _active_playbacks[user_id] = remaining
        else:
            _active_playbacks.pop(user_id, None)
        await go2rtc.delete_stream(name)

    try:
        await go2rtc.ensure_stream(name, source)
    except go2rtc.Go2rtcError as exc:
        await cleanup()
        await websocket.send_json({"type": "error", "value": str(exc)})
        await websocket.close(code=1011)
        return
    await proxy_stream(websocket, name, ctx.session.id, on_close=cleanup)
