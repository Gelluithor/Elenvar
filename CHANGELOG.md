# Changelog

All notable changes to Elenvar are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows [Semantic Versioning](https://semver.org/).

## [1.1.1] – 2026-10-23

### Added
- Running behind an existing Traefik: `docker-compose.traefik.yml` and a step-by-step guide in the README.
- `ELENVAR_TRUSTED_PROXIES` setting that limits which reverse proxies are trusted to report the client IP address (used for sign-in rate limiting and the audit log).

### Changed
- Comments in `.env.example`, compose files and the Caddyfile, and the demo script output, are in English.

## [1.1.0] – 2026-10-23

### Added
- English language support across the whole interface, server error messages, monitoring events, device states and the audit log.
- Language switch in the sidebar and on the sign-in screen; the default language follows the browser.
- Notification language setting for e-mails and webhooks.
- Translation completeness checks for the frontend and backend (`tools/`).

### Changed
- The README is now entirely in English.
- Server logs are in English.
- Dates and times are formatted according to the selected language.

## [1.0.0] – 2026-10-22

Initial release.

### Live view
- Watch cameras from multiple NVRs at once in a 1, 4, 9 or 16 tile grid.
- Drag cameras into tiles, enlarge a tile, full-screen mode.
- Automatic quality selection: substream in the grid, main stream when enlarged.
- Optional H.265 to H.264 conversion for browsers without H.265 support.
- Automatic reconnection after an outage.

### Recordings
- Search recordings on the NVR and browse a day timeline that distinguishes continuous recording from events.
- Play from any point in time, skip ±30 s, pause.
- Download recording segments.

### Monitoring
- Periodic checks of NVR availability, camera status, disks (HDD/NAS) and clock drift.
- Mark which cameras are monitored; events and notifications on outages and recoveries.
- False-alarm protection (number of failures before notifying).
- Notifications by e-mail (SMTP) and webhook.
- Polling pauses when the NVR password is wrong, so the NVR account does not get locked.

### Device management
- Add Hikvision NVRs, DVRs and standalone IP cameras over ISAPI, with a connection test.
- Change camera stream parameters (codec, resolution, frame rate, bitrate, GOP) within the camera's capabilities.
- Restart devices remotely; overview of disks, firmware and device time.

### Security
- Mandatory two-factor authentication (TOTP) with 10 one-time recovery codes.
- Argon2id password hashing, server-side sessions, CSRF protection and origin checks.
- Sign-in rate limiting and temporary account lockout.
- Viewer, operator and administrator roles.
- Encrypted NVR and SMTP passwords that are never sent to the browser.
- Audit log of sign-ins, settings changes, playback and downloads.
- HTTPS via Caddy, strict security headers, containers with restricted privileges.

### Updates
- Watches GitHub for new releases and announces new versions.
- Installs updates directly from the web interface (updater service, confirmed with a password).

### Interface
- Light and dark theme; the "Watchful eye" logo in Night (dark theme) and Graphite (light theme) variants.
- Responsive layout for phones and tablets.

### Development
- Hikvision NVR simulator (ISAPI with digest authentication, RTSP with a camera-like picture and on-screen display).
- Demo with two NVRs and sample data (`dev/demo.sh`).

[1.1.1]: https://github.com/Gelluithor/Elenvar/releases/tag/v1.1.1
[1.1.0]: https://github.com/Gelluithor/Elenvar/releases/tag/v1.1.0
[1.0.0]: https://github.com/Gelluithor/Elenvar/releases/tag/v1.0.0
