"""Překlad hlášek pro uživatele (čeština je zdrojový jazyk, angličtina překlad).

Kód vrací české texty; podle jazyka požadavku se při odeslání přeloží. Katalog
obsahuje šablony s proměnnými ({name}), takže se přeloží i hlášky s názvy zařízení,
čísly apod. Proměnné části se překládají rekurzivně (např. chyba zařízení uvnitř
hlášky o výpadku).
"""

from __future__ import annotations

import re
from contextvars import ContextVar
from collections.abc import Mapping

LANGUAGES = ("cs", "en")
DEFAULT_LANGUAGE = "cs"
LANGUAGE_HEADER = "x-elenvar-language"

_current: ContextVar[str] = ContextVar("elenvar_language", default=DEFAULT_LANGUAGE)

CATALOG: dict[str, str] = {
    # --- přihlášení a účty ---------------------------------------------------
    "Příliš mnoho pokusů. Zkuste to prosím později.": "Too many attempts. Please try again later.",
    "Pokus o přihlášení k zablokovanému účtu": "Sign-in attempt to a locked account",
    "Účet je kvůli opakovaným neúspěšným pokusům dočasně zablokován. Zkuste to za {minutes} min.":
        "The account is temporarily locked after repeated failed attempts. Try again in {minutes} min.",
    "Neplatné přihlašovací údaje": "Invalid credentials",
    "Neplatné uživatelské jméno nebo heslo.": "Invalid username or password.",
    "Přihlášení heslem (2FA není vyžadováno)": "Signed in with password (2FA not required)",
    "Heslo ověřeno, čeká se na 2FA": "Password verified, waiting for 2FA",
    "Ověření kódem teď není požadováno.": "A verification code is not required right now.",
    "Neplatný ověřovací kód": "Invalid verification code",
    "Příliš mnoho neplatných kódů. Přihlaste se prosím znovu.": "Too many invalid codes. Please sign in again.",
    "Neplatný nebo již použitý kód.": "Invalid or already used code.",
    "Přihlášení s 2FA": "Signed in with 2FA",
    "Přihlášení recovery kódem": "Signed in with a recovery code",
    "Nejprve dokončete přihlášení.": "Finish signing in first.",
    "Dvoufázové ověření je již zapnuté.": "Two-factor authentication is already enabled.",
    "Nejprve spusťte nastavení dvoufázového ověření.": "Start the two-factor authentication setup first.",
    "Kód nesouhlasí. Zkontrolujte, že má telefon správný čas, a zadejte aktuální kód.":
        "The code doesn't match. Make sure your phone's clock is correct and enter the current code.",
    "Zapnuto dvoufázové ověření": "Two-factor authentication enabled",
    "Přihlášení po nastavení 2FA": "Signed in after setting up 2FA",
    "Dvoufázové ověření je v této instalaci povinné.": "Two-factor authentication is required in this installation.",
    "Dvoufázové ověření není zapnuté.": "Two-factor authentication is not enabled.",
    "Neplatné heslo nebo kód": "Invalid password or code",
    "Neplatné heslo nebo ověřovací kód.": "Invalid password or verification code.",
    "Vypnuto dvoufázové ověření": "Two-factor authentication disabled",
    "Vygenerovány nové recovery kódy": "New recovery codes generated",
    "Nejste přihlášeni.": "You are not signed in.",
    "Neplatný CSRF token.": "Invalid CSRF token.",
    "Neplatný CSRF token. Obnovte stránku.": "Invalid CSRF token. Reload the page.",
    "Odhlášení": "Signed out",
    "Neplatné současné heslo": "Invalid current password",
    "Současné heslo není správné.": "The current password is incorrect.",
    "Nové heslo musí být jiné než současné.": "The new password must differ from the current one.",
    "Změna hesla (ostatní relace odhlášeny)": "Password changed (other sessions signed out)",
    "Relace neexistuje.": "Session does not exist.",
    "Aktuální relaci ukončete odhlášením.": "End the current session by signing out.",
    "Ukončena relace z {ip}": "Session from {ip} ended",
    "Přihlášení již bylo dokončeno.": "Sign-in has already been completed.",
    "Nejprve si změňte heslo.": "Change your password first.",
    "K této akci nemáte oprávnění.": "You don't have permission for this action.",
    "Heslo musí mít alespoň {count} znaků.": "The password must be at least {count} characters long.",
    "Heslo může mít nejvýše {count} znaků.": "The password can be at most {count} characters long.",
    "Heslo nesmí obsahovat uživatelské jméno.": "The password must not contain the username.",
    "Heslo je příliš jednoduché.": "The password is too simple.",
    "Nelze dešifrovat uložený údaj – změnil se šifrovací klíč (secret.key)?":
        "Cannot decrypt stored data – has the encryption key (secret.key) changed?",
    # --- uživatelé -----------------------------------------------------------
    "Uživatel s tímto jménem již existuje.": "A user with this name already exists.",
    "Vytvořen uživatel {username} (role {role})": "User {username} created (role {role})",
    "Uživatel neexistuje.": "User does not exist.",
    "Vlastní roli nelze změnit.": "You can't change your own role.",
    "Musí zůstat alespoň jeden aktivní administrátor.": "At least one active administrator must remain.",
    "Vlastní účet nelze deaktivovat.": "You can't deactivate your own account.",
    "Vlastní heslo změňte v nastavení účtu.": "Change your own password in your account settings.",
    "Vlastní 2FA spravujte v nastavení účtu.": "Manage your own 2FA in your account settings.",
    "Vlastní účet nelze smazat.": "You can't delete your own account.",
    "Smazán uživatel {username}": "User {username} deleted",
    "Uživatel {username}: {changes}": "User {username}: {changes}",
    "role {old} → {new}": "role {old} → {new}",
    "aktivován": "activated",
    "deaktivován": "deactivated",
    "jméno": "name",
    "reset hesla": "password reset",
    "reset 2FA": "2FA reset",
    "odblokován": "unlocked",
    # --- zařízení a kamery ---------------------------------------------------
    "Zadejte IP adresu nebo název hostitele (bez http:// a cesty).":
        "Enter an IP address or host name (without http:// or a path).",
    "Zařízení neexistuje.": "Device does not exist.",
    "Přidáno zařízení {name} ({host})": "Device {name} ({host}) added",
    "Příliš mnoho testů připojení, zkuste to za chvíli.": "Too many connection tests, try again in a moment.",
    "Zadejte heslo.": "Enter the password.",
    "Upraveno zařízení {name}: {changes}": "Device {name} updated: {changes}",
    "heslo": "password",
    "Smazáno zařízení {name}": "Device {name} deleted",
    "Restart {name} selhal: {error}": "Restart of {name} failed: {error}",
    "Restart zařízení {name}": "Device {name} restarted",
    "Neplatný kanál.": "Invalid channel.",
    "Nebyly zadány žádné změny.": "No changes were specified.",
    "{name} stream {stream}: změna selhala ({error})": "{name} stream {stream}: change failed ({error})",
    "Zařízení nepodporuje parametr {field}.": "The device does not support parameter {field}.",
    "Hodnota {field} musí být v rozsahu {low}–{high}.": "{field} must be between {low} and {high}.",
    "Hodnota {value} pro {field} není podporována.": "Value {value} is not supported for {field}.",
    "Neplatná hodnota pro {field}.": "Invalid value for {field}.",
    "Rozlišení je nutné změnit současně (šířka i výška).": "Width and height must be changed together.",
    "Kamera neexistuje.": "Camera does not exist.",
    "{device} / {camera}: monitoring {state}": "{device} / {camera}: monitoring {state}",
    "zapnut": "enabled",
    "vypnut": "disabled",
    "Zařízení není dostupné.": "The device is not available.",
    "Zařízení je vypnuté.": "The device is disabled.",
    # --- záznamy -------------------------------------------------------------
    "Neplatný čas.": "Invalid time.",
    "Neplatné datum.": "Invalid date.",
    "Neplatný časový rozsah.": "Invalid time range.",
    "Záznam v zadaném čase nebyl nalezen.": "No recording was found at the given time.",
    "{device} / {camera}: od {start}": "{device} / {camera}: from {start}",
    "Najednou lze přehrávat nejvýše {count} záznamy.": "At most {count} recordings can be played at once.",
    # --- události a přehled --------------------------------------------------
    "Událost neexistuje.": "Event does not exist.",
    "Potvrzeno {count} událostí": "{count} events acknowledged",
    "Zařízení je nedostupné": "The device is unavailable",
    "Kamera je offline": "Camera is offline",
    "Kamera je offline – {detail}": "Camera is offline – {detail}",
    "Čas zařízení se liší o {seconds} s": "Device time differs by {seconds} s",
    # --- nastavení -----------------------------------------------------------
    "URL webhooku musí začínat http:// nebo https://": "The webhook URL must start with http:// or https://",
    "Hodnota nesmí obsahovat zalomení řádku": "The value must not contain line breaks",
    "Před vynucením 2FA si nejprve zapněte dvoufázové ověření u svého účtu.":
        "Before enforcing 2FA, enable two-factor authentication on your own account.",
    "Změněna nastavení: {names}": "Settings changed: {names}",
    "Není zapnutý žádný kanál upozornění.": "No notification channel is enabled.",
    "[Elenvar] Testovací upozornění": "[Elenvar] Test notification",
    "Toto je testovací upozornění odeslané uživatelem {username}.": "This is a test notification sent by {username}.",
    "Není zadán příjemce e-mailu.": "No e-mail recipient is specified.",
    "Webhook vrátil HTTP {code}": "The webhook returned HTTP {code}",
    "E-mail: {error}": "E-mail: {error}",
    "Webhook: {error}": "Webhook: {error}",
    # --- aktualizace ---------------------------------------------------------
    "Heslo není správné.": "The password is incorrect.",
    "Neplatné heslo při potvrzení aktualizace": "Invalid password when confirming the update",
    "Spuštění aktualizace selhalo: {error}": "Starting the update failed: {error}",
    "Spuštěna aktualizace z {current} na {target}": "Update started from {current} to {target}",
    "nejnovější verzi": "the latest version",
    "Repozitář s vydáními nebyl nalezen.": "The release repository was not found.",
    "Služba GitHub dočasně omezila dotazy, zkuste to později.": "GitHub is temporarily limiting requests, try again later.",
    "Neočekávaná odpověď serveru s vydáními.": "Unexpected response from the release server.",
    "Server s vydáními není dostupný. Zkontrolujte připojení serveru k internetu.":
        "The release server is unreachable. Check the server's internet connection.",
    "Server s vydáními vrátil neplatnou odpověď.": "The release server returned an invalid response.",
    "K dispozici je nová verze Elenvar {version}": "A new version of Elenvar is available: {version}",
    "Služba pro aktualizace není nainstalovaná.": "The update service is not installed.",
    "Služba pro aktualizace neodpovídá.": "The update service is not responding.",
    "Služba pro aktualizace vrátila chybu {code}.": "The update service returned error {code}.",
    # zprávy služby updater
    "Hledám aplikaci": "Locating the application",
    "Stahuji novou verzi": "Downloading the new version",
    "Restartuji aplikaci": "Restarting the application",
    "Připravuji": "Preparing",
    "Elenvar je aktuální.": "Elenvar is up to date.",
    "Aktualizace byla nainstalována.": "The update was installed.",
    "Aktualizace už probíhá.": "An update is already in progress.",
    "Obraz aplikace je aktuální, restart není potřeba.": "The application image is up to date, no restart needed.",
    "Chyba: {error}": "Error: {error}",
    "Updater neběží jako součást docker compose projektu.": "The updater is not running as part of a docker compose project.",
    "Kontejner aplikace nebyl nalezen.": "The application container was not found.",
    "Kontejner aplikace nemá údaje docker compose.": "The application container has no docker compose metadata.",
    "Adresář projektu není připojený do updateru (/project).": "The project directory is not mounted into the updater (/project).",
    "Neplatný adresář projektu.": "Invalid project directory.",
    "Konfigurační soubor {path} leží mimo adresář projektu.": "Configuration file {path} is outside the project directory.",
    "Konfigurační soubor {path} nebyl nalezen.": "Configuration file {path} was not found.",
    "Aktualizace trvá příliš dlouho, byla přerušena.": "The update is taking too long and was aborted.",
    "Příkaz docker compose skončil chybou – podrobnosti jsou v záznamu.": "The docker compose command failed – see the log for details.",
    "Objekt {ref} neexistuje.": "Object {ref} does not exist.",
    "Příkaz {command} selhal.": "Command {command} failed.",
    # --- video ---------------------------------------------------------------
    "Služba pro video není dostupná.": "The video service is not available.",
    "Služba pro video (go2rtc) není dostupná.": "The video service (go2rtc) is not available.",
    "Nepodařilo se připravit video stream.": "Failed to prepare the video stream.",
    "Relace vypršela. Přihlaste se znovu.": "Your session has expired. Please sign in again.",
    # --- obecné --------------------------------------------------------------
    "Požadavek z cizího původu byl odmítnut.": "Cross-origin request rejected.",
    "Neznámý požadavek.": "Unknown request.",
    "Frontend není sestaven.": "The frontend is not built.",
    # --- komunikace s NVR (ISAPI) -------------------------------------------
    "Odpověď zařízení je příliš velká.": "The device response is too large.",
    "Zařízení vrátilo neplatnou XML odpověď.": "The device returned an invalid XML response.",
    "Zařízení neodpovídá (vypršel časový limit).": "The device is not responding (timed out).",
    "Chyba TLS při připojení k zařízení (zkontrolujte HTTPS a ověřování certifikátu).":
        "TLS error while connecting to the device (check HTTPS and certificate verification).",
    "Nelze se připojit k zařízení.": "Cannot connect to the device.",
    "Chyba komunikace se zařízením ({error}).": "Communication error with the device ({error}).",
    "Zařízení odmítlo přihlášení – zkontrolujte jméno a heslo (účet může být dočasně zablokován).":
        "The device rejected the login – check the username and password (the account may be temporarily locked).",
    "Zařízení tuto funkci nepodporuje.": "The device does not support this feature.",
    "Zařízení odmítlo požadavek ({detail}).": "The device rejected the request ({detail}).",
    "přístup zamítnut": "access denied",
    "Zařízení vrátilo chybu HTTP {code}.": "The device returned HTTP error {code}.",
    "Zařízení vrátilo chybu HTTP {code} ({detail}).": "The device returned HTTP error {code} ({detail}).",
    "Zařízení odmítlo změnu ({detail}).": "The device rejected the change ({detail}).",
    "kód {code}": "code {code}",
    "Zařízení nevrátilo obrázek.": "The device did not return an image.",
    "Snímek je příliš velký.": "The snapshot is too large.",
    "Stream nemá video parametry.": "The stream has no video parameters.",
    "Neznámý parametr {field}.": "Unknown parameter {field}.",
    # stav kanálů NVR
    "Připojeno": "Connected",
    "Připojování": "Connecting",
    "Síť nedostupná": "Network unreachable",
    "Překročena kapacita": "Capacity exceeded",
    "Překročena šířka pásma": "Bandwidth exceeded",
    "Selhal stream z kamery": "Camera stream failed",
    "Účet na kameře zablokován": "Camera account locked",
    "Neplatné jméno pro kameru": "Invalid camera username",
    "Neplatné heslo pro kameru": "Invalid camera password",
    "Chybné přihlašovací údaje kamery": "Wrong camera credentials",
    "Kamera neexistuje": "Camera does not exist",
    "Neznámá chyba": "Unknown error",
    "Nepodporováno": "Not supported",
    # úložiště
    "{name} – stav „{status}“": "{name} – status “{status}”",
    "neznámý": "unknown",
    "Zařízení nemá žádný disk – nenahrává se": "The device has no disk – nothing is being recorded",
    # --- události monitoringu -----------------------------------------------
    "{device}: zařízení odmítlo přihlášení – dotazování je pozastaveno do opravy údajů":
        "{device}: the device rejected the login – polling is paused until the credentials are fixed",
    "{device} je nedostupný: {error}": "{device} is unavailable: {error}",
    "{device} je opět dostupný": "{device} is available again",
    "{device}: čas zařízení se liší o {seconds} s – zkontrolujte NTP": "{device}: device time differs by {seconds} s – check NTP",
    "{device}: čas zařízení je opět v pořádku": "{device}: device time is correct again",
    "{device}: nalezena kamera „{camera}“ (kanál {channel})": "{device}: camera “{camera}” found (channel {channel})",
    "{device}: kamera „{camera}“ (kanál {channel}) je offline": "{device}: camera “{camera}” (channel {channel}) is offline",
    "{device}: kamera „{camera}“ (kanál {channel}) je offline ({detail})":
        "{device}: camera “{camera}” (channel {channel}) is offline ({detail})",
    "{device}: kamera „{camera}“ (kanál {channel}) je opět online": "{device}: camera “{camera}” (channel {channel}) is online again",
    "{device}: kamera „{camera}“ (kanál {channel}) byla odebrána z konfigurace NVR":
        "{device}: camera “{camera}” (channel {channel}) was removed from the NVR configuration",
    "{device}: problém s úložištěm – {problem}": "{device}: storage problem – {problem}",
    "{device}: úložiště v pořádku ({disk})": "{device}: storage OK ({disk})",
    # --- texty upozornění ----------------------------------------------------
    "Zařízení": "Device",
    "Čas": "Time",
    "Závažnost": "Severity",
    "kritické": "critical",
    "varování": "warning",
    "informace": "info",
    "[Elenvar] K dispozici je verze {version}": "[Elenvar] Version {version} is available",
    "Nainstalovaná verze": "Installed version",
    "Nová verze": "New version",
}


def _compile(template: str) -> re.Pattern[str]:
    parts = re.split(r"\{(\w+)\}", template)
    pattern = ""
    for index, part in enumerate(parts):
        pattern += f"(?P<{part}>.+?)" if index % 2 else re.escape(part)
    return re.compile(pattern, re.S)


_EXACT = {cs: en for cs, en in CATALOG.items() if "{" not in cs}
# Konkrétnější šablony (více pevného textu) se zkoušejí dřív.
_PATTERNS = sorted(
    ((_compile(cs), en, len(re.sub(r"\{\w+\}", "", cs))) for cs, en in CATALOG.items() if "{" in cs),
    key=lambda item: -item[2],
)


def normalize(language: str | None) -> str:
    value = (language or "").strip().lower()[:2]
    return value if value in LANGUAGES else DEFAULT_LANGUAGE


def set_language(language: str | None) -> None:
    _current.set(normalize(language))


def current_language() -> str:
    return _current.get()


def language_from_headers(headers: Mapping[str, str]) -> str:
    explicit = headers.get(LANGUAGE_HEADER)
    if explicit:
        return normalize(explicit)
    accept = headers.get("accept-language", "")
    for item in accept.split(","):
        code = item.split(";")[0].strip().lower()[:2]
        if code in ("cs", "sk"):
            return "cs"
        if code:
            return "en"
    return DEFAULT_LANGUAGE


def tr(text: str | None, language: str | None = None, _depth: int = 0) -> str:
    """Přeloží českou hlášku do zvoleného jazyka (výchozí: jazyk aktuálního požadavku)."""
    if not text:
        return text or ""
    lang = normalize(language) if language else current_language()
    if lang == "cs" or _depth > 4:
        return text
    exact = _EXACT.get(text)
    if exact is not None:
        return exact
    for pattern, english, _ in _PATTERNS:
        match = pattern.fullmatch(text)
        if match:
            params = {key: tr(value, lang, _depth + 1) for key, value in match.groupdict().items()}
            return english.format(**params)
    # Seznam změn oddělený čárkami (např. v auditu) – přeložit po částech.
    if ", " in text:
        return ", ".join(tr(part, lang, _depth + 1) for part in text.split(", "))
    return text


def tr_lines(lines: list[str], language: str | None = None) -> list[str]:
    return [tr(line, language) for line in lines]
