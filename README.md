<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/brand/hero-dark.svg">
    <img src="docs/brand/hero-light.svg" width="860" alt="Elenvar">
  </picture>
</p>

<p align="center">
  Central management and monitoring for <a href="https://www.hikvision.com/">Hikvision</a> NVRs and cameras:
  live view, recordings and the health of every camera, self-hosted with one <code>docker compose up</code>.
</p>

<p align="center">
  <a href="https://github.com/Gelluithor/Elenvar/releases/latest"><img src="https://img.shields.io/github/v/release/Gelluithor/Elenvar?label=release&color=e3b449" alt="Latest release"></a>
  <a href="https://github.com/users/Gelluithor/packages/container/package/elenvar"><img src="https://img.shields.io/badge/docker-ghcr.io%2Fgelluithor%2Felenvar-2496ed?logo=docker&logoColor=white" alt="Docker image"></a>
  <img src="https://img.shields.io/badge/amd64%20%C2%B7%20arm64-supported-555" alt="amd64 and arm64">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/Gelluithor/Elenvar?color=555" alt="License"></a>
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#preparing-a-hikvision-nvr">Preparing an NVR</a> ·
  <a href="#running-behind-traefik">Traefik</a> ·
  <a href="#roles">Roles</a> ·
  <a href="#security">Security</a> ·
  <a href="#demo">Demo</a>
</p>

<p align="center">
  <img src="docs/demo.gif" width="900" alt="Elenvar in action: sign-in, the overview, live view from four cameras, an enlarged camera, device detail, the recordings timeline, monitoring and settings">
</p>

---

## How it fits together

```
 browser ──HTTPS──▶ Caddy or Traefik ──▶ Elenvar app (FastAPI + React UI, SQLite) ──▶ alerts: e-mail, webhook
                                            │    │
                    live view, playback ◀───┘    │ ISAPI (HTTP, digest): status, cameras, disks,
                    over WebSocket (MSE)         │ recordings, stream settings, restart
                         │                       ▼
                       go2rtc ───────RTSP───────▶ NVR / DVR / IP camera ──▶ cameras
                                                  ▲
       updater ──Docker API──▶ pulls a newer app image and restarts the app (only when an admin asks)
```

The browser never talks to an NVR or to go2rtc. Every live stream and every recording goes through the application,
which checks the user's session and role first. NVR passwords are stored encrypted, are never sent to the browser
and reach go2rtc only in memory. Only the reverse proxy is exposed to the network; go2rtc and the updater stay on
an internal Docker network.

## Features

### Watch your cameras

- **Live view from many NVRs at once:** a grid of 1, 4, 9 or 16 tiles with cameras from any device; drag a camera
  into a tile, double-click to enlarge it, or go full screen
- **Quality that fits:** the substream in the grid and the main stream when a camera is enlarged, chosen
  automatically or fixed by the user
- **Plays in the browser:** H.264 everywhere; for H.265 cameras a browser can't play, Elenvar can convert the
  video to H.264 per device
- **Reconnects by itself** after a camera or network outage

### Find what happened

- **Recordings timeline:** a day per camera with continuous recording and events (motion, alarms) told apart
- **Playback from any moment:** click the timeline, skip ±30 s, pause and continue
- **Downloads:** any recorded segment, straight from the NVR

### Know when something breaks

- **Monitoring of every device:** availability of each NVR, the state of each camera, disks (HDD and NAS) and the
  drift of the device clock, checked every minute by default
- **Cameras that must work:** mark which cameras are monitored; an outage and its end create an event and a
  notification by e-mail (SMTP) or webhook (Slack, Discord, Mattermost, Home Assistant…), in Czech or English
- **No false alarms:** a camera or device is reported only after a configurable number of failed checks
- **Safe with wrong passwords:** when an NVR rejects the login, Elenvar stops asking until the credentials are
  fixed, so Hikvision doesn't lock the account or the server's address
- **Overview and history:** current issues on the overview page, the event history with acknowledgements

### Manage the devices

- **NVRs, DVRs and IP cameras** over ISAPI, with a connection test before saving; cameras are discovered
  automatically
- **Stream settings:** codec, resolution, frame rate, bitrate and GOP of each camera, limited to what the camera
  supports
- **Remote restart** of a device, and its model, firmware, serial number and disks at a glance

### Stay secure

- **Two-factor sign-in:** TOTP is required by default, with ten one-time recovery codes
- **Roles:** viewer, operator and administrator
- **Audit log** of sign-ins, settings changes, playback, downloads and updates
- **Hardened by default:** Argon2id passwords, server-side sessions, CSRF protection, strict security headers and
  containers with dropped privileges ([details](#security))

### Keep it current

- **Updates from the web interface:** Elenvar checks GitHub for new releases, shows the release notes and installs
  the new version after the administrator confirms with a password
- **Czech and English:** the interface follows the browser language and can be switched at any time
- **Light and dark theme**, and a layout that works on phones and tablets

## Quick start

On any Linux server or computer with Docker and Compose v2 (amd64 or arm64). The server must reach the NVRs on
their HTTP and RTSP ports.

```bash
git clone https://github.com/Gelluithor/Elenvar.git && cd Elenvar
cp .env.example .env                                  # set ELENVAR_DOMAIN to the address you'll open Elenvar on
docker compose pull && docker compose up -d
docker compose logs app | grep -A3 "Administrator account"   # the first administrator's password
```

Open `https://<ELENVAR_DOMAIN>`, sign in as `admin`, set up two-factor authentication and choose a new password.
Then add your first NVR under *Devices*. To build the images yourself instead of pulling them, use
`docker compose up -d --build`.

### HTTPS

- **Local network** (`ELENVAR_TLS=internal`): Caddy issues a certificate from its own certificate authority, so
  browsers warn about it at first. To remove the warning, import the root certificate on your computers:
  `docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt ./elenvar-root.crt`
- **Public domain** (`ELENVAR_TLS=you@example.com`): Caddy obtains a Let's Encrypt certificate automatically.
  Ports 80 and 443 must be reachable from the internet.
- `ELENVAR_DOMAIN` may list several addresses separated by commas, e.g. `elenvar.example.lan, 192.168.1.20`.

### Running behind Traefik

If you already run [Traefik](https://traefik.io/), use it instead of the bundled Caddy.
`docker-compose.traefik.yml` turns Caddy off, connects the `app` service to Traefik's network and adds the router
labels; go2rtc and the updater stay on Elenvar's internal network.

1. Find the Docker network Traefik uses for its services (e.g. `traefik` or `proxy`): `docker network ls`
2. Add the Traefik settings to `.env`:
   ```bash
   ELENVAR_TRAEFIK_HOST=cameras.example.com      # host name Traefik routes to Elenvar
   ELENVAR_TRAEFIK_NETWORK=traefik               # Traefik's Docker network
   ELENVAR_TRAEFIK_ENTRYPOINT=websecure          # your HTTPS entrypoint
   ELENVAR_TRAEFIK_CERTRESOLVER=letsencrypt      # your certificate resolver; leave empty if you don't use one
   ELENVAR_TRUSTED_PROXIES=172.18.0.2            # Traefik's IP address, see step 3
   ```
3. Set `ELENVAR_TRUSTED_PROXIES` to Traefik's address, so that Elenvar trusts the client IP only from Traefik
   (it is used for sign-in rate limiting and in the audit log). Without it, any other container on the Traefik
   network could fake its address.
   ```bash
   docker inspect -f '{{(index .NetworkSettings.Networks "traefik").IPAddress}}' traefik
   ```
   A container's IP can change when it is recreated: give Traefik a fixed address in its compose file
   (`ipv4_address`), or use the network range (e.g. `172.18.0.0/16`), which trusts every container on that
   network.
4. Start Elenvar with both compose files:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.traefik.yml up -d
   ```
   With `COMPOSE_FILE=docker-compose.yml:docker-compose.traefik.yml` in `.env`, a plain `docker compose up -d` uses
   both files. Updates from the web interface keep using them too.

Traefik must serve Elenvar over **HTTPS** (the session cookie is `Secure`) and pass the **`Host` header** unchanged,
which it does by default; Elenvar uses it to check where requests come from. WebSockets for video work out of the
box. Tested with Traefik v3.7.

### Configuration

All settings are optional (`.env.example`). Everything else – check interval, failure threshold, notifications and
their language, enforcing 2FA, data retention and update checks – is set in the web interface under *Settings*.

| Variable | Meaning |
|---|---|
| `ELENVAR_DOMAIN` | address(es) of the web interface (default `localhost`) |
| `ELENVAR_TLS` | `internal` (default) or an e-mail address for Let's Encrypt |
| `ELENVAR_HTTP_PORT` / `ELENVAR_HTTPS_PORT` | ports on the host (default `80` / `443`) |
| `ELENVAR_ADMIN_USERNAME` | name of the first administrator, first start only (default `admin`) |
| `ELENVAR_ADMIN_PASSWORD` | password of the first administrator; empty = generated and printed to the log |
| `ELENVAR_SESSION_IDLE_MINUTES` | sign-out after inactivity; watching video counts as activity (default `60`) |
| `ELENVAR_SESSION_MAX_HOURS` | maximum session length (default `12`) |
| `ELENVAR_SECRET_KEY` | key that encrypts NVR and SMTP passwords; empty = generated into the data volume |
| `ELENVAR_PLAYBACK_SOURCE` | `rtsp` (default) or `ffmpeg` for firmware where direct playback doesn't work |
| `ELENVAR_TRUSTED_PROXIES` | proxies trusted to report the client IP, IPs or CIDR ranges (default `*`, safe with the bundled Caddy) |
| `ELENVAR_TRAEFIK_*` | host, network, entrypoint and certificate resolver, see [Running behind Traefik](#running-behind-traefik) |
| `ELENVAR_IMAGE`, `ELENVAR_UPDATER_IMAGE`, `ELENVAR_IMAGE_TAG` | where images and updates come from (default `ghcr.io/gelluithor/…`, `latest`) |
| `ELENVAR_UPDATE_REPO` | GitHub repository checked for new releases (default `Gelluithor/Elenvar`) |
| `TZ` | server time zone (default `Europe/Prague`) |

Data live in the volume `elenvar-data`: the SQLite database and the encryption key `secret.key`.

## Preparing a Hikvision NVR

1. **Enable ISAPI.** On newer firmware: *Configuration → Network → Advanced → Integration Protocol → Enable
   Hikvision-CGI / ISAPI*.
2. **Create a dedicated user** for Elenvar. It needs remote live view and playback; to change streams and restart
   the device it also needs parameter configuration and reboot.
3. **Authentication:** the default *digest* is fine; Elenvar supports digest and basic.
4. **H.264 substream:** browsers reliably play H.264. H.265 works in Chrome, Edge and Safari only with hardware
   support and not at all in Firefox. Set the substream to H.264 – directly in Elenvar under
   *Devices → device → Stream* – or turn on *Convert video to H.264* for the device (uses server CPU).
5. **Network:** the server must reach the NVR's HTTP (80/443) and RTSP (554) ports.

Elenvar works with NVRs, DVRs and standalone Hikvision IP cameras that offer ISAPI. For analog DVR channels the
camera state can't be read reliably over ISAPI, so only device availability and disks are monitored there.

## Roles

| Role | What it allows |
|---|---|
| viewer | overview, live view, monitoring and events |
| operator | everything a viewer can, plus playing and downloading recordings and acknowledging events |
| admin | everything, including devices, stream settings, restarts, users, settings, the audit log and updates |

Users who forget their phone can sign in with a recovery code; an administrator can also reset their 2FA under
*Users*. The last active administrator can't be removed or demoted.

## Updates

Every 6 hours, or when you click *Check*, Elenvar looks for a new release on GitHub. A new version shows up as an
event, a notification and a dot next to *Settings*. *Settings → Software update → Update now* asks for your password,
pulls the new image, restarts the app and reloads the page.

Only the `updater` service has access to Docker. It can do exactly one thing – pull a newer `app` image and
restart the `app` container with the same configuration – it is reachable only on the internal network and only
with a shared token. Remove it from `docker-compose.yml` if you don't want updates from the web; then update with
`git pull && docker compose pull && docker compose up -d`.

An update from the web replaces the application image only. When a release changes the compose files (for example
a new go2rtc version), the release notes say so and the files are updated with `git pull`.

## Backup and migration

Back up the volume `elenvar-data`. It holds the database and `secret.key`; **keep the key with the database**,
without it the stored NVR passwords can't be decrypted.

```bash
docker run --rm -v elenvar_elenvar-data:/data -v "$PWD":/backup alpine tar czf /backup/elenvar-backup.tgz -C /data .
```

To move Elenvar to another server, restore the archive into the volume there before the first start.

## Security

- Passwords: Argon2id, at least 12 characters. Two-factor sign-in (TOTP) is required by default; codes can't be
  reused, and the ten recovery codes are stored as hashes.
- Sessions live on the server, in a `__Host-` cookie (`HttpOnly`, `Secure`, `SameSite=Strict`), get a new token
  after sign-in and have an idle timeout and a maximum lifetime. A password change signs out other sessions.
- Every state-changing request needs a CSRF token and a matching `Origin`, WebSockets included.
- Sign-in is rate limited per address, and an account is locked for 15 minutes after 5 failed attempts; the
  response time doesn't reveal which accounts exist.
- NVR and SMTP passwords are encrypted (Fernet) and never sent to the browser; viewers and operators don't even
  see device addresses.
- Content-Security-Policy without inline scripts, HSTS, `X-Frame-Options: DENY`, `nosniff`, `no-referrer`, no
  caching of API responses, no public OpenAPI.
- The app runs as an unprivileged user; all containers drop capabilities and use `no-new-privileges`; the app and
  go2rtc have read-only file systems.

Known limitations: the `updater` container has the Docker socket, which is equivalent to root on the server – it
only accepts one fixed command with a token from the internal network, but remove it if that's not acceptable. The
database itself isn't encrypted (the NVR and SMTP passwords in it are). Recordings are downloaded in Hikvision's
native format (VLC plays it), playback runs in real time, audio isn't played in the browser, and recording times are
shown in the NVR's clock, so keep the NVRs on NTP – Elenvar watches the drift. Don't expose Elenvar to the internet
unless you have to; a LAN or a VPN is the better place for it.

## Demo

Try Elenvar without real hardware – two simulated NVRs with eight cameras and sample data:

```bash
dev/demo.sh        # http://localhost:8080, sign in as admin / Elenvar-Demo-2026
dev/demo.sh down   # stop the demo and delete its data
```

The demo runs separately from a real installation, only on your computer, and without mandatory 2FA.

## Repository layout

```
backend/app/               FastAPI app: API, ISAPI client, monitoring, video proxy, translations (i18n.py)
frontend/src/              React + TypeScript web interface (Vite), English translation in lib/i18n-en.ts
updater/                   the updater service
dev/                       Hikvision NVR simulator (ISAPI + RTSP) and the demo
tools/                     translation completeness checks
docker-compose.yml         app, go2rtc, updater and Caddy
docker-compose.traefik.yml running behind Traefik
```

## Development

```bash
docker compose -f docker-compose.yml -f dev/docker-compose.dev.yml up -d --build   # with the NVR simulator
```

In the app, add a device with the address `mock-nvr`, user `admin` and password `p@ss:w/rd`. The simulator can be
switched into trouble from the app container, e.g. `http://mock-nvr/mock/set?offline=1,3&hdd=error`.

Czech is the source language in the code; the English translations are checked for completeness:

```bash
node tools/check_frontend_i18n.mjs                   # needs frontend/node_modules
cd backend && python ../tools/check_backend_i18n.py
```

Releases: raise `VERSION`, add an entry to `CHANGELOG.md` and publish a GitHub release with the tag `v<version>`.
GitHub Actions builds `ghcr.io/<owner>/elenvar` and `elenvar-updater` for amd64 and arm64, tagged `<version>` and
`latest`.

## License

GPL-3.0, see [LICENSE](LICENSE).
