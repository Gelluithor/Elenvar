"""Nastavení aplikace uložená v databázi (měněná přes web)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Setting

DEFAULTS: dict[str, Any] = {
    "require_2fa": True,
    "poll_interval": 60,
    "offline_threshold": 2,
    "time_drift_threshold": 120,
    "event_retention_days": 180,
    "audit_retention_days": 365,
    "smtp_enabled": False,
    "smtp_host": "",
    "smtp_port": 587,
    "smtp_security": "starttls",  # starttls | ssl | none
    "smtp_username": "",
    "smtp_password_enc": "",
    "smtp_from": "",
    "smtp_to": "",
    "webhook_enabled": False,
    "webhook_url": "",
    "notify_recoveries": True,
    # jazyk e-mailů a webhooků
    "language": "cs",
    "update_check_enabled": True,
    "update_include_prereleases": False,
    # interní stav kontroly aktualizací (nezobrazuje se v nastavení)
    "update_state": {},
    "update_notified": "",
}

INTERNAL_KEYS = {"update_state", "update_notified"}


async def get_all(db: AsyncSession) -> dict[str, Any]:
    values = dict(DEFAULTS)
    rows = (await db.scalars(select(Setting))).all()
    for row in rows:
        if row.key in DEFAULTS:
            try:
                values[row.key] = json.loads(row.value)
            except json.JSONDecodeError:
                continue
    return values


async def get(db: AsyncSession, key: str) -> Any:
    row = await db.get(Setting, key)
    if row is None:
        return DEFAULTS[key]
    try:
        return json.loads(row.value)
    except json.JSONDecodeError:
        return DEFAULTS[key]


async def set_many(db: AsyncSession, values: dict[str, Any]) -> None:
    for key, value in values.items():
        if key not in DEFAULTS:
            raise KeyError(key)
        row = await db.get(Setting, key)
        encoded = json.dumps(value)
        if row is None:
            db.add(Setting(key=key, value=encoded))
        else:
            row.value = encoded
