"""Kryptografické primitivum: hesla, tokeny, šifrování, TOTP, recovery kódy."""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import secrets
import time

import pyotp
import qrcode
import qrcode.image.svg
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from .config import load_secret_key

_hasher = PasswordHasher()  # Argon2id s doporučenými parametry
_fernet = Fernet(load_secret_key())

# Hash pro neexistující uživatele – vyrovnává dobu odezvy přihlášení.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 256
TOTP_ISSUER = "Elenvar"
TOTP_INTERVAL = 30
RECOVERY_CODE_COUNT = 10
_RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


# --- hesla -----------------------------------------------------------------

def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Ověří heslo. Při neexistujícím hashi stejně proběhne výpočet."""
    target = password_hash or _DUMMY_HASH
    try:
        ok = _hasher.verify(target, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return ok and password_hash is not None


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return False


def password_problem(password: str, username: str = "") -> str | None:
    """Vrátí popis problému s heslem, nebo None pokud vyhovuje."""
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"Heslo musí mít alespoň {PASSWORD_MIN_LENGTH} znaků."
    if len(password) > PASSWORD_MAX_LENGTH:
        return f"Heslo může mít nejvýše {PASSWORD_MAX_LENGTH} znaků."
    if username and username.lower() in password.lower():
        return "Heslo nesmí obsahovat uživatelské jméno."
    if len(set(password)) < 5:
        return "Heslo je příliš jednoduché."
    return None


# --- tokeny ----------------------------------------------------------------

def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


# --- šifrování -------------------------------------------------------------

def encrypt(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    try:
        return _fernet.decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError(
            "Nelze dešifrovat uložený údaj – změnil se šifrovací klíč (secret.key)?"
        ) from exc


# --- TOTP ------------------------------------------------------------------

def new_totp_secret() -> str:
    return pyotp.random_base32(length=32)


def totp_uri(secret: str, username: str) -> str:
    return pyotp.TOTP(secret, interval=TOTP_INTERVAL).provisioning_uri(
        name=username, issuer_name=TOTP_ISSUER
    )


def qr_data_uri(data: str) -> str:
    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()


def verify_totp(secret: str, code: str, last_step: int) -> int | None:
    """Ověří TOTP kód (okno ±1 krok). Vrací použitý časový krok, nebo None.

    Kód z kroku, který už byl jednou použit (nebo starší), se odmítne –
    ochrana proti opakovanému použití odposlechnutého kódu.
    """
    code = code.strip().replace(" ", "")
    if len(code) != 6 or not code.isdigit():
        return None
    totp = pyotp.TOTP(secret, interval=TOTP_INTERVAL)
    now_step = int(time.time()) // TOTP_INTERVAL
    for offset in (0, -1, 1):
        step = now_step + offset
        expected = totp.at(step * TOTP_INTERVAL)
        if hmac.compare_digest(expected, code):
            if step <= last_step:
                return None
            return step
    return None


# --- recovery kódy ---------------------------------------------------------

def normalize_recovery_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def hash_recovery_code(code: str) -> str:
    return hashlib.sha256(normalize_recovery_code(code).encode()).hexdigest()


def new_recovery_codes() -> list[str]:
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


def looks_like_recovery_code(code: str) -> bool:
    return len(normalize_recovery_code(code)) == 10
