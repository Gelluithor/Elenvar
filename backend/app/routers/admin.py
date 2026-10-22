"""Systémová nastavení a auditní log (pouze administrátor)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import app_settings, notify
from ..audit import add_audit
from ..db import get_db
from ..deps import AuthContext, require_admin
from ..models import AuditLog, User, UserSession
from ..monitor import monitor
from ..security import encrypt

router = APIRouter(prefix="/api", tags=["admin"])


class SettingsIn(BaseModel):
    require_2fa: bool | None = None
    poll_interval: int | None = Field(default=None, ge=15, le=3600)
    offline_threshold: int | None = Field(default=None, ge=1, le=20)
    time_drift_threshold: int | None = Field(default=None, ge=10, le=86400)
    event_retention_days: int | None = Field(default=None, ge=1, le=3650)
    audit_retention_days: int | None = Field(default=None, ge=30, le=3650)
    smtp_enabled: bool | None = None
    smtp_host: str | None = Field(default=None, max_length=255)
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_security: Literal["starttls", "ssl", "none"] | None = None
    smtp_username: str | None = Field(default=None, max_length=255)
    smtp_password: str | None = Field(default=None, max_length=512)
    smtp_from: str | None = Field(default=None, max_length=255)
    smtp_to: str | None = Field(default=None, max_length=1000)
    webhook_enabled: bool | None = None
    webhook_url: str | None = Field(default=None, max_length=2000)
    notify_recoveries: bool | None = None
    update_check_enabled: bool | None = None
    update_include_prereleases: bool | None = None

    @field_validator("webhook_url")
    @classmethod
    def _webhook(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return value
        value = value.strip()
        if not (value.startswith("https://") or value.startswith("http://")):
            raise ValueError("URL webhooku musí začínat http:// nebo https://")
        return value

    @field_validator("smtp_host", "smtp_username", "smtp_from", "smtp_to")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if any(ch in value for ch in "\r\n"):
            raise ValueError("Hodnota nesmí obsahovat zalomení řádku")
        return value


def _public_settings(values: dict[str, Any]) -> dict[str, Any]:
    data = {k: v for k, v in values.items() if k != "smtp_password_enc" and k not in app_settings.INTERNAL_KEYS}
    data["smtp_password_set"] = bool(values.get("smtp_password_enc"))
    return data


@router.get("/settings")
async def get_settings(_: AuthContext = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    return _public_settings(await app_settings.get_all(db))


@router.put("/settings")
async def put_settings(
    body: SettingsIn,
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    current = await app_settings.get_all(db)
    if "smtp_password" in changes:
        password = changes.pop("smtp_password")
        changes["smtp_password_enc"] = encrypt(password) if password else ""

    turning_on_2fa = changes.get("require_2fa") is True and not current["require_2fa"]
    if turning_on_2fa and not ctx.user.totp_enabled:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Před vynucením 2FA si nejprve zapněte dvoufázové ověření u svého účtu.",
        )

    await app_settings.set_many(db, changes)
    if turning_on_2fa:
        # Uživatelé bez 2FA se musí přihlásit znovu a projít nastavením.
        without_2fa = select(User.id).where(User.totp_enabled.is_(False))
        await db.execute(delete(UserSession).where(UserSession.user_id.in_(without_2fa)))
    names = ", ".join(sorted(k.replace("_enc", "") for k in changes))
    add_audit(db, request, "settings_updated", f"Změněna nastavení: {names}", user=ctx.user)
    await db.commit()
    if "poll_interval" in changes:
        monitor.wake()
    return _public_settings(await app_settings.get_all(db))


@router.post("/settings/test-notification")
async def test_notification(ctx: AuthContext = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    cfg = await app_settings.get_all(db)
    if not notify.enabled_channels(cfg):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Není zapnutý žádný kanál upozornění.")
    errors = await notify.send(
        "[Elenvar] Testovací upozornění",
        f"Toto je testovací upozornění odeslané uživatelem {ctx.user.username}.",
        {"severity": "info", "kind": "test"},
    )
    return {"ok": not errors, "errors": errors}


@router.get("/audit")
async def audit_log(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    q: str | None = Query(default=None, max_length=100),
    _: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    query = select(AuditLog)
    count_query = select(func.count(AuditLog.id))
    if q:
        pattern = f"%{q.replace('%', '').replace('_', '')}%"
        cond = or_(AuditLog.username.ilike(pattern), AuditLog.action.ilike(pattern), AuditLog.detail.ilike(pattern), AuditLog.ip.ilike(pattern))
        query = query.where(cond)
        count_query = count_query.where(cond)
    rows = (await db.scalars(query.order_by(AuditLog.id.desc()).limit(limit).offset(offset))).all()
    total = int(await db.scalar(count_query) or 0)
    return {
        "total": total,
        "items": [
            {
                "id": r.id,
                "ts": r.ts,
                "username": r.username,
                "ip": r.ip,
                "action": r.action,
                "detail": r.detail,
                "success": r.success,
            }
            for r in rows
        ],
    }
