"""Události monitoringu a přehled (dashboard)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .. import app_settings
from ..audit import add_audit
from ..db import get_db, utcnow
from ..deps import AuthContext, require_operator, require_viewer
from ..models import Camera, Event, Nvr
from ..nvr_service import disk_problems, is_recorder, load_disks
from ..views import camera_state

router = APIRouter(prefix="/api", tags=["events"])


def _event_view(ev: Event, nvr_names: dict[int, str]) -> dict:
    return {
        "id": ev.id,
        "ts": ev.ts,
        "severity": ev.severity,
        "kind": ev.kind,
        "nvr_id": ev.nvr_id,
        "nvr_name": nvr_names.get(ev.nvr_id or 0, ""),
        "camera_id": ev.camera_id,
        "message": ev.message,
        "acknowledged_at": ev.acknowledged_at,
        "acknowledged_by": ev.acknowledged_by,
    }


@router.get("/events")
async def list_events(
    severity: Literal["info", "warning", "critical"] | None = None,
    nvr_id: int | None = None,
    unacknowledged: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    before_id: int | None = None,
    _: AuthContext = Depends(require_viewer),
    db: AsyncSession = Depends(get_db),
):
    query = select(Event).order_by(Event.id.desc()).limit(limit)
    if severity:
        query = query.where(Event.severity == severity)
    if nvr_id is not None:
        query = query.where(Event.nvr_id == nvr_id)
    if unacknowledged:
        query = query.where(Event.acknowledged_at.is_(None), Event.severity != "info")
    if before_id is not None:
        query = query.where(Event.id < before_id)
    events = (await db.scalars(query)).all()
    names = {n.id: n.name for n in (await db.scalars(select(Nvr))).all()}
    return [_event_view(e, names) for e in events]


@router.post("/events/{event_id}/ack")
async def acknowledge(
    event_id: int,
    ctx: AuthContext = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    ev = await db.get(Event, event_id)
    if ev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Událost neexistuje.")
    if ev.acknowledged_at is None:
        ev.acknowledged_at = utcnow()
        ev.acknowledged_by = ctx.user.username
        await db.commit()
    return {"ok": True}


@router.post("/events/ack-all")
async def acknowledge_all(
    request: Request,
    ctx: AuthContext = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        update(Event)
        .where(Event.acknowledged_at.is_(None), Event.severity != "info")
        .values(acknowledged_at=utcnow(), acknowledged_by=ctx.user.username)
    )
    add_audit(db, request, "events_ack_all", f"Potvrzeno {result.rowcount} událostí", user=ctx.user)
    await db.commit()
    return {"ok": True, "count": result.rowcount}


@router.get("/dashboard")
async def dashboard(_: AuthContext = Depends(require_viewer), db: AsyncSession = Depends(get_db)):
    nvrs = (await db.scalars(select(Nvr).order_by(Nvr.name))).all()
    cams = (await db.scalars(select(Camera).order_by(Camera.nvr_id, Camera.channel))).all()
    by_id = {n.id: n for n in nvrs}
    problems: list[dict] = []
    drift_limit = max(10, int(await app_settings.get(db, "time_drift_threshold")))

    enabled = [n for n in nvrs if n.enabled]
    for nvr in enabled:
        if nvr.status in {"offline", "error", "auth_error"}:
            problems.append(
                {
                    "severity": "critical",
                    "kind": "nvr",
                    "nvr_id": nvr.id,
                    "title": nvr.name,
                    "message": nvr.status_message or "Zařízení je nedostupné",
                    "since": nvr.status_changed_at,
                }
            )
            continue
        if nvr.status != "online":
            continue
        if nvr.last_seen_at:
            for text in disk_problems(load_disks(nvr), is_recorder(nvr.device_type)).values():
                problems.append(
                    {"severity": "critical", "kind": "disk", "nvr_id": nvr.id, "title": nvr.name, "message": text, "since": None}
                )
        if nvr.time_drift_sec is not None and abs(nvr.time_drift_sec) > drift_limit:
            problems.append(
                {
                    "severity": "warning",
                    "kind": "time",
                    "nvr_id": nvr.id,
                    "title": nvr.name,
                    "message": f"Čas zařízení se liší o {nvr.time_drift_sec} s",
                    "since": None,
                }
            )

    monitored_total = 0
    monitored_online = 0
    cams_online = 0
    for cam in cams:
        nvr = by_id.get(cam.nvr_id)
        if nvr is None or not nvr.enabled:
            continue
        state = camera_state(cam, nvr)
        if state == "online":
            cams_online += 1
        if not cam.monitored:
            continue
        monitored_total += 1
        if state == "online":
            monitored_online += 1
        elif state == "offline":
            problems.append(
                {
                    "severity": "warning",
                    "kind": "camera",
                    "nvr_id": nvr.id,
                    "camera_id": cam.id,
                    "title": f"{cam.name} ({nvr.name})",
                    "message": "Kamera je offline" + (f" – {cam.detail}" if cam.detail else ""),
                    "since": cam.status_changed_at,
                }
            )

    unacked = await db.scalar(
        select(func.count(Event.id)).where(Event.acknowledged_at.is_(None), Event.severity != "info")
    )
    order = {"critical": 0, "warning": 1}
    problems.sort(key=lambda p: order.get(p["severity"], 2))
    return {
        "nvr_total": len(enabled),
        "nvr_online": sum(1 for n in enabled if n.status == "online"),
        "camera_total": sum(1 for c in cams if c.nvr_id in by_id and by_id[c.nvr_id].enabled),
        "camera_online": cams_online,
        "monitored_total": monitored_total,
        "monitored_online": monitored_online,
        "unacknowledged_events": int(unacked or 0),
        "problems": problems,
    }
