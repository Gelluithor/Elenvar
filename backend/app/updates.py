"""Sledování nových vydání Elenvaru a spouštění aktualizace přes službu updater."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx

from . import app_settings, notify
from .db import SessionLocal, utcnow
from .i18n import tr
from .models import Event
from .version import VERSION, is_newer, parse

log = logging.getLogger("elenvar.updates")

REPO = os.environ.get("ELENVAR_UPDATE_REPO", "Gelluithor/Elenvar").strip()
FEED_URL = os.environ.get("ELENVAR_UPDATE_FEED", "").strip() or f"https://api.github.com/repos/{REPO}/releases?per_page=20"
UPDATER_URL = os.environ.get("ELENVAR_UPDATER_URL", "").strip().rstrip("/")
UPDATER_TOKEN_FILE = Path(os.environ.get("ELENVAR_UPDATER_TOKEN_FILE", "/run/elenvar-updater/token"))
CHECK_INTERVAL = 6 * 3600
MAX_NOTES = 20_000

_last_auto_check = 0.0
_tasks: set[asyncio.Task] = set()


class UpdaterError(Exception):
    pass


async def fetch_latest(include_prereleases: bool) -> dict[str, Any] | None:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": f"Elenvar/{VERSION}"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0), follow_redirects=True) as client:
        resp = await client.get(FEED_URL, headers=headers)
    if resp.status_code == 404:
        raise RuntimeError("Repozitář s vydáními nebyl nalezen.")
    if resp.status_code == 403:
        raise RuntimeError("Služba GitHub dočasně omezila dotazy, zkuste to později.")
    resp.raise_for_status()
    releases = resp.json()
    if not isinstance(releases, list):
        raise RuntimeError("Neočekávaná odpověď serveru s vydáními.")
    best: dict[str, Any] | None = None
    for rel in releases:
        if not isinstance(rel, dict) or rel.get("draft"):
            continue
        if rel.get("prerelease") and not include_prereleases:
            continue
        tag = str(rel.get("tag_name", "")).strip()
        if parse(tag) is None:
            continue
        if best is None or parse(tag) > parse(best["tag_name"]):
            best = rel
    if best is None:
        return None
    return {
        "version": str(best["tag_name"]).lstrip("v"),
        "name": str(best.get("name") or best["tag_name"])[:200],
        "published_at": best.get("published_at"),
        "notes": str(best.get("body") or "")[:MAX_NOTES],
        "url": str(best.get("html_url") or ""),
        "prerelease": bool(best.get("prerelease")),
    }


async def check(notify_new: bool = True) -> dict[str, Any]:
    async with SessionLocal() as db:
        cfg = await app_settings.get_all(db)
    state: dict[str, Any] = dict(cfg.get("update_state") or {})
    state["checked_at"] = utcnow().isoformat()
    try:
        latest = await fetch_latest(bool(cfg.get("update_include_prereleases")))
        state["latest"] = latest
        state["error"] = ""
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        log.warning("Update check failed: %s", exc)
        if isinstance(exc, RuntimeError):
            state["error"] = str(exc)
        elif isinstance(exc, httpx.HTTPError):
            state["error"] = "Server s vydáními není dostupný. Zkontrolujte připojení serveru k internetu."
        else:
            state["error"] = "Server s vydáními vrátil neplatnou odpověď."
        latest = state.get("latest")

    new_version = latest["version"] if latest and is_newer(latest["version"]) else None
    async with SessionLocal() as db:
        announce = bool(new_version) and notify_new and cfg.get("update_notified") != new_version
        values: dict[str, Any] = {"update_state": state}
        if announce:
            values["update_notified"] = new_version
            db.add(Event(severity="info", kind="update_available", message=f"K dispozici je nová verze Elenvar {new_version}"))
        await app_settings.set_many(db, values)
        await db.commit()
    if announce:
        lang = cfg.get("language", "cs")
        await notify.send(
            tr(f"[Elenvar] K dispozici je verze {new_version}", lang),
            f"{tr('Nainstalovaná verze', lang)}: {VERSION}\n{tr('Nová verze', lang)}: {new_version}\n"
            f"{latest.get('url', '') if latest else ''}",
            {"kind": "update_available", "version": new_version},
        )
    return state


async def maybe_auto_check(cfg: dict[str, Any]) -> None:
    global _last_auto_check
    if not cfg.get("update_check_enabled", True):
        return
    if time.monotonic() - _last_auto_check < CHECK_INTERVAL and _last_auto_check:
        return
    _last_auto_check = time.monotonic()
    # Na pozadí, aby pomalé připojení ke GitHubu nezdržovalo monitoring.
    task = asyncio.create_task(check())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


# --- updater -----------------------------------------------------------------

def _token() -> str | None:
    try:
        token = UPDATER_TOKEN_FILE.read_text().strip()
    except OSError:
        return None
    return token or None


def updater_configured() -> bool:
    return bool(UPDATER_URL) and _token() is not None


async def _updater_request(method: str, path: str) -> dict[str, Any]:
    token = _token()
    if not UPDATER_URL or token is None:
        raise UpdaterError("Služba pro aktualizace není nainstalovaná.")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0)) as client:
            resp = await client.request(method, UPDATER_URL + path, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as exc:
        raise UpdaterError("Služba pro aktualizace neodpovídá.") from exc
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code >= 400:
        raise UpdaterError(str(data.get("detail") or f"Služba pro aktualizace vrátila chybu {resp.status_code}."))
    return data


async def updater_status() -> dict[str, Any]:
    return await _updater_request("GET", "/status")


async def start_update() -> dict[str, Any]:
    return await _updater_request("POST", "/update")
