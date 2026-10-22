<p align="center">
  <img src="frontend/public/logo.svg" width="96" height="96" alt="">
</p>

<h1 align="center">Elenvar</h1>

<p align="center">Centrální správa a monitoring kamerových systémů Hikvision v Dockeru.</p>

---

## Co umí

- **Živý obraz z více NVR najednou** – mřížka 1 / 4 / 9 / 16 kamer, přetahování kamer, celá obrazovka, automatická volba kvality (substream v mřížce, hlavní stream při zvětšení).
- **Záznamy** – vyhledání záznamů na NVR, časová osa dne (průběžný záznam / události), přehrávání od libovolného času, posun ±30 s, stahování úseků.
- **Monitoring** – pravidelná kontrola dostupnosti NVR, stavu každé kamery, disků (HDD/NAS) a odchylky času. Kamery lze označit jako *sledované*; při výpadku vznikne událost a odejde upozornění (e-mail, webhook). Ochrana před planými poplachy (počet selhání před upozorněním).
- **Nastavení zařízení** – parametry streamů kamer (kodek, rozlišení, snímková frekvence, datový tok, GOP) podle schopností kamery, restart NVR.
- **Zabezpečení** – povinné dvoufázové ověření (TOTP) se záložními kódy, role, audit všech důležitých akcí.

Podporovaná zařízení: Hikvision NVR (primárně), DVR a samostatné IP kamery s rozhraním ISAPI.

## Architektura

```
prohlížeč ──HTTPS──▶ Caddy ──▶ app (FastAPI + React UI) ──ISAPI (HTTP/Digest)──▶ NVR
                                   │
                                   └─WebSocket─▶ go2rtc ──RTSP──▶ NVR
```

| Služba   | Úloha |
|----------|-------|
| `caddy`  | Jediná služba vystavená ven. HTTPS (interní CA nebo Let's Encrypt), přesměrování HTTP → HTTPS. |
| `app`    | API, webové rozhraní, autentizace, monitoring na pozadí, proxy videa. Data v SQLite ve svazku `elenvar-data`. |
| `go2rtc` | Interní převod RTSP z NVR na MSE (fMP4) pro prohlížeč. Není dostupný mimo Docker síť, přihlašovací údaje ke kamerám drží jen v paměti (tmpfs). |

Video jde vždy přes aplikaci – prohlížeč se nikdy nepřipojuje přímo k NVR ani ke go2rtc a každé spojení se ověřuje přihlášením a rolí.

## Instalace

Požadavky: Docker s Compose v2 a síťová dostupnost NVR (HTTP port ISAPI a RTSP port) ze serveru.

```bash
git clone <repozitář> elenvar && cd elenvar
cp .env.example .env
# upravte ELENVAR_DOMAIN (adresa, pod kterou budete Elenvar otevírat)
docker compose up -d --build
docker compose logs app | grep -A3 "Vytvořen účet"   # heslo administrátora
```

Otevřete `https://<ELENVAR_DOMAIN>`, přihlaste se jako `admin`, nastavte si dvoufázové ověření a změňte heslo.

### HTTPS

- **Interní síť** (`ELENVAR_TLS=internal`): Caddy vystaví certifikát vlastní certifikační autoritou. Prohlížeč ji napoprvé označí jako nedůvěryhodnou. Pro odstranění varování naimportujte kořenový certifikát do počítačů:
  `docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt ./elenvar-root.crt`
- **Veřejná doména** (`ELENVAR_TLS=vas@email.cz`): Caddy získá certifikát Let's Encrypt automaticky (porty 80 a 443 musí být dostupné z internetu).
- `ELENVAR_DOMAIN` může obsahovat více adres oddělených čárkou, např. `elenvar.firma.lan, 192.168.1.20`.

### Konfigurace (`.env`)

| Proměnná | Výchozí | Popis |
|----------|---------|-------|
| `ELENVAR_DOMAIN` | `localhost` | Adresa(y) webu. |
| `ELENVAR_TLS` | `internal` | `internal` nebo e-mail pro Let's Encrypt. |
| `ELENVAR_HTTP_PORT` / `ELENVAR_HTTPS_PORT` | `80` / `443` | Porty na hostiteli. |
| `ELENVAR_ADMIN_USERNAME` | `admin` | Jméno prvního administrátora (jen při prvním startu). |
| `ELENVAR_ADMIN_PASSWORD` | *(vygeneruje se)* | Heslo prvního administrátora. |
| `ELENVAR_SESSION_IDLE_MINUTES` | `60` | Odhlášení po nečinnosti (sledování videa se počítá jako aktivita). |
| `ELENVAR_SESSION_MAX_HOURS` | `12` | Maximální délka přihlášení. |
| `ELENVAR_SECRET_KEY` | *(vygeneruje se do svazku)* | Klíč pro šifrování hesel k NVR a SMTP. |
| `ELENVAR_PLAYBACK_SOURCE` | `rtsp` | `ffmpeg` pro firmwary, kde přímé přehrávání záznamu nefunguje. |
| `TZ` | `Europe/Prague` | Časová zóna serveru. |

Ostatní nastavení (interval kontroly, upozornění, vynucení 2FA, retence) se mění ve webu v sekci **Nastavení**.

## Příprava NVR Hikvision

1. **Povolte ISAPI** – u novějších firmwarů *Konfigurace → Síť → Rozšířené → Integrační protokol → Povolit Hikvision-CGI / ISAPI*.
2. **Vytvořte samostatného uživatele** pro Elenvar (doporučeno). Oprávnění: vzdálený živý náhled a přehrávání; pro úpravu streamů a restart navíc nastavení parametrů a restart.
3. **Autentizace** – výchozí *digest* je v pořádku (Elenvar umí digest i basic).
4. **Kodek substreamu** – prohlížeče spolehlivě přehrávají **H.264**. H.265 umí Chrome/Edge/Safari jen s hardwarovou podporou, Firefox vůbec. Doporučujeme nastavit substream na H.264 (lze přímo v Elenvar: *Zařízení → NVR → Stream*). Alternativně zapněte u zařízení *Převádět video na H.264* (zatěžuje CPU serveru).
5. Ze serveru musí být dostupné porty HTTP (80/443) a RTSP (554) NVR.

> Elenvar při chybném hesle k NVR automaticky přestane zařízení dotazovat, aby Hikvision nezablokoval účet ani IP adresu serveru. Po opravě údajů se kontrola obnoví.

## Role

| Role | Oprávnění |
|------|-----------|
| Pozorovatel | Přehled, živý obraz, stav monitoringu a události. |
| Operátor | Navíc přehrávání a stahování záznamů, potvrzování událostí. |
| Administrátor | Vše včetně správy zařízení, uživatelů, nastavení a auditu. |

## Zabezpečení

- Hesla uživatelů: **Argon2id**, minimální délka 12 znaků.
- **Dvoufázové ověření TOTP** (standardně povinné) s ochranou proti opakovanému použití kódu a 10 jednorázovými záložními kódy (uložené jako hash).
- Relace na straně serveru, cookie `__Host-` s `HttpOnly`, `Secure`, `SameSite=Strict`; nový token po přihlášení (ochrana proti fixaci relace), časový limit nečinnosti i maximální délky.
- **CSRF** token pro každou měnící operaci a kontrola `Origin` (i u WebSocketů).
- Omezení pokusů o přihlášení (IP i účet), dočasné zablokování účtu po 5 chybách.
- Hesla k NVR a SMTP šifrovaná (Fernet/AES), nikdy se neposílají do prohlížeče; pozorovatelé a operátoři nevidí ani adresy zařízení.
- Přísné bezpečnostní hlavičky (CSP bez inline skriptů, HSTS, `X-Frame-Options`, `nosniff`, …).
- Aplikace běží pod neprivilegovaným uživatelem; všechny kontejnery mají zahozené capabilities a `no-new-privileges`, aplikace a go2rtc navíc read-only souborový systém.
- Auditní záznam přihlášení, změn nastavení, přehrávání a stahování záznamů.

Doporučení: Elenvar nevystavujte do internetu bez nutnosti – ideálně jen v interní síti nebo přes VPN.

## Zálohování a aktualizace

Všechna data (databáze a šifrovací klíč `secret.key`) jsou ve svazku `elenvar-data`. **Klíč zálohujte spolu s databází** – bez něj nelze dešifrovat uložená hesla k NVR.

```bash
# záloha
docker run --rm -v elenvar_elenvar-data:/data -v "$PWD":/backup alpine tar czf /backup/elenvar-backup.tgz -C /data .
# aktualizace
git pull && docker compose up -d --build
```

Ztracený přístup administrátora (telefon s 2FA): jiný administrátor může v sekci **Uživatelé** resetovat 2FA. Pokud žádný není, lze se přihlásit záložním kódem.

## Poznámky a omezení

- Časy záznamů se zobrazují v čase NVR (tak, jak je zařízení vrací), proto mějte čas na NVR nastavený přes NTP – Elenvar hlídá jeho odchylku.
- Zvuk se v prohlížeči nepřehrává (kamery obvykle používají G.711, které prohlížeče nepodporují).
- Stažené záznamy jsou v nativním formátu Hikvision (přehraje je např. VLC).
- Přehrávání záznamu běží v reálném čase (bez zrychlení).
- U analogových kanálů DVR se stav kamer nedá přes ISAPI spolehlivě zjistit – sleduje se jen dostupnost zařízení a disky.

## Demo

Vyzkoušení bez skutečného NVR – dvě simulovaná NVR s osmi kamerami a ukázkovými daty:

```bash
dev/demo.sh        # spustí demo na http://localhost:8080 (přihlášení: admin / Elenvar-Demo-2026)
dev/demo.sh down   # zastaví demo a smaže jeho data
```

Demo běží odděleně od ostré instalace, jen na tomto počítači a bez povinného 2FA.

## Vývoj

Součástí je simulátor Hikvision NVR (ISAPI s digest autentizací + RTSP s testovacím obrazem):

```bash
docker compose -f docker-compose.yml -f dev/docker-compose.dev.yml up -d --build
```

V aplikaci přidejte zařízení s adresou `mock-nvr`, uživatelem `admin` a heslem `p@ss:w/rd`. Stav simulátoru lze měnit z kontejneru aplikace, např. `http://mock-nvr/mock/set?offline=1,3&hdd=error`.

Frontend: React + TypeScript + Vite (`frontend/`), backend: Python FastAPI (`backend/`).

## Licence

GPL-3.0 – viz [LICENSE](LICENSE).
