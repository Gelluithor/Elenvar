"""Závislosti FastAPI: načtení relace, kontrola rolí a CSRF."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import HTTPConnection

from .config import settings
from .db import SessionLocal, get_db, utcnow
from .models import ROLE_RANK, User, UserSession
from .security import hash_token, tokens_equal

SESSION_COOKIE = "__Host-elenvar_session" if settings.cookie_secure else "elenvar_session"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
SESSION_TOUCH_INTERVAL = timedelta(seconds=60)
PENDING_SESSION_TTL = timedelta(minutes=10)


@dataclass
class AuthContext:
    user: User
    session: UserSession


def origin_allowed(headers: Mapping[str, str]) -> bool:
    """Ověří, že požadavek z prohlížeče pochází ze stejného originu."""
    origin = headers.get("origin")
    if origin is None:
        return True
    host = headers.get("host", "")
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    return bool(host) and parsed.netloc.lower() == host.lower()


async def load_session(conn: HTTPConnection, db: AsyncSession) -> AuthContext | None:
    token = conn.cookies.get(SESSION_COOKIE)
    if not token or len(token) > 128:
        return None
    sess = await db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    if sess is None:
        return None
    now = utcnow()
    idle_limit = timedelta(minutes=settings.session_idle_minutes)
    if sess.expires_at <= now or sess.last_seen_at + idle_limit <= now:
        await db.execute(delete(UserSession).where(UserSession.id == sess.id))
        await db.commit()
        return None
    user = await db.get(User, sess.user_id)
    if user is None or not user.is_active:
        await db.execute(delete(UserSession).where(UserSession.id == sess.id))
        await db.commit()
        return None
    if now - sess.last_seen_at >= SESSION_TOUCH_INTERVAL:
        sess.last_seen_at = now
        await db.commit()
    return AuthContext(user=user, session=sess)


def _check_csrf(request: Request, ctx: AuthContext) -> None:
    if request.method in SAFE_METHODS:
        return
    supplied = request.headers.get(CSRF_HEADER, "")
    if not supplied or not tokens_equal(supplied, ctx.session.csrf_token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Neplatný CSRF token. Obnovte stránku.")


def _unauthorized() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "Nejste přihlášeni.")


async def auth_any_stage(request: Request, db: AsyncSession = Depends(get_db)) -> AuthContext:
    """Relace v jakékoli fázi (i čekající na 2FA)."""
    ctx = await load_session(request, db)
    if ctx is None:
        raise _unauthorized()
    _check_csrf(request, ctx)
    return ctx


async def auth_pending(ctx: AuthContext = Depends(auth_any_stage)) -> AuthContext:
    if ctx.session.stage not in {"mfa", "enroll"}:
        raise HTTPException(status.HTTP_409_CONFLICT, "Přihlášení již bylo dokončeno.")
    return ctx


async def auth_full_allow_pw_change(ctx: AuthContext = Depends(auth_any_stage)) -> AuthContext:
    """Plně přihlášený uživatel, i když musí změnit heslo."""
    if ctx.session.stage != "full":
        raise _unauthorized()
    return ctx


async def auth_full(ctx: AuthContext = Depends(auth_full_allow_pw_change)) -> AuthContext:
    if ctx.user.must_change_password:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Nejprve si změňte heslo.")
    return ctx


def require_role(minimum: str):
    min_rank = ROLE_RANK[minimum]

    async def dependency(ctx: AuthContext = Depends(auth_full)) -> AuthContext:
        if ROLE_RANK.get(ctx.user.role, -1) < min_rank:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "K této akci nemáte oprávnění.")
        return ctx

    return dependency


require_viewer = require_role("viewer")
require_operator = require_role("operator")
require_admin = require_role("admin")


def has_role(user: User, minimum: str) -> bool:
    return ROLE_RANK.get(user.role, -1) >= ROLE_RANK[minimum]


async def ws_authenticate(conn: HTTPConnection, minimum: str) -> AuthContext | None:
    """Ověření pro WebSocket (cookie relace + kontrola originu)."""
    if not origin_allowed(conn.headers):
        return None
    async with SessionLocal() as db:
        ctx = await load_session(conn, db)
    if ctx is None or ctx.session.stage != "full" or ctx.user.must_change_password:
        return None
    if not has_role(ctx.user, minimum):
        return None
    return ctx


async def session_still_valid(session_id: int, touch: bool = True) -> bool:
    """Kontrola během dlouhého spojení; sledování videa se počítá jako aktivita."""
    async with SessionLocal() as db:
        sess = await db.get(UserSession, session_id)
        if sess is None or sess.expires_at <= utcnow():
            return False
        user = await db.get(User, sess.user_id)
        if user is None or not user.is_active:
            return False
        if touch:
            sess.last_seen_at = utcnow()
            await db.commit()
    return True
