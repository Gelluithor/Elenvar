"""Auditní záznamy a pomocné funkce pro identifikaci klienta."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import HTTPConnection

from .models import AuditLog, User

log = logging.getLogger("elenvar.audit")


def client_ip(conn: HTTPConnection) -> str:
    # Uvicorn běží s --proxy-headers, takže client.host je skutečná adresa z reverzní proxy.
    return (conn.client.host if conn.client else "")[:64]


def user_agent(conn: HTTPConnection) -> str:
    return conn.headers.get("user-agent", "")[:256]


def add_audit(
    db: AsyncSession,
    conn: HTTPConnection | None,
    action: str,
    detail: str = "",
    user: User | None = None,
    username: str | None = None,
    success: bool = True,
) -> None:
    """Přidá auditní záznam do aktuální transakce (commit provádí volající)."""
    entry = AuditLog(
        user_id=user.id if user else None,
        username=(user.username if user else (username or ""))[:64],
        ip=client_ip(conn) if conn else "",
        action=action,
        detail=detail[:2000],
        success=success,
    )
    db.add(entry)
    log.info(
        "audit action=%s user=%s ip=%s success=%s detail=%s",
        action,
        entry.username,
        entry.ip,
        success,
        detail[:200],
    )
