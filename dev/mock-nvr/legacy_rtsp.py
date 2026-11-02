"""RTSP proxy, která se přihlašuje jako starší firmware Hikvision. Pouze pro vývoj a testy.

Nabízí nejdřív Basic a teprve potom Digest s qop="auth", přijme ale jen Digest s qop.
Klient, který použije první nabídnutý způsob nebo digest bez qop, dostane 401.
Po úspěšném přihlášení se spojení přepojí na interní RTSP server simulátoru.
"""

import asyncio
import hashlib
import os
import re
import secrets

LISTEN_PORT = 554
UPSTREAM = ("127.0.0.1", 8554)
USER = os.environ.get("MOCK_USER", "admin")
PASSWORD = os.environ.get("MOCK_PASSWORD", "p@ss:w/rd")
REALM = "Legacy NVR"


def md5(*parts: str) -> str:
    return hashlib.md5(":".join(parts).encode()).hexdigest()


def params(header: str) -> dict[str, str]:
    return {k.lower(): a or b for k, a, b in re.findall(r'(\w+)=(?:"([^"]*)"|([^\s,]+))', header)}


def valid(auth: str, method: str, nonce: str) -> bool:
    if not auth.startswith("Digest "):
        return False
    p = params(auth[7:])
    if p.get("qop") != "auth" or p.get("nonce") != nonce or p.get("username") != USER:
        return False
    ha1, ha2 = md5(USER, REALM, PASSWORD), md5(method, p.get("uri", ""))
    return p.get("response") == md5(ha1, nonce, p.get("nc", ""), p.get("cnonce", ""), "auth", ha2)


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        writer.close()


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    nonce = secrets.token_hex(16)
    try:
        while True:
            head = await reader.readuntil(b"\r\n\r\n")
            lines = head.decode("latin-1").split("\r\n")
            method = lines[0].split(" ", 1)[0]
            headers = {k.strip().lower(): v.strip() for k, _, v in (l.partition(":") for l in lines[1:] if l)}
            length = int(headers.get("content-length", "0") or 0)
            body = await reader.readexactly(length) if length else b""
            if valid(headers.get("authorization", ""), method, nonce):
                up_reader, up_writer = await asyncio.open_connection(*UPSTREAM)
                up_writer.write(head + body)
                await up_writer.drain()
                await asyncio.gather(pipe(reader, up_writer), pipe(up_reader, writer))
                return
            writer.write(
                (
                    f"RTSP/1.0 401 Unauthorized\r\nCSeq: {headers.get('cseq', '0')}\r\n"
                    f'WWW-Authenticate: Basic realm="{REALM}"\r\n'
                    f'WWW-Authenticate: Digest realm="{REALM}", nonce="{nonce}", qop="auth"\r\n\r\n'
                ).encode()
            )
            await writer.drain()
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError, ValueError):
        writer.close()


async def main() -> None:
    server = await asyncio.start_server(handle, "0.0.0.0", LISTEN_PORT)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
