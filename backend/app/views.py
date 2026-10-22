"""Serializace modelů pro API."""

from __future__ import annotations

from typing import Any

from .i18n import tr
from .models import Camera, Nvr
from .nvr_service import disk_problems, is_recorder, load_disks


def camera_state(cam: Camera, nvr: Nvr) -> str:
    """Efektivní stav kamery: online | offline | unknown | nvr_down."""
    if not nvr.enabled or nvr.status != "online":
        return "nvr_down"
    if cam.online is True:
        return "online"
    if cam.online is False:
        return "offline"
    return "unknown"


def camera_view(cam: Camera, nvr: Nvr) -> dict[str, Any]:
    return {
        "id": cam.id,
        "nvr_id": nvr.id,
        "nvr_name": nvr.name,
        "channel": cam.channel,
        "name": cam.name,
        "ip_address": cam.ip_address,
        "online": cam.online,
        "state": camera_state(cam, nvr),
        "detail": tr(cam.detail),
        "monitored": cam.monitored,
        "status_changed_at": cam.status_changed_at,
        "last_online_at": cam.last_online_at,
    }


def nvr_view(nvr: Nvr, cameras: list[Camera], admin: bool) -> dict[str, Any]:
    disks = load_disks(nvr)
    online = sum(1 for c in cameras if camera_state(c, nvr) == "online")
    monitored_offline = sum(1 for c in cameras if c.monitored and camera_state(c, nvr) == "offline")
    data: dict[str, Any] = {
        "id": nvr.id,
        "name": nvr.name,
        "enabled": nvr.enabled,
        "status": nvr.status if nvr.enabled else "disabled",
        "status_message": tr(nvr.status_message),
        "status_changed_at": nvr.status_changed_at,
        "last_seen_at": nvr.last_seen_at,
        "last_poll_at": nvr.last_poll_at,
        "model": nvr.model,
        "device_type": nvr.device_type,
        "device_name": nvr.device_name,
        "firmware": nvr.firmware,
        "serial_number": nvr.serial_number,
        "device_time": nvr.device_time,
        "time_drift_sec": nvr.time_drift_sec,
        "camera_count": len(cameras),
        "camera_online": online,
        "camera_monitored_offline": monitored_offline,
        "disks": disks,
        "disk_problems": [tr(p) for p in disk_problems(disks, is_recorder(nvr.device_type)).values()]
        if nvr.last_seen_at
        else [],
        "transcode": nvr.transcode,
    }
    if admin:
        data.update(
            {
                "host": nvr.host,
                "http_port": nvr.http_port,
                "rtsp_port": nvr.rtsp_port,
                "use_https": nvr.use_https,
                "verify_tls": nvr.verify_tls,
                "username": nvr.username,
                "notes": nvr.notes,
                "mac_address": nvr.mac_address,
            }
        )
    return data
