"""Pomocné funkce pro práci s NVR záznamy z databáze."""

from __future__ import annotations

import json
from typing import Any

from .hikvision import CAMERA_DEVICE_TYPES, HEALTHY_HDD_STATES, Connection, HikvisionClient
from .models import Nvr
from .security import decrypt


def connection_for(nvr: Nvr) -> Connection:
    return Connection(
        host=nvr.host,
        http_port=nvr.http_port,
        rtsp_port=nvr.rtsp_port,
        use_https=nvr.use_https,
        verify_tls=nvr.verify_tls,
        username=nvr.username,
        password=decrypt(nvr.password_enc),
    )


def client_for(nvr: Nvr) -> HikvisionClient:
    return HikvisionClient(connection_for(nvr))


def is_recorder(device_type: str) -> bool:
    """NVR/DVR (nahrávací zařízení), ne samostatná kamera."""
    return bool(device_type) and device_type.lower() not in CAMERA_DEVICE_TYPES


def load_disks(nvr: Nvr) -> list[dict[str, Any]]:
    try:
        data = json.loads(nvr.hdd_json or "[]")
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def disk_problems(disks: list[dict[str, Any]], recorder: bool) -> dict[str, str]:
    """Klíč disku -> popis problému."""
    problems: dict[str, str] = {}
    for disk in disks:
        status = str(disk.get("status", "")).strip()
        if status.lower() not in HEALTHY_HDD_STATES:
            key = f"{disk.get('kind', 'HDD')}:{disk.get('id', '')}"
            problems[key] = f"{disk.get('name', 'Disk')} – stav „{status or 'neznámý'}“"
    if recorder and not disks:
        problems["none"] = "Zařízení nemá žádný disk – nenahrává se"
    return problems
