"""Verze, kontrola a instalace aktualizací (pouze administrátor)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .. import app_settings, updates
from ..audit import add_audit
from ..db import get_db
from ..deps import AuthContext, require_admin
from ..security import verify_password
from ..version import VERSION, is_newer

router = APIRouter(prefix="/api/system", tags=["system"])


class InstallIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)


def _view(state: dict, updater: dict | None, updater_error: str) -> dict:
    latest = state.get("latest")
    return {
        "current": VERSION,
        "latest": latest,
        "update_available": bool(latest and is_newer(latest["version"])),
        "checked_at": state.get("checked_at"),
        "error": state.get("error", ""),
        "repo": updates.REPO,
        "updater_available": updater is not None,
        "updater_error": updater_error,
        "updater": updater,
    }


async def _status(db: AsyncSession) -> dict:
    state = await app_settings.get(db, "update_state") or {}
    updater, error = None, ""
    try:
        updater = await updates.updater_status()
    except updates.UpdaterError as exc:
        error = str(exc)
    return _view(state, updater, error)


@router.get("/update")
async def update_info(_: AuthContext = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    return await _status(db)


@router.post("/update/check")
async def update_check(_: AuthContext = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    await updates.check()
    db.expire_all()
    return await _status(db)


@router.post("/update/install", status_code=202)
async def update_install(
    body: InstallIn,
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(ctx.user.password_hash, body.password):
        add_audit(db, request, "update_install", "Neplatné heslo při potvrzení aktualizace", user=ctx.user, success=False)
        await db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Heslo není správné.")
    state = await app_settings.get(db, "update_state") or {}
    target = (state.get("latest") or {}).get("version", "")
    try:
        updater = await updates.start_update()
    except updates.UpdaterError as exc:
        add_audit(db, request, "update_install", f"Spuštění aktualizace selhalo: {exc}", user=ctx.user, success=False)
        await db.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    add_audit(db, request, "update_install", f"Spuštěna aktualizace z {VERSION} na {target or 'nejnovější verzi'}", user=ctx.user)
    await db.commit()
    return _view(state, updater, "")
