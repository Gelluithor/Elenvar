"""Správa NVR zařízení a jejich nastavení."""

from __future__ import annotations

import asyncio
import ipaddress
import re
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import go2rtc
from ..audit import add_audit, client_ip
from ..db import get_db
from ..deps import AuthContext, has_role, require_admin, require_viewer
from ..i18n import tr
from ..hikvision import (
    STREAM_INT_FIELDS,
    Connection,
    HikvisionClient,
    IsapiError,
    main_stream_id,
    sub_stream_id,
)
from ..models import Camera, Nvr
from ..monitor import monitor
from ..nvr_service import client_for
from ..ratelimit import test_connection_limiter
from ..security import decrypt, encrypt
from ..views import camera_view, nvr_view

router = APIRouter(prefix="/api/nvrs", tags=["nvrs"])

_HOSTNAME_RE = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")
CONNECTION_FIELDS = {"host", "http_port", "rtsp_port", "use_https", "verify_tls", "username", "password"}
_background: set[asyncio.Task] = set()


def _validate_host(value: str) -> str:
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass
    if not _HOSTNAME_RE.match(value):
        raise ValueError("Zadejte IP adresu nebo název hostitele (bez http:// a cesty).")
    return value.lower()


class NvrBase(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    host: str = Field(min_length=1, max_length=255)
    http_port: int = Field(default=80, ge=1, le=65535)
    rtsp_port: int = Field(default=554, ge=1, le=65535)
    use_https: bool = False
    verify_tls: bool = False
    username: str = Field(min_length=1, max_length=128)
    enabled: bool = True
    transcode: bool = False
    notes: str = Field(default="", max_length=2000)

    @field_validator("host")
    @classmethod
    def _host(cls, value: str) -> str:
        return _validate_host(value)


class NvrCreate(NvrBase):
    password: str = Field(min_length=1, max_length=256)


class NvrUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    host: str | None = Field(default=None, min_length=1, max_length=255)
    http_port: int | None = Field(default=None, ge=1, le=65535)
    rtsp_port: int | None = Field(default=None, ge=1, le=65535)
    use_https: bool | None = None
    verify_tls: bool | None = None
    username: str | None = Field(default=None, min_length=1, max_length=128)
    password: str | None = Field(default=None, min_length=1, max_length=256)
    enabled: bool | None = None
    transcode: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("host")
    @classmethod
    def _host(cls, value: str | None) -> str | None:
        return None if value is None else _validate_host(value)


class NvrTest(BaseModel):
    nvr_id: int | None = None
    host: str = Field(min_length=1, max_length=255)
    http_port: int = Field(default=80, ge=1, le=65535)
    use_https: bool = False
    verify_tls: bool = False
    username: str = Field(min_length=1, max_length=128)
    password: str | None = Field(default=None, max_length=256)

    @field_validator("host")
    @classmethod
    def _host(cls, value: str) -> str:
        return _validate_host(value)


class StreamSettingsIn(BaseModel):
    videoCodecType: str | None = Field(default=None, max_length=32)
    videoQualityControlType: str | None = Field(default=None, max_length=16)
    videoResolutionWidth: int | None = Field(default=None, ge=1, le=16384)
    videoResolutionHeight: int | None = Field(default=None, ge=1, le=16384)
    constantBitRate: int | None = Field(default=None, ge=16, le=100000)
    vbrUpperCap: int | None = Field(default=None, ge=16, le=100000)
    maxFrameRate: int | None = Field(default=None, ge=1, le=12000)
    GovLength: int | None = Field(default=None, ge=1, le=1000)


async def _get_nvr(db: AsyncSession, nvr_id: int) -> Nvr:
    nvr = await db.get(Nvr, nvr_id)
    if nvr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Zařízení neexistuje.")
    return nvr


async def _cameras(db: AsyncSession, nvr_id: int) -> list[Camera]:
    return list((await db.scalars(select(Camera).where(Camera.nvr_id == nvr_id).order_by(Camera.channel))).all())


def _schedule_poll(nvr_id: int) -> None:
    task = asyncio.create_task(monitor.poll_nvr(nvr_id, force=True))
    _background.add(task)
    task.add_done_callback(_background.discard)


def _device_error(exc: IsapiError) -> HTTPException:
    return HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))


@router.get("")
async def list_nvrs(ctx: AuthContext = Depends(require_viewer), db: AsyncSession = Depends(get_db)):
    nvrs = (await db.scalars(select(Nvr).order_by(Nvr.name))).all()
    cams = (await db.scalars(select(Camera))).all()
    by_nvr: dict[int, list[Camera]] = {}
    for cam in cams:
        by_nvr.setdefault(cam.nvr_id, []).append(cam)
    admin = has_role(ctx.user, "admin")
    return [nvr_view(n, by_nvr.get(n.id, []), admin) for n in nvrs]


@router.post("", status_code=201)
async def create_nvr(
    body: NvrCreate,
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    data = body.model_dump()
    password = data.pop("password")
    nvr = Nvr(**data, password_enc=encrypt(password), status="unknown")
    db.add(nvr)
    await db.flush()
    add_audit(db, request, "nvr_created", f"Přidáno zařízení {nvr.name} ({nvr.host})", user=ctx.user)
    await db.commit()
    if nvr.enabled:
        _schedule_poll(nvr.id)
    return nvr_view(nvr, [], True)


@router.post("/test")
async def test_connection(
    body: NvrTest,
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    key = f"{ctx.user.id}:{client_ip(request)}"
    if test_connection_limiter.blocked(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Příliš mnoho testů připojení, zkuste to za chvíli.")
    test_connection_limiter.hit(key)
    password = body.password
    if not password:
        if body.nvr_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Zadejte heslo.")
        existing = await _get_nvr(db, body.nvr_id)
        password = decrypt(existing.password_enc)
    client = HikvisionClient(
        Connection(
            host=body.host,
            http_port=body.http_port,
            rtsp_port=554,
            use_https=body.use_https,
            verify_tls=body.verify_tls,
            username=body.username,
            password=password,
        )
    )
    try:
        info = await client.device_info()
        channels = await client.channels(info["device_type"])
    except IsapiError as exc:
        return {"ok": False, "message": tr(str(exc))}
    return {"ok": True, "info": info, "channel_count": len(channels)}


@router.get("/{nvr_id}")
async def get_nvr(nvr_id: int, ctx: AuthContext = Depends(require_viewer), db: AsyncSession = Depends(get_db)):
    nvr = await _get_nvr(db, nvr_id)
    cams = await _cameras(db, nvr_id)
    data = nvr_view(nvr, cams, has_role(ctx.user, "admin"))
    data["cameras"] = [camera_view(c, nvr) for c in cams]
    return data


@router.patch("/{nvr_id}")
async def update_nvr(
    nvr_id: int,
    body: NvrUpdate,
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    nvr = await _get_nvr(db, nvr_id)
    changes = body.model_dump(exclude_unset=True)
    for key in ("name", "host", "http_port", "rtsp_port", "use_https", "verify_tls", "username", "enabled", "transcode", "notes"):
        if key in changes and changes[key] is None:
            changes.pop(key)
    connection_changed = False
    for key, value in changes.items():
        if key == "password":
            if value:
                nvr.password_enc = encrypt(value)
                connection_changed = True
            continue
        if getattr(nvr, key) != value:
            setattr(nvr, key, value)
            if key in CONNECTION_FIELDS or key == "transcode":
                connection_changed = True
    if connection_changed:
        nvr.status = "unknown"
        nvr.status_message = ""
        monitor.forget_nvr(nvr.id)
    changed_names = ", ".join(k for k in changes if k != "password") + (", heslo" if changes.get("password") else "")
    add_audit(db, request, "nvr_updated", f"Upraveno zařízení {nvr.name}: {changed_names}", user=ctx.user)
    await db.commit()
    if connection_changed:
        await go2rtc.delete_streams_with_prefix(f"nvr{nvr.id}_")
    if nvr.enabled:
        _schedule_poll(nvr.id)
    return nvr_view(nvr, await _cameras(db, nvr_id), True)


@router.delete("/{nvr_id}")
async def delete_nvr(
    nvr_id: int,
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    nvr = await _get_nvr(db, nvr_id)
    name = nvr.name
    await db.delete(nvr)
    add_audit(db, request, "nvr_deleted", f"Smazáno zařízení {name}", user=ctx.user)
    await db.commit()
    monitor.forget_nvr(nvr_id)
    await go2rtc.delete_streams_with_prefix(f"nvr{nvr_id}_")
    return {"ok": True}


@router.post("/{nvr_id}/poll")
async def poll_now(nvr_id: int, ctx: AuthContext = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    await _get_nvr(db, nvr_id)
    await monitor.poll_nvr(nvr_id, force=True)
    db.expire_all()
    nvr = await _get_nvr(db, nvr_id)
    return nvr_view(nvr, await _cameras(db, nvr_id), True)


@router.post("/{nvr_id}/reboot")
async def reboot(
    nvr_id: int,
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    nvr = await _get_nvr(db, nvr_id)
    try:
        await client_for(nvr).reboot()
    except IsapiError as exc:
        add_audit(db, request, "nvr_reboot", f"Restart {nvr.name} selhal: {exc}", user=ctx.user, success=False)
        await db.commit()
        raise _device_error(exc) from exc
    add_audit(db, request, "nvr_reboot", f"Restart zařízení {nvr.name}", user=ctx.user)
    await db.commit()
    return {"ok": True}


def _stream_id(channel: int, kind: Literal["main", "sub"]) -> int:
    return main_stream_id(channel) if kind == "main" else sub_stream_id(channel)


@router.get("/{nvr_id}/channels/{channel}/stream/{kind}")
async def get_stream_settings(
    nvr_id: int,
    channel: int,
    kind: Literal["main", "sub"],
    ctx: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not 1 <= channel <= 512:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Neplatný kanál.")
    nvr = await _get_nvr(db, nvr_id)
    try:
        return await client_for(nvr).get_stream_settings(_stream_id(channel, kind))
    except IsapiError as exc:
        raise _device_error(exc) from exc


@router.put("/{nvr_id}/channels/{channel}/stream/{kind}")
async def set_stream_settings(
    nvr_id: int,
    channel: int,
    kind: Literal["main", "sub"],
    body: StreamSettingsIn,
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not 1 <= channel <= 512:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Neplatný kanál.")
    nvr = await _get_nvr(db, nvr_id)
    changes: dict[str, Any] = {k: v for k, v in body.model_dump().items() if v is not None}
    if not changes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nebyly zadány žádné změny.")
    client = client_for(nvr)
    stream_id = _stream_id(channel, kind)
    try:
        current = await client.get_stream_settings(stream_id)
        _validate_stream_changes(changes, current)
        await client.set_stream_settings(stream_id, changes)
    except IsapiError as exc:
        add_audit(
            db, request, "stream_settings", f"{nvr.name} stream {stream_id}: změna selhala ({exc})",
            user=ctx.user, success=False,
        )
        await db.commit()
        raise _device_error(exc) from exc
    summary = ", ".join(f"{k}={v}" for k, v in changes.items())
    add_audit(db, request, "stream_settings", f"{nvr.name} stream {stream_id}: {summary}", user=ctx.user)
    await db.commit()
    await go2rtc.delete_streams_with_prefix(f"nvr{nvr.id}_ch{channel}_")
    try:
        return await client.get_stream_settings(stream_id)
    except IsapiError:
        return current


def _validate_stream_changes(changes: dict[str, Any], current: dict[str, Any]) -> None:
    options: dict[str, list[str]] = current.get("options", {})
    ranges: dict[str, list[int]] = current.get("ranges", {})
    for field, value in changes.items():
        if field not in current.get("current", {}):
            raise IsapiError(f"Zařízení nepodporuje parametr {field}.")
        allowed = options.get(field)
        if field in STREAM_INT_FIELDS:
            if field in ranges and not ranges[field][0] <= value <= ranges[field][1]:
                raise IsapiError(f"Hodnota {field} musí být v rozsahu {ranges[field][0]}–{ranges[field][1]}.")
            if allowed and field in {"videoResolutionWidth", "videoResolutionHeight", "maxFrameRate"} and str(value) not in allowed:
                raise IsapiError(f"Hodnota {value} pro {field} není podporována.")
        else:
            if allowed and value not in allowed:
                raise IsapiError(f"Hodnota {value} pro {field} není podporována.")
            if not re.fullmatch(r"[A-Za-z0-9.+_-]{1,32}", str(value)):
                raise IsapiError(f"Neplatná hodnota pro {field}.")
    if ("videoResolutionWidth" in changes) != ("videoResolutionHeight" in changes):
        raise IsapiError("Rozlišení je nutné změnit současně (šířka i výška).")
