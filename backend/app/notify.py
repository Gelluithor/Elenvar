"""Odesílání upozornění (e-mail, webhook)."""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Any

import httpx

from . import app_settings
from .db import SessionLocal
from .security import decrypt

log = logging.getLogger("elenvar.notify")


def _send_email_sync(cfg: dict[str, Any], password: str, subject: str, body: str) -> None:
    recipients = [r.strip() for r in str(cfg["smtp_to"]).replace(";", ",").split(",") if r.strip()]
    if not recipients:
        raise ValueError("Není zadán příjemce e-mailu.")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["smtp_from"] or cfg["smtp_username"]
    msg["To"] = ", ".join(recipients)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="elenvar.local")
    msg.set_content(body)

    host, port, security = cfg["smtp_host"], int(cfg["smtp_port"]), cfg["smtp_security"]
    context = ssl.create_default_context()
    if security == "ssl":
        server: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=20, context=context)
    else:
        server = smtplib.SMTP(host, port, timeout=20)
    try:
        server.ehlo()
        if security == "starttls":
            server.starttls(context=context)
            server.ehlo()
        if cfg["smtp_username"]:
            server.login(cfg["smtp_username"], password)
        server.send_message(msg)
    finally:
        try:
            server.quit()
        except smtplib.SMTPException:
            server.close()


async def _send_webhook(url: str, subject: str, body: str, payload: dict[str, Any]) -> None:
    text = f"{subject}\n{body}"
    data = {"text": text, "content": text[:1900], "title": subject, "message": body, "event": payload}
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0), follow_redirects=False) as client:
        resp = await client.post(url, json=data)
        if resp.status_code >= 400:
            raise RuntimeError(f"Webhook vrátil HTTP {resp.status_code}")


async def send(subject: str, body: str, payload: dict[str, Any] | None = None) -> list[str]:
    """Odešle upozornění všemi zapnutými kanály. Vrací seznam chyb."""
    async with SessionLocal() as db:
        cfg = await app_settings.get_all(db)
    errors: list[str] = []
    if cfg["smtp_enabled"] and cfg["smtp_host"]:
        try:
            password = decrypt(cfg["smtp_password_enc"]) if cfg["smtp_password_enc"] else ""
            await asyncio.to_thread(_send_email_sync, cfg, password, subject, body)
        except Exception as exc:  # noqa: BLE001 – chyby doručení se jen hlásí
            log.warning("Odeslání e-mailu selhalo: %s", exc)
            errors.append(f"E-mail: {exc}")
    if cfg["webhook_enabled"] and cfg["webhook_url"]:
        try:
            await _send_webhook(cfg["webhook_url"], subject, body, payload or {})
        except Exception as exc:  # noqa: BLE001
            log.warning("Odeslání webhooku selhalo: %s", exc)
            errors.append(f"Webhook: {exc}")
    return errors


def enabled_channels(cfg: dict[str, Any]) -> list[str]:
    channels = []
    if cfg["smtp_enabled"] and cfg["smtp_host"]:
        channels.append("email")
    if cfg["webhook_enabled"] and cfg["webhook_url"]:
        channels.append("webhook")
    return channels
