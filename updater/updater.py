"""Elenvar updater – jediná služba s přístupem k Dockeru.

Umí jedinou pevně danou akci: stáhnout novější obraz služby „app“ a restartovat ji
přes docker compose se stejnou konfigurací, se kterou byla spuštěna. Je dostupná
pouze v interní Docker síti a vyžaduje tajný token, který sdílí s aplikací přes
společný svazek.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import secrets
import socket
import subprocess
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TOKEN_FILE = Path(os.environ.get("UPDATER_TOKEN_FILE", "/run/elenvar-updater/token"))
APP_GID = int(os.environ.get("UPDATER_APP_GID", "10001"))
PROJECT_MOUNT = Path(os.environ.get("UPDATER_PROJECT_MOUNT", "/project"))
SERVICE = "app"
LISTEN_PORT = int(os.environ.get("UPDATER_PORT", "9000"))
COMMAND_TIMEOUT = 15 * 60

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s updater: %(message)s")
log = logging.getLogger("updater")

_lock = threading.Lock()
_state: dict = {
    "state": "idle",  # idle | running | done | failed
    "phase": "",
    "result": "",  # updated | current
    "message": "",
    "started_at": None,
    "finished_at": None,
}
_log: deque[str] = deque(maxlen=300)


class UpdateError(Exception):
    pass


# --- token -------------------------------------------------------------------

def ensure_token() -> str:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not TOKEN_FILE.exists():
        fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
        with os.fdopen(fd, "w") as fh:
            fh.write(secrets.token_urlsafe(32))
    # Číst smí jen root (updater) a skupina aplikace.
    os.chown(TOKEN_FILE, 0, APP_GID)
    os.chmod(TOKEN_FILE, 0o640)
    return TOKEN_FILE.read_text().strip()


TOKEN = ""


# --- docker ------------------------------------------------------------------

def run_capture(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise UpdateError((result.stderr or result.stdout).strip()[:500] or f"Příkaz {args[0]} selhal.")
    return result.stdout


def inspect(ref: str) -> dict:
    data = json.loads(run_capture(["docker", "inspect", ref]))
    if not data:
        raise UpdateError(f"Objekt {ref} neexistuje.")
    return data[0]


def own_project() -> str:
    me = inspect(socket.gethostname())
    project = me.get("Config", {}).get("Labels", {}).get("com.docker.compose.project")
    if not project:
        raise UpdateError("Updater neběží jako součást docker compose projektu.")
    return project


def app_container(project: str) -> dict:
    ids = run_capture(
        [
            "docker", "ps", "-a", "--format", "{{.ID}}",
            "--filter", f"label=com.docker.compose.project={project}",
            "--filter", f"label=com.docker.compose.service={SERVICE}",
        ]
    ).split()
    if not ids:
        raise UpdateError("Kontejner aplikace nebyl nalezen.")
    return inspect(ids[0])


def prepare_project_dir(working_dir: str, config_files: list[str]) -> None:
    """Zpřístupní soubory projektu pod stejnou cestou, jakou vidí Docker na hostiteli.

    Compose předává démonovi cesty relativní k adresáři projektu; aby odkazovaly
    na správná místa na hostiteli, musí updater pracovat se stejnou cestou.
    Adresář projektu je připojený do /project, takže stačí symbolický odkaz.
    """
    if not (PROJECT_MOUNT / "docker-compose.yml").exists():
        raise UpdateError("Adresář projektu není připojený do updateru (/project).")
    wd = Path(working_dir)
    if not wd.is_absolute() or ".." in wd.parts:
        raise UpdateError("Neplatný adresář projektu.")
    if not wd.exists():
        wd.parent.mkdir(parents=True, exist_ok=True)
        wd.symlink_to(PROJECT_MOUNT)
    for cfg in config_files:
        path = Path(cfg)
        if not path.is_absolute() or wd not in path.parents:
            raise UpdateError(f"Konfigurační soubor {cfg} leží mimo adresář projektu.")
        if not path.exists():
            raise UpdateError(f"Konfigurační soubor {cfg} nebyl nalezen.")


def run_logged(args: list[str], cwd: str) -> None:
    _log.append("$ " + " ".join(args[:1] + ["compose", "…"] + args[-3:]))
    proc = subprocess.Popen(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    started = time.monotonic()
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            _log.append(line[:300])
        if time.monotonic() - started > COMMAND_TIMEOUT:
            proc.kill()
            raise UpdateError("Aktualizace trvá příliš dlouho, byla přerušena.")
    if proc.wait() != 0:
        raise UpdateError("Příkaz docker compose skončil chybou – podrobnosti jsou v záznamu.")


def set_state(**changes) -> None:
    with _lock:
        _state.update(changes)


def do_update() -> None:
    try:
        set_state(phase="Hledám aplikaci")
        project = own_project()
        app = app_container(project)
        labels = app.get("Config", {}).get("Labels", {})
        working_dir = labels.get("com.docker.compose.project.working_dir", "")
        config_files = [f for f in labels.get("com.docker.compose.project.config_files", "").split(",") if f]
        image_ref = app.get("Config", {}).get("Image", "")
        old_image = app.get("Image", "")
        if not working_dir or not config_files or not image_ref:
            raise UpdateError("Kontejner aplikace nemá údaje docker compose.")
        prepare_project_dir(working_dir, config_files)

        compose = ["docker", "compose", "-p", project, "--project-directory", working_dir]
        for cfg in config_files:
            compose += ["-f", cfg]

        set_state(phase="Stahuji novou verzi")
        run_logged(compose + ["pull", SERVICE], cwd=working_dir)
        new_image = inspect(image_ref).get("Id", "")
        if new_image and new_image == old_image:
            _log.append("Obraz aplikace je aktuální, restart není potřeba.")
            set_state(state="done", result="current", phase="", message="Elenvar je aktuální.", finished_at=time.time())
            return

        set_state(phase="Restartuji aplikaci")
        run_logged(compose + ["up", "-d", "--no-deps", "--no-build", SERVICE], cwd=working_dir)
        set_state(state="done", result="updated", phase="", message="Aktualizace byla nainstalována.", finished_at=time.time())
        log.info("Aplikace aktualizována (%s)", image_ref)
    except (UpdateError, subprocess.SubprocessError, OSError, ValueError) as exc:
        log.warning("Aktualizace selhala: %s", exc)
        _log.append(f"Chyba: {exc}")
        set_state(state="failed", phase="", message=str(exc)[:500], finished_at=time.time())


# --- HTTP --------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "elenvar-updater"
    sys_version = ""

    def log_message(self, fmt, *args):
        log.info("%s %s", self.command, self.path)

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        header = self.headers.get("Authorization", "")
        supplied = header[7:] if header.startswith("Bearer ") else ""
        return bool(supplied) and hmac.compare_digest(supplied.encode(), TOKEN.encode())

    def _status(self) -> dict:
        with _lock:
            payload = dict(_state)
        payload["log"] = list(_log)[-120:]
        return payload

    def do_GET(self):
        if self.path == "/health":
            return self._json(200, {"status": "ok"})
        if not self._authorized():
            return self._json(401, {"detail": "unauthorized"})
        if self.path == "/status":
            return self._json(200, self._status())
        return self._json(404, {"detail": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(min(length, 4096))
        if not self._authorized():
            return self._json(401, {"detail": "unauthorized"})
        if self.path != "/update":
            return self._json(404, {"detail": "not found"})
        with _lock:
            if _state["state"] == "running":
                return self._json(409, {"detail": "Aktualizace už probíhá."})
            _state.update(state="running", phase="Připravuji", result="", message="", started_at=time.time(), finished_at=None)
            _log.clear()
        threading.Thread(target=do_update, name="update", daemon=True).start()
        return self._json(202, self._status())


def main() -> None:
    global TOKEN
    TOKEN = ensure_token()
    log.info("Updater naslouchá na portu %s", LISTEN_PORT)
    ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
