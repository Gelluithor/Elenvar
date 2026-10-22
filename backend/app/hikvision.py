"""Klient pro Hikvision ISAPI (NVR, DVR i samostatné IP kamery)."""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote
from xml.etree.ElementTree import Element
from xml.sax.saxutils import escape as xml_escape

import httpx
from defusedxml import ElementTree as DET
from defusedxml.common import DefusedXmlException

log = logging.getLogger("elenvar.isapi")

DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
DOWNLOAD_TIMEOUT = httpx.Timeout(60.0, connect=5.0)
SEARCH_PAGE_SIZE = 100
SEARCH_MAX_RESULTS = 2000
MAX_XML_SIZE = 4 * 1024 * 1024
MAX_SNAPSHOT_SIZE = 15 * 1024 * 1024

# Stavy disků, které nejsou problém.
HEALTHY_HDD_STATES = {"ok", "idle", "standby", "sleeping", "sleep"}

CAMERA_DEVICE_TYPES = {"ipcamera", "ipdome", "ipc", "ipzoom", "thermal", "ipcamera_thermal"}

DETECT_RESULT_CS = {
    "connect": "Připojeno",
    "connecting": "Připojování",
    "netunreachable": "Síť nedostupná",
    "overflow": "Překročena kapacita",
    "oversysbandwidth": "Překročena šířka pásma",
    "ipcstreamfail": "Selhal stream z kamery",
    "ipcstreamfailed": "Selhal stream z kamery",
    "ipcuserlocked": "Účet na kameře zablokován",
    "invalidusername": "Neplatné jméno pro kameru",
    "invalidpassword": "Neplatné heslo pro kameru",
    "usernameorpassworderror": "Chybné přihlašovací údaje kamery",
    "notexist": "Kamera neexistuje",
    "unknownerror": "Neznámá chyba",
    "notsupport": "Nepodporováno",
    "offline": "Offline",
}

STREAM_INT_FIELDS = (
    "videoResolutionWidth",
    "videoResolutionHeight",
    "constantBitRate",
    "vbrUpperCap",
    "maxFrameRate",
    "GovLength",
)
STREAM_STR_FIELDS = ("videoCodecType", "videoQualityControlType")
STREAM_FIELDS = STREAM_STR_FIELDS + STREAM_INT_FIELDS


class IsapiError(Exception):
    """Obecná chyba komunikace se zařízením (zpráva je pro uživatele)."""


class IsapiAuthError(IsapiError):
    pass


class IsapiUnreachable(IsapiError):
    pass


class IsapiNotSupported(IsapiError):
    pass


@dataclass(frozen=True)
class Connection:
    host: str
    http_port: int
    rtsp_port: int
    use_https: bool
    verify_tls: bool
    username: str
    password: str

    @property
    def host_for_url(self) -> str:
        if ":" in self.host and not self.host.startswith("["):
            return f"[{self.host}]"
        return self.host

    @property
    def base_url(self) -> str:
        scheme = "https" if self.use_https else "http"
        return f"{scheme}://{self.host_for_url}:{self.http_port}"

    def rtsp_url(self, path_and_query: str) -> str:
        user = quote(self.username, safe="")
        password = quote(self.password, safe="")
        return f"rtsp://{user}:{password}@{self.host_for_url}:{self.rtsp_port}{path_and_query}"


@dataclass
class ChannelInfo:
    channel: int
    name: str
    ip_address: str
    online: bool | None
    detail: str


@dataclass
class RecordingSegment:
    start: datetime  # naivní čas zařízení
    end: datetime
    record_type: str
    playback_uri: str


# --- HTTP klient -------------------------------------------------------------

_clients: dict[bool, httpx.AsyncClient] = {}
# Zařízení, která nabízejí pouze Basic autentizaci (klíč host:port).
_basic_only_hosts: set[str] = set()


def _client(verify: bool) -> httpx.AsyncClient:
    client = _clients.get(verify)
    if client is None:
        client = httpx.AsyncClient(
            verify=verify,
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=False,
            limits=httpx.Limits(max_connections=200, max_keepalive_connections=40),
            headers={"User-Agent": "Elenvar/1.0"},
        )
        _clients[verify] = client
    return client


async def close_clients() -> None:
    for client in list(_clients.values()):
        await client.aclose()
    _clients.clear()


# --- XML pomocníci -----------------------------------------------------------

def parse_xml(content: bytes) -> Element:
    if len(content) > MAX_XML_SIZE:
        raise IsapiError("Odpověď zařízení je příliš velká.")
    try:
        root = DET.fromstring(content)
    except (DET.ParseError, DefusedXmlException, ValueError) as exc:
        raise IsapiError("Zařízení vrátilo neplatnou XML odpověď.") from exc
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def _text(el: Element | None, path: str, default: str = "") -> str:
    if el is None:
        return default
    found = el.find(path)
    if found is None or found.text is None:
        return default
    return found.text.strip()


def _int(value: str, default: int = 0) -> int:
    try:
        return int(value.strip())
    except (ValueError, AttributeError):
        return default


def _status_detail(content: bytes) -> tuple[str, str]:
    """Vrátí (statusString, subStatusCode) z ResponseStatus, pokud jde o XML."""
    try:
        root = parse_xml(content)
    except IsapiError:
        return "", ""
    return _text(root, "statusString"), _text(root, "subStatusCode")


def parse_device_time(value: str) -> datetime | None:
    """Datum a čas z /ISAPI/System/time; None, pokud chybí časová zóna."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def parse_device_datetime(value: str) -> datetime | None:
    """Čas záznamu jako naivní lokální čas zařízení.

    Hikvision u vyhledávání záznamů vrací lokální čas zařízení, i když ho
    označuje příponou 'Z'. Používá se proto pouze datum a čas bez zóny.
    """
    try:
        return datetime.strptime(value.strip()[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None


def format_search_time(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def format_rtsp_time(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%SZ")


def main_stream_id(channel: int) -> int:
    return channel * 100 + 1


def sub_stream_id(channel: int) -> int:
    return channel * 100 + 2


def live_rtsp_path(channel: int, quality: str) -> str:
    stream = main_stream_id(channel) if quality == "main" else sub_stream_id(channel)
    return f"/Streaming/Channels/{stream}"


def playback_rtsp_path(channel: int, start: datetime, end: datetime) -> str:
    return (
        f"/Streaming/tracks/{main_stream_id(channel)}"
        f"?starttime={format_rtsp_time(start)}&endtime={format_rtsp_time(end)}"
    )


# --- klient ------------------------------------------------------------------

class HikvisionClient:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    @property
    def _host_key(self) -> str:
        return f"{self.conn.host}:{self.conn.http_port}"

    def _auth(self) -> httpx.Auth:
        if self._host_key in _basic_only_hosts:
            return httpx.BasicAuth(self.conn.username, self.conn.password)
        return httpx.DigestAuth(self.conn.username, self.conn.password)

    @staticmethod
    def _offers_only_basic(resp: httpx.Response) -> bool:
        challenges = [c.lower() for c in resp.headers.get_list("www-authenticate")]
        return bool(challenges) and not any(c.startswith("digest") for c in challenges) and any(
            c.startswith("basic") for c in challenges
        )

    async def _send(
        self,
        method: str,
        path: str,
        *,
        content: bytes | None = None,
        timeout: httpx.Timeout | None = None,
        stream: bool = False,
    ) -> httpx.Response:
        client = _client(self.conn.verify_tls)
        url = self.conn.base_url + path
        headers = {"Content-Type": "application/xml; charset=UTF-8"} if content is not None else {}
        for attempt in range(2):
            request = client.build_request(
                method, url, content=content, headers=headers, timeout=timeout or DEFAULT_TIMEOUT
            )
            try:
                resp = await client.send(request, auth=self._auth(), stream=stream)
            except httpx.TimeoutException as exc:
                raise IsapiUnreachable("Zařízení neodpovídá (vypršel časový limit).") from exc
            except httpx.ConnectError as exc:
                text = str(exc)
                if "SSL" in text or "certificate" in text.lower():
                    raise IsapiUnreachable(
                        "Chyba TLS při připojení k zařízení (zkontrolujte HTTPS a ověřování certifikátu)."
                    ) from exc
                raise IsapiUnreachable("Nelze se připojit k zařízení.") from exc
            except httpx.HTTPError as exc:
                raise IsapiUnreachable(f"Chyba komunikace se zařízením ({exc.__class__.__name__}).") from exc

            if (
                resp.status_code == 401
                and attempt == 0
                and self._host_key not in _basic_only_hosts
                and self._offers_only_basic(resp)
            ):
                if stream:
                    await resp.aclose()
                _basic_only_hosts.add(self._host_key)
                continue
            return resp
        return resp

    async def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.status_code < 400:
            return
        if not resp.is_closed:
            await resp.aread()
        status_string, sub_status = _status_detail(resp.content)
        if resp.status_code == 401:
            raise IsapiAuthError(
                "Zařízení odmítlo přihlášení – zkontrolujte jméno a heslo (účet může být dočasně zablokován)."
            )
        if resp.status_code == 404 or sub_status.lower() == "notsupport":
            raise IsapiNotSupported("Zařízení tuto funkci nepodporuje.")
        detail = ", ".join(filter(None, [status_string, sub_status]))
        if resp.status_code == 403:
            raise IsapiError(f"Zařízení odmítlo požadavek ({detail or 'přístup zamítnut'}).")
        raise IsapiError(f"Zařízení vrátilo chybu HTTP {resp.status_code}{' (' + detail + ')' if detail else ''}.")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        content: bytes | None = None,
        timeout: httpx.Timeout | None = None,
    ) -> httpx.Response:
        resp = await self._send(method, path, content=content, timeout=timeout)
        await self._raise_for_status(resp)
        return resp

    async def _get_xml(self, path: str) -> Element:
        resp = await self._request("GET", path)
        return parse_xml(resp.content)

    @staticmethod
    def _check_response_status(resp: httpx.Response) -> None:
        try:
            root = parse_xml(resp.content)
        except IsapiError:
            return
        if root.tag != "ResponseStatus":
            return
        code = _text(root, "statusCode")
        if code in {"", "1", "7"}:  # 1 = OK, 7 = vyžaduje restart
            return
        detail = ", ".join(filter(None, [_text(root, "statusString"), _text(root, "subStatusCode")]))
        raise IsapiError(f"Zařízení odmítlo změnu ({detail or 'kód ' + code}).")

    # --- informace o zařízení ------------------------------------------------

    async def device_info(self) -> dict[str, str]:
        root = await self._get_xml("/ISAPI/System/deviceInfo")
        firmware = " ".join(filter(None, [_text(root, "firmwareVersion"), _text(root, "firmwareReleasedDate")]))
        return {
            "device_name": _text(root, "deviceName")[:128],
            "device_type": _text(root, "deviceType")[:64],
            "model": _text(root, "model")[:128],
            "serial_number": _text(root, "serialNumber")[:128],
            "firmware": firmware[:128],
            "mac_address": _text(root, "macAddress")[:64],
        }

    async def channels(self, device_type: str) -> list[ChannelInfo]:
        """Seznam kamer. U NVR z InputProxy (vč. stavu online), jinak ze streamů."""
        try:
            proxy = await self._get_xml("/ISAPI/ContentMgmt/InputProxy/channels")
        except IsapiNotSupported:
            proxy = None

        if proxy is not None and proxy.tag == "InputProxyChannelList":
            found: dict[int, ChannelInfo] = {}
            for item in proxy.iter("InputProxyChannel"):
                channel = _int(_text(item, "id"))
                if channel <= 0:
                    continue
                ip = _text(item, "sourceInputPortDescriptor/ipAddress") or _text(
                    item, "sourceInputPortDescriptor/hostName"
                )
                found[channel] = ChannelInfo(
                    channel=channel,
                    name=(_text(item, "name") or f"Kamera {channel}")[:128],
                    ip_address=ip[:128],
                    online=None,
                    detail="",
                )
            if found:
                try:
                    status_root = await self._get_xml("/ISAPI/ContentMgmt/InputProxy/channels/status")
                except IsapiNotSupported:
                    status_root = None
                if status_root is not None:
                    for item in status_root.iter("InputProxyChannelStatus"):
                        channel = _int(_text(item, "id"))
                        info = found.get(channel)
                        if info is None:
                            continue
                        online_text = _text(item, "online").lower()
                        if online_text in {"true", "false"}:
                            info.online = online_text == "true"
                        detect = _text(item, "chanDetectResult")
                        info.detail = DETECT_RESULT_CS.get(detect.lower(), detect)[:128]
            return [found[key] for key in sorted(found)]

        root = await self._get_xml("/ISAPI/Streaming/channels")
        is_camera = device_type.lower() in CAMERA_DEVICE_TYPES
        result: list[ChannelInfo] = []
        seen: set[int] = set()
        for item in root.iter("StreamingChannel"):
            stream_id = _int(_text(item, "id"))
            if stream_id <= 0 or stream_id % 100 != 1:
                continue
            channel = stream_id // 100
            if channel in seen:
                continue
            seen.add(channel)
            result.append(
                ChannelInfo(
                    channel=channel,
                    name=(_text(item, "channelName") or f"Kamera {channel}")[:128],
                    ip_address="",
                    # samostatná kamera odpověděla => je online; u DVR stav neznáme
                    online=True if is_camera else None,
                    detail="",
                )
            )
        return sorted(result, key=lambda c: c.channel)

    async def storage(self) -> list[dict[str, Any]]:
        try:
            root = await self._get_xml("/ISAPI/ContentMgmt/Storage")
        except IsapiNotSupported:
            return []
        disks: list[dict[str, Any]] = []
        for hdd in root.iter("hdd"):
            disk_id = _text(hdd, "id")
            disks.append(
                {
                    "id": disk_id,
                    "kind": "HDD",
                    "name": (_text(hdd, "hddName") or f"HDD {disk_id}")[:64],
                    "status": _text(hdd, "status")[:32],
                    "capacity_mb": _int(_text(hdd, "capacity")),
                    "free_mb": _int(_text(hdd, "freeSpace")),
                    "property": _text(hdd, "property")[:32],
                }
            )
        for nas in root.iter("nas"):
            disk_id = _text(nas, "id")
            disks.append(
                {
                    "id": disk_id,
                    "kind": "NAS",
                    "name": (_text(nas, "ipAddress") or f"NAS {disk_id}")[:64],
                    "status": _text(nas, "status")[:32],
                    "capacity_mb": _int(_text(nas, "capacity")),
                    "free_mb": _int(_text(nas, "freeSpace")),
                    "property": _text(nas, "property")[:32],
                }
            )
        return disks

    async def device_time(self) -> str:
        try:
            root = await self._get_xml("/ISAPI/System/time")
        except IsapiNotSupported:
            return ""
        return _text(root, "localTime")[:64]

    async def snapshot(self, channel: int) -> tuple[bytes, str]:
        resp = await self._request(
            "GET",
            f"/ISAPI/Streaming/channels/{main_stream_id(channel)}/picture",
            timeout=httpx.Timeout(20.0, connect=5.0),
        )
        content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        if not content_type.startswith("image/"):
            raise IsapiError("Zařízení nevrátilo obrázek.")
        if len(resp.content) > MAX_SNAPSHOT_SIZE:
            raise IsapiError("Snímek je příliš velký.")
        return resp.content, content_type

    async def reboot(self) -> None:
        resp = await self._request("PUT", "/ISAPI/System/reboot")
        self._check_response_status(resp)

    # --- záznamy -------------------------------------------------------------

    async def search_recordings(self, channel: int, start: datetime, end: datetime) -> list[RecordingSegment]:
        search_id = str(uuid.uuid4()).upper()
        track = main_stream_id(channel)
        position = 0
        segments: list[RecordingSegment] = []
        while len(segments) < SEARCH_MAX_RESULTS:
            body = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                "<CMSearchDescription>"
                f"<searchID>{search_id}</searchID>"
                f"<trackList><trackID>{track}</trackID></trackList>"
                "<timeSpanList><timeSpan>"
                f"<startTime>{format_search_time(start)}</startTime>"
                f"<endTime>{format_search_time(end)}</endTime>"
                "</timeSpan></timeSpanList>"
                f"<maxResults>{SEARCH_PAGE_SIZE}</maxResults>"
                f"<searchResultPostion>{position}</searchResultPostion>"
                "<metadataList><metadataDescriptor>//recordType.meta.std-cgi.com</metadataDescriptor></metadataList>"
                "</CMSearchDescription>"
            )
            resp = await self._request(
                "POST",
                "/ISAPI/ContentMgmt/search",
                content=body.encode(),
                timeout=httpx.Timeout(30.0, connect=5.0),
            )
            root = parse_xml(resp.content)
            status_str = _text(root, "responseStatusStrg").upper()
            items = list(root.iter("searchMatchItem"))
            for item in items:
                seg_start = parse_device_datetime(_text(item, "timeSpan/startTime"))
                seg_end = parse_device_datetime(_text(item, "timeSpan/endTime"))
                uri = _text(item, "mediaSegmentDescriptor/playbackURI")
                if seg_start is None or seg_end is None or seg_end <= seg_start:
                    continue
                descriptor = _text(item, "metadataMatches/metadataDescriptor")
                record_type = descriptor.rsplit("/", 1)[-1] if descriptor else ""
                segments.append(
                    RecordingSegment(
                        start=seg_start, end=seg_end, record_type=record_type[:32], playback_uri=uri[:2048]
                    )
                )
            if status_str != "MORE" or not items:
                break
            position += len(items)
        segments.sort(key=lambda s: s.start)
        return segments

    @asynccontextmanager
    async def download(self, playback_uri: str) -> AsyncIterator[httpx.Response]:
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<downloadRequest version="1.0" xmlns="http://www.isapi.org/ver20/XMLSchema">'
            f"<playbackURI>{xml_escape(playback_uri)}</playbackURI>"
            "</downloadRequest>"
        )
        resp = await self._send(
            "GET", "/ISAPI/ContentMgmt/download", content=body.encode(), timeout=DOWNLOAD_TIMEOUT, stream=True
        )
        try:
            await self._raise_for_status(resp)
            yield resp
        finally:
            await resp.aclose()

    # --- nastavení streamů ---------------------------------------------------

    async def get_stream_settings(self, stream_id: int) -> dict[str, Any]:
        root = await self._get_xml(f"/ISAPI/Streaming/channels/{stream_id}")
        video = root.find("Video")
        if video is None:
            raise IsapiNotSupported("Stream nemá video parametry.")
        current: dict[str, Any] = {}
        for field in STREAM_FIELDS:
            el = video.find(field)
            if el is None or el.text is None:
                continue
            value = el.text.strip()
            current[field] = _int(value) if field in STREAM_INT_FIELDS else value

        options: dict[str, list[str]] = {}
        ranges: dict[str, list[int]] = {}
        resolutions: list[list[int]] = []
        try:
            caps = await self._get_xml(f"/ISAPI/Streaming/channels/{stream_id}/capabilities")
        except IsapiError:
            caps = None
        caps_video = caps.find("Video") if caps is not None else None
        if caps_video is not None:
            for field in STREAM_FIELDS:
                el = caps_video.find(field)
                if el is None:
                    continue
                opt = el.get("opt")
                if opt:
                    options[field] = [o.strip() for o in opt.split(",") if o.strip()]
                if el.get("min") is not None and el.get("max") is not None:
                    lo, hi = _int(el.get("min", "")), _int(el.get("max", ""))
                    if hi >= lo:
                        ranges[field] = [lo, hi]
            widths = options.get("videoResolutionWidth", [])
            heights = options.get("videoResolutionHeight", [])
            if widths and len(widths) == len(heights):
                for w, h in zip(widths, heights):
                    pair = [_int(w), _int(h)]
                    if pair[0] > 0 and pair[1] > 0 and pair not in resolutions:
                        resolutions.append(pair)
        return {"current": current, "options": options, "ranges": ranges, "resolutions": resolutions}

    async def set_stream_settings(self, stream_id: int, changes: dict[str, Any]) -> None:
        path = f"/ISAPI/Streaming/channels/{stream_id}"
        resp = await self._request("GET", path)
        text = resp.text
        match = re.search(r"<Video\b[^>]*>.*?</Video>", text, re.S)
        if match is None:
            raise IsapiNotSupported("Stream nemá video parametry.")
        segment = match.group(0)
        for field, value in changes.items():
            if field not in STREAM_FIELDS:
                raise IsapiError(f"Neznámý parametr {field}.")
            pattern = re.compile(rf"(<{field}\b[^>]*>)([^<]*)(</{field}>)")
            if pattern.search(segment) is None:
                raise IsapiNotSupported(f"Zařízení nepodporuje parametr {field}.")
            replacement = xml_escape(str(value))
            segment = pattern.sub(lambda m: m.group(1) + replacement + m.group(3), segment, count=1)
        new_text = text[: match.start()] + segment + text[match.end():]
        put = await self._request("PUT", path, content=new_text.encode("utf-8"))
        self._check_response_status(put)


def drift_seconds(device_time: str) -> int | None:
    parsed = parse_device_time(device_time)
    if parsed is None:
        return None
    return int((parsed - datetime.now(timezone.utc)).total_seconds())
