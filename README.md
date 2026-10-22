<p align="center">
  <img src="frontend/public/logo-dark.svg" width="96" height="96" alt="">
</p>

<h1 align="center">Elenvar</h1>

<p align="center">Self-hosted central management and monitoring for Hikvision camera systems, running in Docker.</p>

---

## Features

- **Live view from multiple NVRs at once**: 1 / 4 / 9 / 16 tile layouts, drag and drop, full screen, and automatic quality selection (substream in the grid, main stream when enlarged).
- **Recordings**: search recordings on the NVR, browse a day timeline (continuous recording vs. events), play from any point, skip ±30 s and download segments.
- **Monitoring**: periodic checks of NVR availability, camera status, disks (HDD/NAS) and clock drift.
  - Mark the cameras that must stay online. Elenvar logs an event and sends a notification (e-mail, webhook) when they go down and when they come back.
  - A configurable failure threshold prevents false alarms.
- **Device settings**: change camera stream parameters (codec, resolution, frame rate, bitrate, GOP) within the camera's capabilities, and restart devices remotely.
- **Security**:
  - Mandatory two-factor authentication (TOTP) with recovery codes.
  - Roles and a full audit log.
- **Updates from the web interface**: Elenvar watches for new releases and installs them after the administrator confirms.
- **Czech and English**: the interface follows the browser language and can be switched at any time.

Supported devices: Hikvision NVRs (primary target), DVRs and standalone IP cameras with the ISAPI interface.

## Architecture

```
browser ──HTTPS──▶ Caddy ──▶ app (FastAPI + React UI) ──ISAPI (HTTP/Digest)──▶ NVR
                               │
                               └─WebSocket─▶ go2rtc ──RTSP──▶ NVR

               updater ──Docker API──▶ restarts "app" with a newer image (on request)
```

| Service   | Role |
|-----------|------|
| `caddy`   | The only service exposed to the network. HTTPS (internal CA or Let's Encrypt) and HTTP → HTTPS redirect. |
| `app`     | API, web interface, authentication, background monitoring and video proxy. Data is stored in SQLite in the `elenvar-data` volume. |
| `go2rtc`  | Internal RTSP → MSE (fMP4) conversion for the browser. It is not reachable outside the Docker network and keeps camera credentials in memory only (tmpfs). |
| `updater` | The only service with access to Docker. It can do exactly one thing: pull a newer `app` image and restart the `app` container. Internal network only, protected by a shared token. |

Video always goes through the application. The browser never connects to an NVR or to go2rtc directly, and every stream is checked against the user's session and role.

## Installation

Requirements: Docker with Compose v2. The server must be able to reach the NVRs on their HTTP (ISAPI) and RTSP ports.

```bash
git clone https://github.com/Gelluithor/Elenvar.git && cd Elenvar
cp .env.example .env
# set ELENVAR_DOMAIN (the address you will open Elenvar on)
docker compose up -d --build
docker compose logs app | grep -A3 "Administrator account"   # initial admin password
```

Open `https://<ELENVAR_DOMAIN>`, sign in as `admin`, set up two-factor authentication and change the password.

Released images are also published to the GitHub Container Registry, so `docker compose pull && docker compose up -d` works without building locally.

### HTTPS

- **Local network** (`ELENVAR_TLS=internal`): Caddy issues a certificate from its own certificate authority, so browsers warn about it at first. To remove the warning, import the root certificate on your computers:
  `docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt ./elenvar-root.crt`
- **Public domain** (`ELENVAR_TLS=you@example.com`): Caddy obtains a Let's Encrypt certificate automatically. Ports 80 and 443 must be reachable from the internet.
- `ELENVAR_DOMAIN` may list several addresses separated by commas, e.g. `elenvar.example.lan, 192.168.1.20`.

### Configuration (`.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `ELENVAR_DOMAIN` | `localhost` | Address(es) of the web interface. |
| `ELENVAR_TLS` | `internal` | `internal`, or an e-mail address for Let's Encrypt. |
| `ELENVAR_HTTP_PORT` / `ELENVAR_HTTPS_PORT` | `80` / `443` | Ports on the host. |
| `ELENVAR_ADMIN_USERNAME` | `admin` | Name of the first administrator (first start only). |
| `ELENVAR_ADMIN_PASSWORD` | *(generated)* | Password of the first administrator. If empty, it is generated and printed to the log. |
| `ELENVAR_SESSION_IDLE_MINUTES` | `60` | Sign-out after inactivity (watching video counts as activity). |
| `ELENVAR_SESSION_MAX_HOURS` | `12` | Maximum session length. |
| `ELENVAR_SECRET_KEY` | *(generated into the volume)* | Key used to encrypt NVR and SMTP passwords. |
| `ELENVAR_PLAYBACK_SOURCE` | `rtsp` | Set to `ffmpeg` for firmware where direct playback does not work. |
| `ELENVAR_IMAGE`, `ELENVAR_UPDATER_IMAGE`, `ELENVAR_IMAGE_TAG` | `ghcr.io/gelluithor/…`, `latest` | Where updates are pulled from. |
| `ELENVAR_UPDATE_REPO` | `Gelluithor/Elenvar` | GitHub repository that is checked for new releases. |
| `TZ` | `Europe/Prague` | Server time zone. |

Everything else is changed in the web interface under **Settings**:
- check interval and failure threshold;
- notifications and their language;
- enforcing 2FA;
- data retention;
- update checks.

## Preparing a Hikvision NVR

1. **Enable ISAPI.** On newer firmware: *Configuration → Network → Advanced → Integration Protocol → Enable Hikvision-CGI / ISAPI*.
2. **Create a dedicated user** for Elenvar (recommended).
   - It needs remote live view and playback permissions.
   - To change streams and restart the device, it also needs parameter configuration and reboot permissions.
3. **Authentication.** The default *digest* mode is fine; Elenvar supports both digest and basic.
4. **Substream codec.** Browsers reliably play **H.264**.
   - H.265 works in Chrome, Edge and Safari only with hardware support, and not at all in Firefox.
   - Set the substream to H.264. You can do it directly in Elenvar: *Devices → device → Stream*.
   - Alternatively, enable *Convert video to H.264* for the device (uses server CPU).
5. The server must reach the NVR's HTTP (80/443) and RTSP (554) ports.

> If the NVR password is wrong, Elenvar stops polling the device so that Hikvision does not lock the account or the server's IP address. Polling resumes once the credentials are fixed.

## Roles

| Role | Permissions |
|------|-------------|
| Viewer | Overview, live view, monitoring status and events. |
| Operator | Additionally: playing and downloading recordings, acknowledging events. |
| Administrator | Everything, including devices, users, settings and the audit log. |

## Security

- **Passwords:** hashed with **Argon2id**, minimum length 12 characters.
- **Two-factor authentication (TOTP):** required by default. Codes can't be reused, and there are 10 one-time recovery codes, stored as hashes.
- **Sessions:**
  - Stored on the server, with an `__Host-` cookie that is `HttpOnly`, `Secure` and `SameSite=Strict`.
  - A new token is issued after sign-in, which prevents session fixation.
  - Sessions have both an idle timeout and a maximum lifetime.
- **CSRF protection:** a token for every state-changing request, plus an `Origin` check, also on WebSockets.
- **Sign-in rate limiting:** limits per IP and per account; an account is temporarily locked after 5 failed attempts.
- **Stored credentials:** NVR and SMTP passwords are encrypted (Fernet/AES) and never sent to the browser. Viewers and operators don't even see device addresses.
- **Security headers:** strict HTTP headers, including a CSP without inline scripts, HSTS, `X-Frame-Options` and `nosniff`.
- **Containers:**
  - The application runs as an unprivileged user.
  - All containers drop capabilities and use `no-new-privileges`.
  - The app and go2rtc also use read-only file systems.
- **Audit log:** covers sign-ins, settings changes, playback, downloads and updates.

Recommendation: don't expose Elenvar to the internet unless you have to. Keep it on the local network or behind a VPN.

## Updates

Elenvar checks GitHub for a new release every 6 hours, and you can also check manually. When a new version is out:
- an event appears in Monitoring;
- a notification is sent;
- a dot appears next to **Settings**.

Install it under *Settings → Software update → Update now*. Elenvar asks for your password, pulls the new image, restarts and reloads the page.

- Updating from the web replaces the application image only. If a release changes `docker-compose.yml` (for example a new go2rtc version), update the compose file on the server once (`git pull && docker compose up -d`).
- If you don't want updates from the web, remove the `updater` service from `docker-compose.yml`.

### Publishing a release

1. Bump the version in `VERSION`, update `CHANGELOG.md` and commit.
2. Create a GitHub release with the tag `v<version>` (e.g. `v1.1.0`).
3. The *Release* workflow builds multi-architecture images (amd64, arm64) and pushes them to `ghcr.io`.

GHCR packages are private by default. Make them public, or run `docker login ghcr.io` on the server once.

## Backup

All data lives in the `elenvar-data` volume: the database and the encryption key `secret.key`.

**Back up the key together with the database.** Without it, the stored NVR passwords cannot be decrypted.

```bash
docker run --rm -v elenvar_elenvar-data:/data -v "$PWD":/backup alpine tar czf /backup/elenvar-backup.tgz -C /data .
```

If an administrator loses access to their 2FA device, another administrator can reset their 2FA under **Users**. If there is no other administrator, sign in with a recovery code.

## Notes and limitations

- Recording times are shown in the NVR's time, as the device reports them. Keep the NVR clock synchronised via NTP; Elenvar monitors its drift.
- Audio is not played in the browser, because cameras usually use G.711, which browsers do not support.
- Downloaded recordings are in Hikvision's native format. VLC, for example, can play them.
- Playback runs in real time (no fast-forward).
- For analog DVR channels, camera status can't be reliably detected over ISAPI. Only device availability and disks are monitored.

## Demo

Try Elenvar without real hardware: two simulated NVRs with eight cameras and sample data.

```bash
dev/demo.sh        # starts the demo on http://localhost:8080 (sign in: admin / Elenvar-Demo-2026)
dev/demo.sh down   # stops the demo and deletes its data
```

The demo runs separately from a production installation, only on the local machine, and without mandatory 2FA.

## Development

The repository contains a Hikvision NVR simulator: ISAPI with digest authentication, and RTSP with a camera-like picture and on-screen display.

```bash
docker compose -f docker-compose.yml -f dev/docker-compose.dev.yml up -d --build
```

In the app, add a device with the address `mock-nvr`, user `admin` and password `p@ss:w/rd`. The simulator state can be changed from the app container, e.g. `http://mock-nvr/mock/set?offline=1,3&hdd=error`.

- Frontend: React + TypeScript + Vite (`frontend/`).
- Backend: Python FastAPI (`backend/`).
- Updater: `updater/`.

### Translations

Czech is the source language in the code. English translations live in:
- `frontend/src/lib/i18n-en.ts` for the interface;
- `backend/app/i18n.py` for server messages.

Two checks make sure nothing is left untranslated:

```bash
node tools/check_frontend_i18n.mjs                  # needs frontend/node_modules
cd backend && python ../tools/check_backend_i18n.py
```

## License

GPL-3.0, see [LICENSE](LICENSE).
