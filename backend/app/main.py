"""Vstupní bod aplikace Elenvar."""

from __future__ import annotations

import logging
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import func, select
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("elenvar")
# Každý HTTP požadavek na NVR/go2rtc by zbytečně zahlcoval log.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

from . import go2rtc  # noqa: E402
from .db import SessionLocal, init_db  # noqa: E402
from .deps import SAFE_METHODS, origin_allowed  # noqa: E402
from .hikvision import close_clients  # noqa: E402
from .models import User  # noqa: E402
from .monitor import monitor  # noqa: E402
from .routers import admin, auth, cameras, events, nvrs, playback, system, users  # noqa: E402
from .version import VERSION  # noqa: E402
from .security import hash_password, password_problem  # noqa: E402

_HOST_RE = re.compile(r"^[A-Za-z0-9.\-:\[\]]{1,260}$")


async def bootstrap_admin() -> None:
    async with SessionLocal() as db:
        count = await db.scalar(select(func.count(User.id)))
        if count:
            return
        username = settings.admin_username
        password = settings.admin_password
        generated = password is None
        if generated:
            password = secrets.token_urlsafe(18)
        must_change = generated or password_problem(password, username) is not None
        db.add(
            User(
                username=username,
                full_name="Administrátor",
                role="admin",
                password_hash=hash_password(password),
                must_change_password=must_change,
            )
        )
        await db.commit()
    if generated:
        log.warning(
            "\n%s\n  Vytvořen účet administrátora\n  Uživatel: %s\n  Heslo:    %s\n"
            "  Po přihlášení budete vyzváni ke změně hesla a nastavení 2FA.\n%s",
            "=" * 60, username, password, "=" * 60,
        )
    else:
        log.warning("Vytvořen účet administrátora '%s' (heslo z ELENVAR_ADMIN_PASSWORD).", username)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    await bootstrap_admin()
    # Uklidit případné streamy přehrávání po předchozím běhu.
    await go2rtc.delete_streams_with_prefix("pb_")
    monitor.start()
    log.info("Elenvar %s spuštěn", VERSION)
    try:
        yield
    finally:
        await monitor.stop()
        await close_clients()
        await go2rtc.close()


class SecurityMiddleware:
    """Bezpečnostní hlavičky a kontrola originu pro měnící požadavky."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        path: str = scope["path"]
        if scope["method"] not in SAFE_METHODS and path.startswith("/api/") and not origin_allowed(headers):
            response = JSONResponse({"detail": "Požadavek z cizího původu byl odmítnut."}, status_code=403)
            await response(scope, receive, send)
            return

        host = headers.get("host", "")
        ws_sources = f" wss://{host} ws://{host}" if _HOST_RE.match(host) else ""
        csp = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
            f"media-src 'self' blob:; connect-src 'self'{ws_sources}; font-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'; worker-src 'self' blob:; manifest-src 'self'"
        )

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                h = MutableHeaders(scope=message)
                h["Content-Security-Policy"] = csp
                h["X-Content-Type-Options"] = "nosniff"
                h["X-Frame-Options"] = "DENY"
                h["Referrer-Policy"] = "no-referrer"
                h["Cross-Origin-Opener-Policy"] = "same-origin"
                h["Cross-Origin-Resource-Policy"] = "same-origin"
                h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
                if settings.cookie_secure:
                    h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
                if path.startswith("/api/") and "cache-control" not in h:
                    h["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_wrapper)


app = FastAPI(title="Elenvar", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SecurityMiddleware)

for module in (auth, users, nvrs, cameras, playback, events, admin, system):
    app.include_router(module.router)


@app.get("/api/health", include_in_schema=False)
async def health():
    return {"status": "ok", "version": VERSION}


@app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
async def api_not_found(rest: str):
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Neznámý požadavek.")


STATIC_DIR = settings.static_dir.resolve()
INDEX_FILE = STATIC_DIR / "index.html"


@app.get("/{full_path:path}", include_in_schema=False)
async def spa(full_path: str):
    if full_path:
        candidate = (STATIC_DIR / full_path).resolve()
        if candidate.is_relative_to(STATIC_DIR) and candidate.is_file():
            cache = (
                "public, max-age=31536000, immutable"
                if Path(full_path).parts[:1] == ("assets",)
                else "public, max-age=3600"
            )
            return FileResponse(candidate, headers={"Cache-Control": cache})
    if not INDEX_FILE.is_file():
        return JSONResponse({"detail": "Frontend není sestaven."}, status_code=503)
    return FileResponse(INDEX_FILE, headers={"Cache-Control": "no-cache"})
