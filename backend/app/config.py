"""Konfigurace aplikace z proměnných prostředí."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet

log = logging.getLogger("elenvar.config")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "ano"}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"Variable {name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"Variable {name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    static_dir: Path
    cookie_secure: bool
    session_idle_minutes: int
    session_max_hours: int
    go2rtc_url: str
    admin_username: str
    admin_password: str | None
    log_level: str
    playback_source: str


def load_settings() -> Settings:
    data_dir = Path(os.environ.get("ELENVAR_DATA_DIR", "/data"))
    playback_source = os.environ.get("ELENVAR_PLAYBACK_SOURCE", "rtsp").strip().lower()
    if playback_source not in {"rtsp", "ffmpeg"}:
        raise RuntimeError("ELENVAR_PLAYBACK_SOURCE must be 'rtsp' or 'ffmpeg'")
    admin_password = os.environ.get("ELENVAR_ADMIN_PASSWORD") or None
    return Settings(
        data_dir=data_dir,
        static_dir=Path(os.environ.get("ELENVAR_STATIC_DIR", "/app/static")),
        cookie_secure=_env_bool("ELENVAR_COOKIE_SECURE", True),
        session_idle_minutes=_env_int("ELENVAR_SESSION_IDLE_MINUTES", 60, 5, 24 * 60),
        session_max_hours=_env_int("ELENVAR_SESSION_MAX_HOURS", 12, 1, 24 * 30),
        go2rtc_url=os.environ.get("ELENVAR_GO2RTC_URL", "http://go2rtc:1984").rstrip("/"),
        admin_username=os.environ.get("ELENVAR_ADMIN_USERNAME", "admin").strip().lower() or "admin",
        admin_password=admin_password,
        log_level=os.environ.get("ELENVAR_LOG_LEVEL", "INFO").upper(),
        playback_source=playback_source,
    )


settings = load_settings()


def load_secret_key() -> bytes:
    """Vrátí klíč pro šifrování citlivých údajů (hesla k NVR, SMTP).

    Přednost má proměnná ELENVAR_SECRET_KEY, jinak se klíč při prvním startu
    vygeneruje do datového adresáře s právy 0600.
    """
    env_key = os.environ.get("ELENVAR_SECRET_KEY", "").strip()
    if env_key:
        key = env_key.encode()
        try:
            Fernet(key)
        except (ValueError, TypeError) as exc:
            raise RuntimeError(
                "ELENVAR_SECRET_KEY is not a valid key (32 bytes, URL-safe base64). "
                "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            ) from exc
        return key

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    key_file = settings.data_dir / "secret.key"
    if key_file.exists():
        key = key_file.read_bytes().strip()
        Fernet(key)
        return key

    key = Fernet.generate_key()
    fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(key)
    log.warning("Generated a new encryption key %s – back it up together with the database.", key_file)
    return key
