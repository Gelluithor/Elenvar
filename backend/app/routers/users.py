"""Správa uživatelů (pouze administrátor)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import add_audit
from ..db import get_db, utcnow
from ..deps import AuthContext, require_admin
from ..models import RecoveryCode, User, UserSession
from ..security import hash_password, password_problem

router = APIRouter(prefix="/api/users", tags=["users"])

Role = Literal["viewer", "operator", "admin"]
USERNAME_PATTERN = r"^[a-z0-9][a-z0-9._-]{2,63}$"


class UserCreate(BaseModel):
    username: str = Field(pattern=USERNAME_PATTERN)
    full_name: str = Field(default="", max_length=128)
    role: Role = "viewer"
    password: str = Field(min_length=1, max_length=256)


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=128)
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=1, max_length=256)
    reset_2fa: bool = False
    unlock: bool = False


def _user_admin_view(user: User) -> dict:
    now = utcnow()
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
        "is_active": user.is_active,
        "totp_enabled": user.totp_enabled,
        "must_change_password": user.must_change_password,
        "locked": bool(user.locked_until and user.locked_until > now),
        "failed_attempts": user.failed_attempts,
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
    }


async def _active_admin_count(db: AsyncSession, exclude_id: int | None = None) -> int:
    query = select(func.count(User.id)).where(User.role == "admin", User.is_active.is_(True))
    if exclude_id is not None:
        query = query.where(User.id != exclude_id)
    return int(await db.scalar(query) or 0)


@router.get("")
async def list_users(_: AuthContext = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    users = (await db.scalars(select(User).order_by(User.username))).all()
    return [_user_admin_view(u) for u in users]


@router.post("", status_code=201)
async def create_user(
    body: UserCreate,
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    username = body.username.lower()
    if await db.scalar(select(User.id).where(User.username == username)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Uživatel s tímto jménem již existuje.")
    problem = password_problem(body.password, username)
    if problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, problem)
    user = User(
        username=username,
        full_name=body.full_name.strip(),
        role=body.role,
        password_hash=hash_password(body.password),
        must_change_password=True,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    add_audit(db, request, "user_created", f"Vytvořen uživatel {username} (role {body.role})", user=ctx.user)
    await db.commit()
    return _user_admin_view(user)


@router.patch("/{user_id}")
async def update_user(
    user_id: int,
    body: UserUpdate,
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Uživatel neexistuje.")
    is_self = user.id == ctx.user.id
    changes: list[str] = []
    revoke_sessions = False

    if body.role is not None and body.role != user.role:
        if is_self:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Vlastní roli nelze změnit.")
        if user.role == "admin" and await _active_admin_count(db, exclude_id=user.id) == 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Musí zůstat alespoň jeden aktivní administrátor.")
        changes.append(f"role {user.role} → {body.role}")
        user.role = body.role
        revoke_sessions = True

    if body.is_active is not None and body.is_active != user.is_active:
        if is_self:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Vlastní účet nelze deaktivovat.")
        if not body.is_active and user.role == "admin" and await _active_admin_count(db, exclude_id=user.id) == 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Musí zůstat alespoň jeden aktivní administrátor.")
        user.is_active = body.is_active
        changes.append("aktivován" if body.is_active else "deaktivován")
        revoke_sessions = True

    if body.full_name is not None and body.full_name.strip() != user.full_name:
        user.full_name = body.full_name.strip()
        changes.append("jméno")

    if body.password is not None:
        if is_self:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Vlastní heslo změňte v nastavení účtu.")
        problem = password_problem(body.password, user.username)
        if problem:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, problem)
        user.password_hash = hash_password(body.password)
        user.must_change_password = True
        user.failed_attempts = 0
        user.locked_until = None
        changes.append("reset hesla")
        revoke_sessions = True

    if body.reset_2fa:
        if is_self:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Vlastní 2FA spravujte v nastavení účtu.")
        user.totp_enabled = False
        user.totp_secret_enc = None
        user.totp_pending_enc = None
        user.totp_last_step = 0
        await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
        changes.append("reset 2FA")
        revoke_sessions = True

    if body.unlock:
        user.failed_attempts = 0
        user.locked_until = None
        changes.append("odblokován")

    if revoke_sessions:
        await db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    if changes:
        add_audit(db, request, "user_updated", f"Uživatel {user.username}: {', '.join(changes)}", user=ctx.user)
    await db.commit()
    return _user_admin_view(user)


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Uživatel neexistuje.")
    if user.id == ctx.user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Vlastní účet nelze smazat.")
    if user.role == "admin" and user.is_active and await _active_admin_count(db, exclude_id=user.id) == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Musí zůstat alespoň jeden aktivní administrátor.")
    username = user.username
    await db.delete(user)
    add_audit(db, request, "user_deleted", f"Smazán uživatel {username}", user=ctx.user)
    await db.commit()
    return {"ok": True}
