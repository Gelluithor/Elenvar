"""Spuštění simulátoru: vygeneruje konfiguraci go2rtc (RTSP) podle MOCK_CHANNELS a spustí ISAPI server.

Pouze pro vývoj a demo. Každá kamera má hlavní stream (720p) a substream (360p) s OSD
jako u kamer Hikvision; kodér se spouští až při připojení diváka.
"""

import json
import os
import subprocess
import sys

FONT_MONO = "/usr/share/fonts/droid/DroidSansMono.ttf"
FONT = "/usr/share/fonts/droid/DroidSans.ttf"


def channels() -> list[str]:
    raw = os.environ.get("MOCK_CHANNELS", "Vjezd,Parkoviště,Sklad,Recepce")
    return [c.strip() for c in raw.split(",") if c.strip()]


def scene(name: str, w: int, h: int, fps: int, seed: int, label: str = "") -> str:
    fs = max(14, h // 24)
    bx = int(w * (0.06 + (seed % 4) * 0.08))
    lamp = int(w * (0.62 + (seed % 3) * 0.1))
    text = f"{name}{label}".replace("'", "")
    parts = [
        f"gradients=s={w}x{h}:r={fps}:c0=0x1d2836:c1=0x2c394a:c2=0x131b26:n=3:speed=0.003:seed={seed}",
        f"drawbox=x=0:y={int(h * 0.62)}:w={w}:h={h}:color=0x0e141c@0.75:t=fill",
        f"drawbox=x={bx}:y={int(h * 0.26)}:w={int(w * 0.3)}:h={int(h * 0.36)}:color=0x0b1018@0.95:t=fill",
        f"drawbox=x={bx + int(w * 0.05)}:y={int(h * 0.33)}:w={w // 40}:h={h // 26}:color=0xd9b25c@0.75:t=fill",
        f"drawbox=x={bx + int(w * 0.17)}:y={int(h * 0.42)}:w={w // 40}:h={h // 26}:color=0xd9b25c@0.6:t=fill",
        f"drawbox=x={lamp}:y={int(h * 0.3)}:w={max(2, w // 320)}:h={int(h * 0.32)}:color=0x0b1018:t=fill",
        f"drawbox=x={lamp - w // 60}:y={int(h * 0.28)}:w={w // 30}:h={h // 60 + 2}:color=0xf2deb0@0.8:t=fill",
        f"drawbox=x='mod(t*{w // (10 + seed)}\\,{w + 220})-180':y={int(h * 0.66)}:w={w // 8}:h={h // 12}:color=0xa9b2bd@0.7:t=fill",
        "noise=alls=9:allf=t",
    ]
    # Hodiny jen u živého obrazu – simulátor nezná skutečný čas přehrávaného záznamu.
    if not label:
        parts.append(
            f"drawtext=fontfile={FONT_MONO}:text='%{{localtime}}':fontcolor=white:fontsize={fs}:x={fs // 2}:y={fs // 2}:borderw=1:bordercolor=black@0.6"
        )
    parts += [
        f"drawtext=fontfile={FONT}:text='{text}':fontcolor=white:fontsize={fs}:x=w-tw-{fs // 2}:y=h-th-{fs // 2}:borderw=1:bordercolor=black@0.6",
    ]
    return ",".join(parts)


def stream(name: str, w: int, h: int, fps: int, seed: int, label: str = "") -> str:
    return (
        f'exec:ffmpeg -hide_banner -loglevel error -re -f lavfi -i "{scene(name, w, h, fps, seed, label)}" '
        f"-c:v libx264 -preset ultrafast -tune zerolatency -g {fps * 2} -pix_fmt yuv420p -f rtsp {{output}}"
    )


def main() -> None:
    streams = {}
    # Kamery hlášené jako offline nestreamují (stejně jako skutečná nedostupná kamera).
    offline = {int(x) for x in os.environ.get("MOCK_OFFLINE", "3").split(",") if x.strip()}
    for i, name in enumerate(channels(), start=1):
        if i in offline:
            continue
        streams[f"Streaming/Channels/{i}01"] = stream(name, 1280, 720, 15, i)
        streams[f"Streaming/Channels/{i}02"] = stream(name, 640, 360, 12, i)
        streams[f"Streaming/tracks/{i}01"] = stream(name, 1280, 720, 15, i, " · ZÁZNAM")
    config = {
        "api": {"listen": "127.0.0.1:1984"},
        "webrtc": {"listen": ""},
        "rtsp": {
            "listen": ":554",
            "username": os.environ.get("MOCK_USER", "admin"),
            "password": os.environ.get("MOCK_PASSWORD", "p@ss:w/rd"),
        },
        "log": {"level": "warn"},
        "streams": streams,
    }
    with open("/tmp/go2rtc.yaml", "w", encoding="utf-8") as fh:
        json.dump(config, fh, ensure_ascii=False)
    rtsp = subprocess.Popen(["go2rtc", "-config", "/tmp/go2rtc.yaml"])
    try:
        os.execvp(sys.executable, [sys.executable, "-u", "/mock/mock_isapi.py"])
    finally:
        rtsp.terminate()


if __name__ == "__main__":
    main()
