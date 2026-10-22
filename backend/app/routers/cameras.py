"""Kamery: seznam, nastavení monitoringu, snímky a živý obraz."""

from __future__ import annotations

import asyncio
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import go2rtc
from ..audit import add_audit
from ..db import SessionLocal, get_db
from ..deps import AuthContext, require_admin, require_viewer, ws_authenticate
from ..hikvision import IsapiError, live_rtsp_path
from ..i18n import tr
from ..models import Camera, Nvr
from ..nvr_service import client_for, connection_for
from ..streaming import proxy_stream
from ..views import camera_view

router = APIRouter(prefix="/api/cameras", tags=["cameras"])

SNAPSHOT_TTL = 10.0
SNAPSHOT_CACHE_MAX = 256
_snapshot_cache: dict[int, tuple[float, bytes, str]] = {}
_nvr_snapshot_limits: dict[int, asyncio.Semaphore] = {}


class CameraUpdate(BaseModel):
    monitored: bool


async def _camera_with_nvr(db: AsyncSession, camera_id: int) -> tuple[Camera, Nvr]:
    cam = await db.get(Camera, camera_id)
    if cam is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kamera neexistuje.")
    nvr = await db.get(Nvr, cam.nvr_id)
    if nvr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kamera neexistuje.")
    return cam, nvr


@router.get("")
async def list_cameras(_: AuthContext = Depends(require_viewer), db: AsyncSession = Depends(get_db)):
    nvrs = {n.id: n for n in (await db.scalars(select(Nvr))).all()}
    cams = (await db.scalars(select(Camera).order_by(Camera.nvr_id, Camera.channel))).all()
    return [camera_view(c, nvrs[c.nvr_id]) for c in cams if c.nvr_id in nvrs]


@router.patch("/{camera_id}")
async def update_camera(
    camera_id: int,
    body: CameraUpdate,
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    cam, nvr = await _camera_with_nvr(db, camera_id)
    if cam.monitored != body.monitored:
        cam.monitored = body.monitored
        state = "zapnut" if body.monitored else "vypnut"
        add_audit(db, request, "camera_monitoring", f"{nvr.name} / {cam.name}: monitoring {state}", user=ctx.user)
        await db.commit()
    return camera_view(cam, nvr)


@router.get("/{camera_id}/snapshot")
async def snapshot(camera_id: int, _: AuthContext = Depends(require_viewer), db: AsyncSession = Depends(get_db)):
    cam, nvr = await _camera_with_nvr(db, camera_id)
    now = time.monotonic()
    cached = _snapshot_cache.get(cam.id)
    if cached is not None and now - cached[0] < SNAPSHOT_TTL:
        return Response(cached[1], media_type=cached[2], headers={"Cache-Control": "private, max-age=10"})
    if nvr.status != "online" or not nvr.enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Zařízení není dostupné.")
    limiter = _nvr_snapshot_limits.setdefault(nvr.id, asyncio.Semaphore(3))
    async with limiter:
        try:
            content, content_type = await client_for(nvr).snapshot(cam.channel)
        except IsapiError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    if len(_snapshot_cache) >= SNAPSHOT_CACHE_MAX:
        oldest = min(_snapshot_cache, key=lambda k: _snapshot_cache[k][0])
        _snapshot_cache.pop(oldest, None)
    _snapshot_cache[cam.id] = (time.monotonic(), content, content_type)
    return Response(content, media_type=content_type, headers={"Cache-Control": "private, max-age=10"})


def live_stream_name(nvr_id: int, channel: int, quality: str) -> str:
    return f"nvr{nvr_id}_ch{channel}_{quality}"


def live_source(nvr: Nvr, channel: int, quality: str) -> str:
    url = connection_for(nvr).rtsp_url(live_rtsp_path(channel, quality))
    if nvr.transcode:
        return f"ffmpeg:{url}#video=h264"
    return f"{url}#backchannel=0"


@router.websocket("/{camera_id}/live")
async def live(websocket: WebSocket, camera_id: int, quality: Literal["main", "sub"] = "sub"):
    ctx = await ws_authenticate(websocket, "viewer")
    if ctx is None:
        await websocket.close(code=4401)
        return
    async with SessionLocal() as db:
        cam = await db.get(Camera, camera_id)
        nvr = await db.get(Nvr, cam.nvr_id) if cam else None
        if cam is None or nvr is None or not nvr.enabled:
            await websocket.close(code=4404)
            return
        try:
            source = live_source(nvr, cam.channel, quality)
        except RuntimeError:
            await websocket.close(code=1011)
            return
        name = live_stream_name(nvr.id, cam.channel, quality)
    await websocket.accept()
    try:
        await go2rtc.ensure_stream(name, source)
    except go2rtc.Go2rtcError as exc:
        await websocket.send_json({"type": "error", "value": tr(str(exc))})
        await websocket.close(code=1011)
        return
    await proxy_stream(websocket, name, ctx.session.id)
