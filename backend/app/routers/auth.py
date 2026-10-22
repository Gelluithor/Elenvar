"""Přihlášení, dvoufázové ověření, změna hesla a správa relací."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import app_settings
from ..audit import add_audit, client_ip, user_agent
from ..config import settings
from ..db import get_db, utcnow
from ..deps import (
    PENDING_SESSION_TTL,
    SESSION_COOKIE,
    AuthContext,
    auth_any_stage,
    auth_full,
    auth_full_allow_pw_change,
    load_session,
)
from ..models import RecoveryCode, User, UserSession
from ..ratelimit import login_ip_limiter, mfa_ip_limiter
from ..security import (
    decrypt,
    encrypt,
    hash_password,
    hash_recovery_code,
    hash_token,
    looks_like_recovery_code,
    needs_rehash,
    new_recovery_codes,
    new_token,
    new_totp_secret,
    password_problem,
    qr_data_uri,
    tokens_equal,
    totp_uri,
    verify_password,
    verify_totp,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)
MAX_MFA_ATTEMPTS = 5


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=32)


class ReauthIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)
    code: str = Field(min_length=6, max_length=32)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


def user_public(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
        "totp_enabled": user.totp_enabled,
        "must_change_password": user.must_change_password,
        "last_login_at": user.last_login_at,
    }


def _session_payload(user: User, sess: UserSession) -> dict[str, Any]:
    payload: dict[str, Any] = {"stage": sess.stage, "csrf_token": sess.csrf_token}
    if sess.stage == "full":
        payload["user"] = user_public(user)
    else:
        payload["username"] = user.username
    return payload


def _set_cookie(response: Response, token: str, sess: UserSession) -> None:
    max_age = max(1, int((sess.expires_at - utcnow()).total_seconds()))
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=settings.cookie_secure, httponly=True, samesite="strict")


def _new_session(db: AsyncSession, request: Request, user: User, stage: str) -> tuple[str, UserSession]:
    token = new_token()
    now = utcnow()
    ttl = timedelta(hours=settings.session_max_hours) if stage == "full" else PENDING_SESSION_TTL
    sess = UserSession(
        token_hash=hash_token(token),
        user_id=user.id,
        stage=stage,
        csrf_token=new_token(),
        created_at=now,
        last_seen_at=now,
        expires_at=now + ttl,
        ip=client_ip(request),
        user_agent=user_agent(request),
    )
    db.add(sess)
    return token, sess


def _finalize_login(user: User, now: datetime) -> None:
    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = now


def _error(status_code: int, detail: str, clear_cookie: bool = False) -> JSONResponse:
    resp = JSONResponse({"detail": detail}, status_code=status_code)
    if clear_cookie:
        _clear_cookie(resp)
    return resp


async def _check_second_factor(db: AsyncSession, user: User, code: str) -> str | None:
    """Ověří TOTP nebo recovery kód. Vrací použitou metodu, nebo None."""
    compact = code.strip().replace(" ", "")
    if compact.isdigit() and len(compact) == 6:
        if not user.totp_secret_enc:
            return None
        step = verify_totp(decrypt(user.totp_secret_enc), compact, user.totp_last_step)
        if step is None:
            return None
        user.totp_last_step = step
        return "totp"
    if looks_like_recovery_code(code):
        row = await db.scalar(
            select(RecoveryCode).where(
                RecoveryCode.user_id == user.id,
                RecoveryCode.code_hash == hash_recovery_code(code),
                RecoveryCode.used_at.is_(None),
            )
        )
        if row is None:
            return None
        row.used_at = utcnow()
        return "recovery"
    return None


def _rate_limited(retry_after: int) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "Příliš mnoho pokusů. Zkuste to prosím později.",
        headers={"Retry-After": str(retry_after)},
    )


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    ip = client_ip(request)
    if login_ip_limiter.blocked(ip):
        raise _rate_limited(login_ip_limiter.retry_after(ip))
    login_ip_limiter.hit(ip)

    username = body.username.strip().lower()
    user = await db.scalar(select(User).where(User.username == username))
    now = utcnow()

    if user is not None and user.locked_until is not None and user.locked_until > now:
        verify_password(None, body.password)
        add_audit(db, request, "login_locked", "Pokus o přihlášení k zablokovanému účtu", username=username, success=False)
        await db.commit()
        minutes = max(1, int((user.locked_until - now).total_seconds() // 60) + 1)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Účet je kvůli opakovaným neúspěšným pokusům dočasně zablokován. Zkuste to za {minutes} min.",
        )

    password_ok = verify_password(user.password_hash if user else None, body.password)
    if user is None or not password_ok or not user.is_active:
        if user is not None and not password_ok:
            user.failed_attempts += 1
            if user.failed_attempts >= MAX_FAILED_LOGINS:
                user.locked_until = now + LOCKOUT
        add_audit(db, request, "login_failed", "Neplatné přihlašovací údaje", username=username, success=False)
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Neplatné uživatelské jméno nebo heslo.")

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)

    require_2fa = bool(await app_settings.get(db, "require_2fa"))
    if user.totp_enabled:
        stage = "mfa"
    elif require_2fa:
        stage = "enroll"
    else:
        stage = "full"

    # Ochrana proti fixaci relace – případná stará relace z tohoto prohlížeče se zruší.
    old_token = request.cookies.get(SESSION_COOKIE)
    if old_token:
        await db.execute(delete(UserSession).where(UserSession.token_hash == hash_token(old_token)))

    token, sess = _new_session(db, request, user, stage)
    if stage == "full":
        _finalize_login(user, now)
        add_audit(db, request, "login_success", "Přihlášení heslem (2FA není vyžadováno)", user=user)
    else:
        add_audit(db, request, "login_password_ok", "Heslo ověřeno, čeká se na 2FA", user=user)
    await db.commit()
    _set_cookie(response, token, sess)
    return _session_payload(user, sess)


@router.post("/mfa")
async def verify_mfa(
    body: CodeIn,
    request: Request,
    response: Response,
    ctx: AuthContext = Depends(auth_any_stage),
    db: AsyncSession = Depends(get_db),
):
    if ctx.session.stage != "mfa":
        raise HTTPException(status.HTTP_409_CONFLICT, "Ověření kódem teď není požadováno.")
    ip = client_ip(request)
    if mfa_ip_limiter.blocked(ip):
        raise _rate_limited(mfa_ip_limiter.retry_after(ip))
    mfa_ip_limiter.hit(ip)

    user = ctx.user
    method = await _check_second_factor(db, user, body.code)
    if method is None:
        ctx.session.mfa_attempts += 1
        add_audit(db, request, "mfa_failed", "Neplatný ověřovací kód", user=user, success=False)
        if ctx.session.mfa_attempts >= MAX_MFA_ATTEMPTS:
            await db.delete(ctx.session)
            await db.commit()
            return _error(401, "Příliš mnoho neplatných kódů. Přihlaste se prosím znovu.", clear_cookie=True)
        await db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Neplatný nebo již použitý kód.")

    await db.delete(ctx.session)
    token, sess = _new_session(db, request, user, "full")
    _finalize_login(user, utcnow())
    detail = "Přihlášení s 2FA" if method == "totp" else "Přihlášení recovery kódem"
    add_audit(db, request, "login_success", detail, user=user)
    await db.commit()
    _set_cookie(response, token, sess)
    payload = _session_payload(user, sess)
    if method == "recovery":
        remaining = await db.scalar(
            select(RecoveryCode.id).where(RecoveryCode.user_id == user.id, RecoveryCode.used_at.is_(None)).limit(1)
        )
        payload["recovery_codes_exhausted"] = remaining is None
    return payload


@router.post("/2fa/setup")
async def totp_setup(ctx: AuthContext = Depends(auth_any_stage), db: AsyncSession = Depends(get_db)):
    if ctx.session.stage not in {"enroll", "full"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Nejprve dokončete přihlášení.")
    user = ctx.user
    if user.totp_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Dvoufázové ověření je již zapnuté.")
    secret = new_totp_secret()
    user.totp_pending_enc = encrypt(secret)
    await db.commit()
    uri = totp_uri(secret, user.username)
    return {"secret": secret, "otpauth_uri": uri, "qr": qr_data_uri(uri)}


@router.post("/2fa/enable")
async def totp_enable(
    body: CodeIn,
    request: Request,
    response: Response,
    ctx: AuthContext = Depends(auth_any_stage),
    db: AsyncSession = Depends(get_db),
):
    if ctx.session.stage not in {"enroll", "full"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Nejprve dokončete přihlášení.")
    user = ctx.user
    if user.totp_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Dvoufázové ověření je již zapnuté.")
    if not user.totp_pending_enc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nejprve spusťte nastavení dvoufázového ověření.")

    pending = user.totp_pending_enc
    step = verify_totp(decrypt(pending), body.code, 0)
    if step is None:
        if ctx.session.stage == "enroll":
            ctx.session.mfa_attempts += 1
            if ctx.session.mfa_attempts >= MAX_MFA_ATTEMPTS * 2:
                await db.delete(ctx.session)
                await db.commit()
                return _error(401, "Příliš mnoho neplatných kódů. Přihlaste se prosím znovu.", clear_cookie=True)
            await db.commit()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Kód nesouhlasí. Zkontrolujte, že má telefon správný čas, a zadejte aktuální kód.",
        )

    user.totp_secret_enc = pending
    user.totp_pending_enc = None
    user.totp_enabled = True
    user.totp_last_step = step
    await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    codes = new_recovery_codes()
    for code in codes:
        db.add(RecoveryCode(user_id=user.id, code_hash=hash_recovery_code(code)))
    add_audit(db, request, "2fa_enabled", "Zapnuto dvoufázové ověření", user=user)

    result: dict[str, Any] = {"recovery_codes": codes}
    if ctx.session.stage == "enroll":
        await db.delete(ctx.session)
        token, sess = _new_session(db, request, user, "full")
        _finalize_login(user, utcnow())
        add_audit(db, request, "login_success", "Přihlášení po nastavení 2FA", user=user)
        await db.commit()
        _set_cookie(response, token, sess)
        result.update(_session_payload(user, sess))
    else:
        await db.commit()
        result.update(_session_payload(user, ctx.session))
    return result


@router.post("/2fa/disable")
async def totp_disable(
    body: ReauthIn,
    request: Request,
    ctx: AuthContext = Depends(auth_full),
    db: AsyncSession = Depends(get_db),
):
    if await app_settings.get(db, "require_2fa"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Dvoufázové ověření je v této instalaci povinné.")
    user = ctx.user
    if not user.totp_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Dvoufázové ověření není zapnuté.")
    if not verify_password(user.password_hash, body.password) or await _check_second_factor(db, user, body.code) is None:
        add_audit(db, request, "2fa_disable_failed", "Neplatné heslo nebo kód", user=user, success=False)
        await db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Neplatné heslo nebo ověřovací kód.")
    user.totp_enabled = False
    user.totp_secret_enc = None
    user.totp_pending_enc = None
    await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    add_audit(db, request, "2fa_disabled", "Vypnuto dvoufázové ověření", user=user)
    await db.commit()
    return {"ok": True}


@router.post("/2fa/recovery-codes")
async def regenerate_recovery_codes(
    body: ReauthIn,
    request: Request,
    ctx: AuthContext = Depends(auth_full),
    db: AsyncSession = Depends(get_db),
):
    user = ctx.user
    if not user.totp_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Dvoufázové ověření není zapnuté.")
    if not verify_password(user.password_hash, body.password) or await _check_second_factor(db, user, body.code) is None:
        add_audit(db, request, "recovery_codes_failed", "Neplatné heslo nebo kód", user=user, success=False)
        await db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Neplatné heslo nebo ověřovací kód.")
    await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    codes = new_recovery_codes()
    for code in codes:
        db.add(RecoveryCode(user_id=user.id, code_hash=hash_recovery_code(code)))
    add_audit(db, request, "recovery_codes_regenerated", "Vygenerovány nové recovery kódy", user=user)
    await db.commit()
    return {"recovery_codes": codes}


@router.get("/me")
async def me(request: Request, db: AsyncSession = Depends(get_db)):
    ctx = await load_session(request, db)
    if ctx is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Nejste přihlášeni.")
    payload = _session_payload(ctx.user, ctx.session)
    payload["require_2fa"] = bool(await app_settings.get(db, "require_2fa"))
    if ctx.session.stage == "full":
        remaining = (
            await db.scalars(
                select(RecoveryCode.id).where(RecoveryCode.user_id == ctx.user.id, RecoveryCode.used_at.is_(None))
            )
        ).all()
        payload["recovery_codes_left"] = len(remaining)
    return payload


@router.post("/logout")
async def logout(request: Request, db: AsyncSession = Depends(get_db)):
    ctx = await load_session(request, db)
    resp = JSONResponse({"ok": True})
    if ctx is not None:
        supplied = request.headers.get("x-csrf-token", "")
        if not supplied or not tokens_equal(supplied, ctx.session.csrf_token):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Neplatný CSRF token.")
        await db.delete(ctx.session)
        add_audit(db, request, "logout", "Odhlášení", user=ctx.user)
        await db.commit()
    _clear_cookie(resp)
    return resp


@router.post("/password")
async def change_password(
    body: PasswordChangeIn,
    request: Request,
    ctx: AuthContext = Depends(auth_full_allow_pw_change),
    db: AsyncSession = Depends(get_db),
):
    ip = client_ip(request)
    if login_ip_limiter.blocked(ip):
        raise _rate_limited(login_ip_limiter.retry_after(ip))
    user = ctx.user
    if not verify_password(user.password_hash, body.current_password):
        login_ip_limiter.hit(ip)
        add_audit(db, request, "password_change_failed", "Neplatné současné heslo", user=user, success=False)
        await db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Současné heslo není správné.")
    problem = password_problem(body.new_password, user.username)
    if problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, problem)
    if verify_password(user.password_hash, body.new_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nové heslo musí být jiné než současné.")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    await db.execute(delete(UserSession).where(UserSession.user_id == user.id, UserSession.id != ctx.session.id))
    add_audit(db, request, "password_changed", "Změna hesla (ostatní relace odhlášeny)", user=user)
    await db.commit()
    return {"ok": True, "user": user_public(user)}


@router.get("/sessions")
async def list_sessions(ctx: AuthContext = Depends(auth_full), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.scalars(
            select(UserSession)
            .where(UserSession.user_id == ctx.user.id, UserSession.stage == "full")
            .order_by(UserSession.last_seen_at.desc())
        )
    ).all()
    return [
        {
            "id": s.id,
            "created_at": s.created_at,
            "last_seen_at": s.last_seen_at,
            "expires_at": s.expires_at,
            "ip": s.ip,
            "user_agent": s.user_agent,
            "current": s.id == ctx.session.id,
        }
        for s in rows
    ]


@router.delete("/sessions/{session_id}")
async def revoke_session(
    session_id: int,
    request: Request,
    ctx: AuthContext = Depends(auth_full),
    db: AsyncSession = Depends(get_db),
):
    sess = await db.get(UserSession, session_id)
    if sess is None or sess.user_id != ctx.user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Relace neexistuje.")
    if sess.id == ctx.session.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Aktuální relaci ukončete odhlášením.")
    await db.delete(sess)
    add_audit(db, request, "session_revoked", f"Ukončena relace z {sess.ip}", user=ctx.user)
    await db.commit()
    return {"ok": True}
