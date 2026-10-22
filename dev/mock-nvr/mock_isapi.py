"""Simulátor Hikvision NVR (ISAPI) pro vývoj a testování Elenvar.

Pouze pro vývoj – implementuje podmnožinu ISAPI s Digest autentizací.
Stav kanálů lze měnit: GET /mock/set?offline=2,3&hdd=error
Přijaté webhooky: POST /mock/webhook, výpis GET /mock/webhooks
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import threading
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

USERNAME = os.environ.get("MOCK_USER", "admin")
PASSWORD = os.environ.get("MOCK_PASSWORD", "p@ss:w/rd")
REALM = "IP Camera(mock)"
NS = 'xmlns="http://www.hikvision.com/ver20/XMLSchema"'
HERE = Path(__file__).parent
SNAPSHOT = (HERE / "snapshot.jpg").read_bytes()
SAMPLE = (HERE / "sample.mp4").read_bytes()

CHANNELS = {
    i: name.strip()
    for i, name in enumerate(os.environ.get("MOCK_CHANNELS", "Vjezd,Parkoviště,Sklad,Recepce").split(","), start=1)
    if name.strip()
}
MODEL = os.environ.get("MOCK_MODEL", "DS-7608NXI-K2")
DEVICE_NAME = os.environ.get("MOCK_DEVICE_NAME", "Mock NVR")
state = {
    "offline": {int(x) for x in os.environ.get("MOCK_OFFLINE", "3").split(",") if x.strip()},
    "hdd": "ok",
}
streams: dict[int, dict[str, str]] = {}
for ch in CHANNELS:
    streams[ch * 100 + 1] = {"videoCodecType": "H.265", "videoResolutionWidth": "2560", "videoResolutionHeight": "1440",
                             "videoQualityControlType": "VBR", "vbrUpperCap": "4096", "constantBitRate": "4096",
                             "maxFrameRate": "2500", "GovLength": "50"}
    streams[ch * 100 + 2] = {"videoCodecType": "H.264", "videoResolutionWidth": "640", "videoResolutionHeight": "360",
                             "videoQualityControlType": "VBR", "vbrUpperCap": "512", "constantBitRate": "512",
                             "maxFrameRate": "1500", "GovLength": "30"}
nonces: set[str] = set()
webhooks: list[str] = []
releases: list[bytes] = [b"[]"]
lock = threading.Lock()


def live_frame(channel: int) -> bytes:
    """Snímek z interního RTSP streamu simulátoru; při chybě statický obrázek."""
    src = urllib.parse.quote(f"Streaming/Channels/{channel}02", safe="")
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:1984/api/frame.jpeg?src={src}", timeout=15) as resp:
            data = resp.read()
            if data[:2] == b"\xff\xd8":
                return data
    except OSError:
        pass
    return SNAPSHOT


def md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def parse_auth(header: str) -> dict[str, str]:
    return {k: v1 or v2 for k, v1, v2 in re.findall(r'(\w+)=(?:"([^"]*)"|([^,\s]*))', header)}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # noqa: D401
        print("mock:", self.command, self.path, "->", args[1] if len(args) > 1 else "")

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _send(self, code: int, body: bytes, ctype: str = "application/xml", extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _xml(self, text: str, code: int = 200) -> None:
        self._send(code, ('<?xml version="1.0" encoding="UTF-8"?>\n' + text).encode())

    def _status(self, code: int = 1, string: str = "OK", sub: str = "ok", http: int = 200) -> None:
        self._xml(
            f'<ResponseStatus version="2.0" {NS}><requestURL>{self.path}</requestURL><statusCode>{code}</statusCode>'
            f"<statusString>{string}</statusString><subStatusCode>{sub}</subStatusCode></ResponseStatus>",
            http,
        )

    def _authorized(self) -> bool:
        header = self.headers.get("Authorization", "")
        if header.startswith("Digest "):
            p = parse_auth(header[7:])
            with lock:
                known = p.get("nonce") in nonces
            if known and p.get("username") == USERNAME:
                ha1 = md5(f"{USERNAME}:{REALM}:{PASSWORD}")
                ha2 = md5(f"{self.command}:{p.get('uri', '')}")
                expected = md5(f"{ha1}:{p['nonce']}:{p.get('nc', '')}:{p.get('cnonce', '')}:{p.get('qop', '')}:{ha2}")
                if secrets.compare_digest(expected, p.get("response", "")):
                    return True
        nonce = secrets.token_hex(16)
        with lock:
            nonces.add(nonce)
        self._body()
        self._send(
            401,
            b"<html>401 Unauthorized</html>",
            "text/html",
            {"WWW-Authenticate": f'Digest qop="auth", realm="{REALM}", nonce="{nonce}", stale="FALSE"'},
        )
        return False

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_PUT(self):
        self._route("PUT")

    def _route(self, method: str) -> None:
        url = urlsplit(self.path)
        path = url.path
        if path == "/mock/set":
            q = parse_qs(url.query)
            if "offline" in q:
                state["offline"] = {int(x) for x in q["offline"][0].split(",") if x.strip()}
            if "hdd" in q:
                state["hdd"] = q["hdd"][0]
            return self._send(200, repr(state).encode(), "text/plain")
        if path == "/mock/webhook" and method == "POST":
            webhooks.append(self._body().decode("utf-8", "replace"))
            return self._send(200, b"{}", "application/json")
        if path == "/mock/github/releases":
            # Napodobení GitHub API se seznamem vydání (pro test aktualizací).
            if method == "POST":
                releases[0] = self._body() or b"[]"
            return self._send(200, releases[0], "application/json")
        if path == "/mock/webhooks":
            return self._send(200, ("[" + ",".join(webhooks) + "]").encode(), "application/json")
        if not self._authorized():
            return
        body = self._body()

        if path == "/ISAPI/System/deviceInfo":
            return self._xml(
                f'<DeviceInfo version="2.0" {NS}><deviceName>{DEVICE_NAME}</deviceName><deviceID>mock-1</deviceID>'
                f"<model>{MODEL}</model><serialNumber>{MODEL}20240101CCRRF{sum(map(ord, DEVICE_NAME)) * 7919 % 10**8:08d}</serialNumber>"
                "<macAddress>44:47:cc:00:00:01</macAddress><firmwareVersion>V4.71.110</firmwareVersion>"
                "<firmwareReleasedDate>build 240101</firmwareReleasedDate><deviceType>NVR</deviceType></DeviceInfo>"
            )
        if path == "/ISAPI/ContentMgmt/InputProxy/channels":
            items = "".join(
                f"<InputProxyChannel><id>{ch}</id><name>{name}</name><sourceInputPortDescriptor>"
                f"<proxyProtocol>HIKVISION</proxyProtocol><addressingFormatType>ipaddress</addressingFormatType>"
                f"<ipAddress>192.168.254.{ch + 1}</ipAddress><managePortNo>8000</managePortNo></sourceInputPortDescriptor>"
                "</InputProxyChannel>"
                for ch, name in CHANNELS.items()
            )
            return self._xml(f'<InputProxyChannelList version="2.0" {NS}>{items}</InputProxyChannelList>')
        if path == "/ISAPI/ContentMgmt/InputProxy/channels/status":
            items = "".join(
                f"<InputProxyChannelStatus><id>{ch}</id><online>{'false' if ch in state['offline'] else 'true'}</online>"
                f"<chanDetectResult>{'netUnreachable' if ch in state['offline'] else 'connect'}</chanDetectResult>"
                "</InputProxyChannelStatus>"
                for ch in CHANNELS
            )
            return self._xml(f'<InputProxyChannelStatusList version="2.0" {NS}>{items}</InputProxyChannelStatusList>')
        if path == "/ISAPI/ContentMgmt/Storage":
            return self._xml(
                f'<storage version="2.0" {NS}><hddList><hdd><id>1</id><hddName>hdd1</hddName><hddPath></hddPath>'
                f"<hddType>SATA</hddType><status>{state['hdd']}</status><capacity>3815447</capacity>"
                "<freeSpace>0</freeSpace><property>RW</property></hdd></hddList></storage>"
            )
        if path == "/ISAPI/System/time":
            now = datetime.now(timezone(timedelta(hours=2)))
            return self._xml(
                f'<Time version="2.0" {NS}><timeMode>NTP</timeMode><localTime>{now.isoformat(timespec="seconds")}</localTime>'
                "<timeZone>CST-1:00:00DST01:00:00,M3.5.0/02:00:00,M10.5.0/03:00:00</timeZone></Time>"
            )
        m = re.fullmatch(r"/ISAPI/Streaming/channels/(\d+)/picture", path)
        if m:
            ch = int(m.group(1)) // 100
            if ch in state["offline"] or ch not in CHANNELS:
                return self._status(4, "Invalid Operation", "deviceError", 403)
            return self._send(200, live_frame(ch), "image/jpeg")
        m = re.fullmatch(r"/ISAPI/Streaming/channels/(\d+)/capabilities", path)
        if m and int(m.group(1)) in streams:
            return self._xml(
                f'<StreamingChannel version="2.0" {NS}><id>{m.group(1)}</id><Video>'
                '<videoCodecType opt="H.264,H.265">H.264</videoCodecType>'
                '<videoResolutionWidth opt="2560,1920,1280,640">1920</videoResolutionWidth>'
                '<videoResolutionHeight opt="1440,1080,720,360">1080</videoResolutionHeight>'
                '<videoQualityControlType opt="CBR,VBR">VBR</videoQualityControlType>'
                '<constantBitRate min="32" max="16384">2048</constantBitRate>'
                '<vbrUpperCap min="32" max="16384">2048</vbrUpperCap>'
                '<maxFrameRate opt="2500,2000,1500,1000,500,100">2500</maxFrameRate>'
                '<GovLength min="1" max="400">50</GovLength></Video></StreamingChannel>'
            )
        m = re.fullmatch(r"/ISAPI/Streaming/channels/(\d+)", path)
        if m and int(m.group(1)) in streams:
            sid = int(m.group(1))
            if method == "PUT":
                text = body.decode()
                for field in streams[sid]:
                    fm = re.search(rf"<{field}>([^<]*)</{field}>", text)
                    if fm:
                        streams[sid][field] = fm.group(1)
                return self._status()
            fields = "".join(f"<{k}>{v}</{k}>" for k, v in streams[sid].items())
            return self._xml(
                f'<StreamingChannel version="2.0" {NS}><id>{sid}</id><channelName>{CHANNELS[sid // 100]}</channelName>'
                f"<enabled>true</enabled><Video><enabled>true</enabled><videoInputChannelID>{sid // 100}</videoInputChannelID>"
                f"{fields}<SmartCodec><enabled>false</enabled></SmartCodec></Video>"
                "<Audio><enabled>false</enabled><audioCompressionType>G.711ulaw</audioCompressionType></Audio></StreamingChannel>"
            )
        if path == "/ISAPI/ContentMgmt/search" and method == "POST":
            return self._search(body.decode())
        if path == "/ISAPI/ContentMgmt/download":
            if b"playbackURI" not in body:
                return self._status(6, "Invalid XML Content", "badXmlContent", 400)
            return self._send(200, SAMPLE, "video/mp4")
        if path == "/ISAPI/System/reboot" and method == "PUT":
            return self._status(1, "OK", "ok")
        return self._status(4, "Invalid Operation", "notSupport", 403)

    def _search(self, text: str) -> None:
        track = int(re.search(r"<trackID>(\d+)</trackID>", text).group(1))
        start = datetime.strptime(re.search(r"<startTime>([^<]+)</startTime>", text).group(1)[:19], "%Y-%m-%dT%H:%M:%S")
        end = datetime.strptime(re.search(r"<endTime>([^<]+)</endTime>", text).group(1)[:19], "%Y-%m-%dT%H:%M:%S")
        max_results = int(re.search(r"<maxResults>(\d+)</maxResults>", text).group(1))
        position = int(re.search(r"<searchResultPostion>(\d+)</searchResultPostion>", text).group(1))
        search_id = re.search(r"<searchID>([^<]+)</searchID>", text).group(1)
        day = start.replace(hour=0, minute=0, second=0)
        segments = []
        cursor = day
        while cursor < day + timedelta(days=1):
            seg_end = cursor + timedelta(minutes=9, seconds=59)
            # Kanál 4 nahrává jen při pohybu (mezery v záznamu).
            if (track // 100 != 4 or cursor.hour % 3 == 0) and seg_end >= start and cursor <= end:
                segments.append((cursor, seg_end, "motion" if cursor.hour % 3 == 0 else "timing"))
            cursor += timedelta(minutes=10)
        page = segments[position : position + max_results]
        more = position + max_results < len(segments)
        if not page:
            return self._xml(
                f'<CMSearchResult version="2.0" {NS}><searchID>{search_id}</searchID><responseStatus>true</responseStatus>'
                "<responseStatusStrg>NO MATCHES</responseStatusStrg><numOfMatches>0</numOfMatches><matchList/></CMSearchResult>"
            )
        items = "".join(
            "<searchMatchItem><sourceID>{2C3F8D2D-mock}</sourceID>"
            f"<trackID>{track}</trackID><timeSpan><startTime>{s:%Y-%m-%dT%H:%M:%S}Z</startTime>"
            f"<endTime>{e:%Y-%m-%dT%H:%M:%S}Z</endTime></timeSpan><mediaSegmentDescriptor><contentType>video</contentType>"
            f"<codecType>H.265</codecType><playbackURI>rtsp://192.168.1.10/Streaming/tracks/{track}/?starttime="
            f"{s:%Y%m%dT%H%M%S}Z&amp;endtime={e:%Y%m%dT%H%M%S}Z&amp;name=ch01_{s:%H%M}&amp;size=100000</playbackURI>"
            "</mediaSegmentDescriptor><metadataMatches><metadataDescriptor>recordType.meta.hikvision.com/"
            f"{kind}</metadataDescriptor></metadataMatches></searchMatchItem>"
            for s, e, kind in page
        )
        self._xml(
            f'<CMSearchResult version="2.0" {NS}><searchID>{search_id}</searchID><responseStatus>true</responseStatus>'
            f"<responseStatusStrg>{'MORE' if more else 'OK'}</responseStatusStrg><numOfMatches>{len(page)}</numOfMatches>"
            f"<matchList>{items}</matchList></CMSearchResult>"
        )


if __name__ == "__main__":
    port = int(os.environ.get("MOCK_PORT", "80"))
    print(f"Mock Hikvision NVR na portu {port} (uživatel {USERNAME})")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
