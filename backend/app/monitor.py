"""Periodický monitoring NVR a kamer."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import app_settings, notify, updates
from .db import SessionLocal, utcnow
from .hikvision import ChannelInfo, IsapiAuthError, IsapiError, IsapiUnreachable, drift_seconds
from .models import AuditLog, Camera, Event, Nvr, UserSession
from .nvr_service import client_for, disk_problems, is_recorder, load_disks

log = logging.getLogger("elenvar.monitor")

Notification = tuple[str, str, dict[str, Any]]


class Monitor:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._nvr_failures: dict[int, int] = {}
        self._cam_failures: dict[int, int] = {}
        self._locks: dict[int, asyncio.Lock] = {}
        self._semaphore = asyncio.Semaphore(8)
        self._last_cleanup = 0.0
        self._notify_tasks: set[asyncio.Task] = set()

    # --- životní cyklus ------------------------------------------------------

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="elenvar-monitor")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def wake(self) -> None:
        self._wake.set()

    def forget_nvr(self, nvr_id: int) -> None:
        self._nvr_failures.pop(nvr_id, None)
        self._locks.pop(nvr_id, None)

    async def _run(self) -> None:
        await asyncio.sleep(3)
        while True:
            cfg: dict[str, Any] = dict(app_settings.DEFAULTS)
            try:
                async with SessionLocal() as db:
                    cfg = await app_settings.get_all(db)
                await self.poll_all(cfg)
                await self._cleanup(cfg)
                await updates.maybe_auto_check(cfg)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 – smyčka nesmí spadnout
                log.exception("Chyba v monitorovací smyčce")
            interval = max(15, min(3600, int(cfg.get("poll_interval", 60))))
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    async def poll_all(self, cfg: dict[str, Any]) -> None:
        async with SessionLocal() as db:
            ids = (await db.scalars(select(Nvr.id).where(Nvr.enabled.is_(True)))).all()
        results = await asyncio.gather(*(self.poll_nvr(nvr_id, cfg) for nvr_id in ids), return_exceptions=True)
        for nvr_id, result in zip(ids, results):
            if isinstance(result, Exception):
                log.error("Dotazování NVR %s selhalo: %r", nvr_id, result)

    async def _cleanup(self, cfg: dict[str, Any]) -> None:
        if time.monotonic() - self._last_cleanup < 3600:
            return
        self._last_cleanup = time.monotonic()
        now = utcnow()
        async with SessionLocal() as db:
            event_days = max(1, int(cfg.get("event_retention_days", 180)))
            audit_days = max(1, int(cfg.get("audit_retention_days", 365)))
            await db.execute(delete(Event).where(Event.ts < now - timedelta(days=event_days)))
            await db.execute(delete(AuditLog).where(AuditLog.ts < now - timedelta(days=audit_days)))
            await db.execute(delete(UserSession).where(UserSession.expires_at < now))
            await db.commit()

    # --- dotazování jednoho NVR ---------------------------------------------

    async def poll_nvr(self, nvr_id: int, cfg: dict[str, Any] | None = None, force: bool = False) -> None:
        if cfg is None:
            async with SessionLocal() as db:
                cfg = await app_settings.get_all(db)
        lock = self._locks.setdefault(nvr_id, asyncio.Lock())
        async with lock, self._semaphore:
            notifications: list[Notification] = []
            async with SessionLocal() as db:
                nvr = await db.get(Nvr, nvr_id)
                if nvr is None or (not nvr.enabled and not force):
                    return
                # Po chybném přihlášení se nedotazujeme, aby se účet na NVR nezablokoval.
                if nvr.status == "auth_error" and not force:
                    return
                await self._poll(db, nvr, cfg, notifications)
                await db.commit()
            self._dispatch(notifications)

    async def _poll(self, db: AsyncSession, nvr: Nvr, cfg: dict[str, Any], out: list[Notification]) -> None:
        now = utcnow()
        threshold = max(1, int(cfg.get("offline_threshold", 2)))
        nvr.last_poll_at = now
        previously_seen = nvr.last_seen_at is not None
        try:
            client = client_for(nvr)
            info = await client.device_info()
            channels = await client.channels(info["device_type"])
            try:
                disks: list[dict[str, Any]] | None = await client.storage()
            except IsapiError as exc:
                log.info("NVR %s: stav disků nelze načíst: %s", nvr.id, exc)
                disks = None
            try:
                device_time = await client.device_time()
            except IsapiError:
                device_time = ""
        except IsapiAuthError as exc:
            self._nvr_failures.pop(nvr.id, None)
            nvr.status_message = str(exc)
            if nvr.status != "auth_error":
                nvr.status = "auth_error"
                nvr.status_changed_at = now
                self._event(
                    db, out, cfg, "critical", "nvr_auth_error", nvr,
                    f"{nvr.name}: zařízení odmítlo přihlášení – dotazování je pozastaveno do opravy údajů",
                )
            return
        except (IsapiError, RuntimeError) as exc:
            count = self._nvr_failures.get(nvr.id, 0) + 1
            self._nvr_failures[nvr.id] = count
            nvr.status_message = str(exc)
            target = "offline" if isinstance(exc, IsapiUnreachable) else "error"
            if count >= threshold and nvr.status not in {"offline", "error"}:
                nvr.status = target
                nvr.status_changed_at = now
                self._event(db, out, cfg, "critical", "nvr_offline", nvr, f"{nvr.name} je nedostupný: {exc}")
            elif nvr.status in {"offline", "error"}:
                nvr.status = target
            return

        self._nvr_failures.pop(nvr.id, None)
        if nvr.status != "online":
            if nvr.status in {"offline", "error", "auth_error"}:
                self._event(db, out, cfg, "info", "nvr_online", nvr, f"{nvr.name} je opět dostupný", recovery=True)
            nvr.status = "online"
            nvr.status_changed_at = now
        nvr.status_message = ""
        nvr.last_seen_at = now
        for key, value in info.items():
            setattr(nvr, key, value)

        old_drift = nvr.time_drift_sec
        nvr.device_time = device_time
        nvr.time_drift_sec = drift_seconds(device_time)
        drift_limit = max(10, int(cfg.get("time_drift_threshold", 120)))
        was_bad = old_drift is not None and abs(old_drift) > drift_limit
        is_bad = nvr.time_drift_sec is not None and abs(nvr.time_drift_sec) > drift_limit
        if is_bad and not was_bad:
            self._event(
                db, out, cfg, "warning", "time_drift", nvr,
                f"{nvr.name}: čas zařízení se liší o {nvr.time_drift_sec} s – zkontrolujte NTP",
            )
        elif was_bad and nvr.time_drift_sec is not None and not is_bad:
            self._event(db, out, cfg, "info", "time_ok", nvr, f"{nvr.name}: čas zařízení je opět v pořádku", recovery=True)

        await self._sync_cameras(db, nvr, channels, cfg, threshold, out)
        if disks is not None:
            self._sync_disks(db, nvr, disks, previously_seen, cfg, out)

    async def _sync_cameras(
        self,
        db: AsyncSession,
        nvr: Nvr,
        channels: list[ChannelInfo],
        cfg: dict[str, Any],
        threshold: int,
        out: list[Notification],
    ) -> None:
        now = utcnow()
        existing = {c.channel: c for c in (await db.scalars(select(Camera).where(Camera.nvr_id == nvr.id))).all()}
        seen: set[int] = set()
        for ch in channels:
            seen.add(ch.channel)
            cam = existing.get(ch.channel)
            if cam is None:
                cam = Camera(
                    nvr_id=nvr.id,
                    channel=ch.channel,
                    name=ch.name,
                    ip_address=ch.ip_address,
                    detail=ch.detail,
                    online=ch.online,
                    monitored=True,
                    status_changed_at=now,
                    last_online_at=now if ch.online else None,
                )
                db.add(cam)
                await db.flush()
                self._event(
                    db, out, cfg, "info", "camera_added", nvr,
                    f"{nvr.name}: nalezena kamera „{cam.name}“ (kanál {cam.channel})", camera=cam, send=False,
                )
                if ch.online is False:
                    self._event(
                        db, out, cfg, "warning", "camera_offline", nvr,
                        f"{nvr.name}: kamera „{cam.name}“ (kanál {cam.channel}) je offline", camera=cam,
                    )
                continue

            cam.name = ch.name
            cam.ip_address = ch.ip_address
            cam.detail = ch.detail
            if ch.online is True:
                cam.last_online_at = now
                self._cam_failures.pop(cam.id, None)
                if cam.online is not True:
                    was_offline = cam.online is False
                    cam.online = True
                    cam.status_changed_at = now
                    if was_offline and cam.monitored:
                        self._event(
                            db, out, cfg, "info", "camera_online", nvr,
                            f"{nvr.name}: kamera „{cam.name}“ (kanál {cam.channel}) je opět online",
                            camera=cam, recovery=True,
                        )
            elif ch.online is False:
                count = self._cam_failures.get(cam.id, 0) + 1
                self._cam_failures[cam.id] = count
                if cam.online is not False and (count >= threshold or cam.online is None):
                    cam.online = False
                    cam.status_changed_at = now
                    if cam.monitored:
                        self._event(
                            db, out, cfg, "warning", "camera_offline", nvr,
                            f"{nvr.name}: kamera „{cam.name}“ (kanál {cam.channel}) je offline"
                            + (f" ({ch.detail})" if ch.detail else ""),
                            camera=cam,
                        )
            else:
                self._cam_failures.pop(cam.id, None)
                cam.online = None

        if not channels and existing:
            # Prázdný seznam při existujících kamerách je spíš chyba zařízení – nic nemažeme.
            log.warning("NVR %s vrátil prázdný seznam kanálů, kamery ponechány", nvr.id)
            return
        for channel, cam in existing.items():
            if channel in seen:
                continue
            self._event(
                db, out, cfg, "info", "camera_removed", nvr,
                f"{nvr.name}: kamera „{cam.name}“ (kanál {channel}) byla odebrána z konfigurace NVR",
                send=cam.monitored,
            )
            self._cam_failures.pop(cam.id, None)
            await db.delete(cam)

    def _sync_disks(
        self,
        db: AsyncSession,
        nvr: Nvr,
        disks: list[dict[str, Any]],
        previously_seen: bool,
        cfg: dict[str, Any],
        out: list[Notification],
    ) -> None:
        recorder = is_recorder(nvr.device_type)
        old = disk_problems(load_disks(nvr), recorder) if previously_seen else {}
        new = disk_problems(disks, recorder)
        for key, text in new.items():
            if old.get(key) != text:
                self._event(db, out, cfg, "critical", "hdd_error", nvr, f"{nvr.name}: problém s úložištěm – {text}")
        for key, text in old.items():
            if key not in new:
                self._event(
                    db, out, cfg, "info", "hdd_ok", nvr, f"{nvr.name}: úložiště v pořádku ({text.split(' – ')[0]})",
                    recovery=True,
                )
        nvr.hdd_json = json.dumps(disks, ensure_ascii=False)

    # --- události a upozornění ----------------------------------------------

    def _event(
        self,
        db: AsyncSession,
        out: list[Notification],
        cfg: dict[str, Any],
        severity: str,
        kind: str,
        nvr: Nvr,
        message: str,
        camera: Camera | None = None,
        recovery: bool = False,
        send: bool = True,
    ) -> None:
        db.add(Event(severity=severity, kind=kind, nvr_id=nvr.id, camera_id=camera.id if camera else None, message=message))
        log.info("Událost [%s] %s", severity, message)
        if not send or (recovery and not cfg.get("notify_recoveries", True)):
            return
        if not notify.enabled_channels(cfg):
            return
        ts = utcnow().astimezone().strftime("%d.%m.%Y %H:%M:%S")
        body = f"{message}\n\nZařízení: {nvr.name} ({nvr.host})\nČas: {ts}\nZávažnost: {severity}"
        payload = {"severity": severity, "kind": kind, "nvr": nvr.name, "nvr_id": nvr.id, "message": message}
        if camera is not None:
            payload.update({"camera": camera.name, "channel": camera.channel})
        out.append((f"[Elenvar] {message}", body, payload))

    def _dispatch(self, notifications: list[Notification]) -> None:
        for subject, body, payload in notifications:
            task = asyncio.create_task(notify.send(subject, body, payload))
            self._notify_tasks.add(task)
            task.add_done_callback(self._notify_tasks.discard)


monitor = Monitor()
