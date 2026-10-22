"""Naplní demo ukázkovými daty. Spouští se uvnitř kontejneru aplikace (viz dev/demo.sh)."""

import asyncio
import time

import httpx

from app import app_settings
from app.db import SessionLocal

BASE = "http://127.0.0.1:8000"
ADMIN = ("admin", "Elenvar-Demo-2026")
DEVICES = [
    {"name": "Areál Brno", "host": "mock-areal", "notes": "Hlavní areál, 4 kamery."},
    {"name": "Sklad Ostrava", "host": "mock-sklad", "notes": "Pobočka, nakládací rampa."},
]
USERS = [
    {"username": "jnovak", "full_name": "Jan Novák", "role": "operator", "password": "Operator-Demo-2026"},
    {"username": "recepce", "full_name": "Recepce", "role": "viewer", "password": "Pozorovatel-Demo-2026"},
]


async def demo_settings() -> None:
    async with SessionLocal() as db:
        # Jen pro demo: bez povinného 2FA a s rychlejší kontrolou stavu.
        await app_settings.set_many(db, {"require_2fa": False, "poll_interval": 20, "offline_threshold": 1})
        await db.commit()


def main() -> None:
    asyncio.run(demo_settings())
    c = httpx.Client(base_url=BASE, timeout=60)
    r = c.post("/api/auth/login", json={"username": ADMIN[0], "password": ADMIN[1]})
    r.raise_for_status()
    h = {"X-CSRF-Token": r.json()["csrf_token"]}

    existing = {n["name"] for n in c.get("/api/nvrs").json()}
    for dev in DEVICES:
        if dev["name"] in existing:
            continue
        body = {**dev, "username": "admin", "password": "p@ss:w/rd"}
        c.post("/api/nvrs", json=body, headers=h).raise_for_status()
        print(f"  + zařízení {dev['name']}")

    users = {u["username"] for u in c.get("/api/users").json()}
    for user in USERS:
        if user["username"] not in users:
            c.post("/api/users", json=user, headers=h).raise_for_status()
            print(f"  + uživatel {user['username']}")

    nvrs = {n["name"]: n["id"] for n in c.get("/api/nvrs").json()}
    for _ in range(30):
        cams = c.get("/api/cameras").json()
        if len(cams) >= 8:
            break
        time.sleep(1)

    # Kancelář se nemá hlídat (kamera je mimo pracovní dobu vypnutá).
    for cam in cams:
        if cam["name"] == "Kancelář" and cam["monitored"]:
            c.patch(f"/api/cameras/{cam['id']}", json={"monitored": False}, headers=h)

    # Historie: krátký výpadek kamery „Brána sever“ a jeho obnovení.
    events = c.get("/api/events").json()
    if not any("Brána sever" in e["message"] for e in events):
        sklad = nvrs["Sklad Ostrava"]
        httpx.get("http://mock-sklad/mock/set?offline=2", timeout=10)
        c.post(f"/api/nvrs/{sklad}/poll", headers=h)
        time.sleep(2)
        httpx.get("http://mock-sklad/mock/set?offline=", timeout=10)
        c.post(f"/api/nvrs/{sklad}/poll", headers=h)
    c.post("/api/auth/logout", headers=h)
    print("  hotovo")


if __name__ == "__main__":
    main()
