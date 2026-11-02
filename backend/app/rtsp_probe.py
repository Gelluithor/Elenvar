"""Zkouška RTSP přihlášení a kodeku (DESCRIBE) bez přehrávání videa.

go2rtc při přihlášení čte jen první hlavičku WWW-Authenticate a digest počítá
bez qop. Starší firmware Hikvision nabízí přihlášení jinak a go2rtc pak dostane
401, přestože jméno a heslo jsou správné. Zkouška proto přihlášení ověří dvakrát:
stejně jako go2rtc („přímé spojení“) a plnohodnotně jako FFmpeg („kompatibilní
režim“). Výsledek rozhoduje o tom, kudy se video čte.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import re
import secrets
from dataclasses import dataclass, field

from .hikvision import Connection

TIMEOUT = 6.0
MAX_HEADER_BYTES = 16 * 1024
MAX_BODY_BYTES = 64 * 1024
USER_AGENT = "Elenvar"


class RtspUnreachable(Exception):
    pass


@dataclass
class RtspResponse:
    status: int
    headers: list[tuple[str, str]]
    body: str

    def all(self, name: str) -> list[str]:
        name = name.lower()
        return [v for k, v in self.headers if k.lower() == name]


@dataclass
class ProbeResult:
    reachable: bool
    # HTTP-like status kódy výsledné odpovědi: přímé (go2rtc) a kompatibilní (FFmpeg) přihlášení
    direct_status: int | None = None
    compat_status: int | None = None
    auth_offered: list[str] = field(default_factory=list)
    video_codec: str = ""
    audio_codec: str = ""

    @property
    def direct_ok(self) -> bool:
        return self.direct_status == 200

    @property
    def compat_ok(self) -> bool:
        return self.compat_status == 200


def _md5(*parts: str) -> str:
    return hashlib.md5(":".join(parts).encode()).hexdigest()  # noqa: S324 (RTSP digest vyžaduje MD5)


def _params(header: str) -> dict[str, str]:
    return {k.lower(): v1 or v2 for k, v1, v2 in re.findall(r'(\w+)=(?:"([^"]*)"|([^\s,]+))', header)}


def go2rtc_authorization(challenge: str, method: str, uri: str, user: str, password: str) -> str | None:
    """Hlavička Authorization tak, jak ji vytvoří go2rtc 1.9 (pkg/tcp/auth.go)."""
    if challenge[:6] == "Basic ":
        return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
    if challenge[:6] == "Digest":
        realm = challenge.split('realm="', 1)[1].split('"', 1)[0] if 'realm="' in challenge else ""
        nonce = challenge.split('nonce="', 1)[1].split('"', 1)[0] if 'nonce="' in challenge else ""
        response = _md5(_md5(user, realm, password), nonce, _md5(method, uri))
        return f'Digest username="{user}", realm="{realm}", nonce="{nonce}", uri="{uri}", response="{response}"'
    return None


def full_authorization(challenges: list[str], method: str, uri: str, user: str, password: str) -> str | None:
    """Plnohodnotné přihlášení (jako FFmpeg): přednost má Digest, umí qop i MD5-sess."""
    digest = next((c for c in challenges if c[:6].lower() == "digest"), None)
    if digest is not None:
        p = _params(digest[6:])
        realm, nonce = p.get("realm", ""), p.get("nonce", "")
        algorithm = p.get("algorithm", "")
        cnonce = secrets.token_hex(8)
        ha1 = _md5(user, realm, password)
        if algorithm.lower() == "md5-sess":
            ha1 = _md5(ha1, nonce, cnonce)
        ha2 = _md5(method, uri)
        qops = [q.strip() for q in p.get("qop", "").split(",") if q.strip()]
        header = f'Digest username="{user}", realm="{realm}", nonce="{nonce}", uri="{uri}"'
        if "auth" in qops:
            nc = "00000001"
            header += f', response="{_md5(ha1, nonce, nc, cnonce, "auth", ha2)}", qop=auth, nc={nc}, cnonce="{cnonce}"'
        else:
            header += f', response="{_md5(ha1, nonce, ha2)}"'
        if "opaque" in p:
            header += f', opaque="{p["opaque"]}"'
        if algorithm:
            header += f", algorithm={algorithm}"
        return header
    if any(c[:5].lower() == "basic" for c in challenges):
        return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
    return None


class _RtspConnection:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer
        self.cseq = 0

    async def describe(self, url: str, authorization: str | None) -> RtspResponse:
        self.cseq += 1
        lines = [f"DESCRIBE {url} RTSP/1.0", f"CSeq: {self.cseq}", f"User-Agent: {USER_AGENT}", "Accept: application/sdp"]
        if authorization:
            lines.append(f"Authorization: {authorization}")
        self.writer.write(("\r\n".join(lines) + "\r\n\r\n").encode())
        await self.writer.drain()
        head = await self.reader.readuntil(b"\r\n\r\n")
        if len(head) > MAX_HEADER_BYTES:
            raise ValueError("RTSP header too large")
        text = head.decode("latin-1").split("\r\n")
        match = re.match(r"RTSP/1\.\d (\d{3})", text[0])
        if not match:
            raise ValueError("Not an RTSP response")
        headers = [(k.strip(), v.strip()) for k, _, v in (line.partition(":") for line in text[1:] if line)]
        length = next((int(v) for k, v in headers if k.lower() == "content-length" and v.isdigit()), 0)
        body = await self.reader.readexactly(min(length, MAX_BODY_BYTES)) if length else b""
        return RtspResponse(int(match.group(1)), headers, body.decode("utf-8", "replace"))


@contextlib.asynccontextmanager
async def _connect(conn: Connection):
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(conn.host, conn.rtsp_port, limit=MAX_HEADER_BYTES + 1024), TIMEOUT
        )
    except (OSError, asyncio.TimeoutError) as exc:
        raise RtspUnreachable(str(exc)) from exc
    try:
        yield _RtspConnection(reader, writer)
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


def _sdp_codecs(sdp: str) -> tuple[str, str]:
    video = audio = ""
    section = ""
    for line in sdp.splitlines():
        if line.startswith("m="):
            section = line[2:].split(" ", 1)[0]
        elif line.startswith("a=rtpmap:"):
            codec = line.split(" ", 1)[1].split("/", 1)[0].upper() if " " in line else ""
            if section == "video" and not video:
                video = codec
            elif section == "audio" and not audio:
                audio = codec
    return video, audio


async def _attempt(conn: Connection, url: str, build) -> RtspResponse:
    """Jeden pokus na vlastním spojení: výzva 401 a odpověď s přihlášením."""
    async with _connect(conn) as rtsp:
        first = await asyncio.wait_for(rtsp.describe(url, None), TIMEOUT)
        if first.status != 401:
            return first
        authorization = build(first.all("WWW-Authenticate"), url)
        if authorization is None:
            return first
        return await asyncio.wait_for(rtsp.describe(url, authorization), TIMEOUT)


async def probe(conn: Connection, path: str) -> ProbeResult:
    url = f"rtsp://{conn.host_for_url}:{conn.rtsp_port}{path}"
    user, password = conn.username, conn.password
    result = ProbeResult(reachable=True)

    def direct(challenges: list[str], uri: str) -> str | None:
        result.auth_offered = [c.split(" ", 1)[0].capitalize() + (" (qop)" if "qop" in c.lower() else "") for c in challenges]
        return go2rtc_authorization(challenges[0], "DESCRIBE", uri, user, password) if challenges else None

    try:
        resp = await _attempt(conn, url, direct)
        result.direct_status = resp.status
        if resp.status == 200:
            result.compat_status = 200
        else:
            resp = await _attempt(conn, url, lambda ch, uri: full_authorization(ch, "DESCRIBE", uri, user, password))
            result.compat_status = resp.status
    except RtspUnreachable:
        return ProbeResult(reachable=False)
    except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, ValueError):
        # Spojení se otevřelo, ale odpověď nedává smysl (jiná služba na portu, přerušení).
        result.direct_status = result.direct_status or 0
        result.compat_status = result.compat_status or 0
        return result
    if resp.status == 200:
        result.video_codec, result.audio_codec = _sdp_codecs(resp.body)
    return result
