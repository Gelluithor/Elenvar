# Changelog

Všechny podstatné změny projektu Elenvar. Formát vychází z [Keep a Changelog](https://keepachangelog.com/cs/1.1.0/), verze se řídí [sémantickým verzováním](https://semver.org/lang/cs/).

## [1.1.0] – 2026-10-23

### Přidáno
- Angličtina: celé rozhraní, chybové hlášky serveru, události monitoringu, stavy zařízení i auditní záznam jsou dostupné česky i anglicky.
- Přepínač jazyka v postranním panelu a na přihlašovací obrazovce; výchozí jazyk podle prohlížeče.
- Volba jazyka upozornění (e-mail, webhook) v Nastavení.
- Kontroly úplnosti překladu pro frontend i backend (`tools/`).

### Změněno
- README je kompletně v angličtině.
- Logy serveru jsou v angličtině.
- Formát data a času se řídí zvoleným jazykem.

## [1.0.0] – 2026-10-22

První vydání.

### Živý obraz
- Sledování kamer z více NVR najednou v mřížce 1, 4, 9 nebo 16 oken.
- Přetažení kamery do okna, zvětšení na celé okno, režim celé obrazovky.
- Automatická volba kvality: substream v mřížce, hlavní stream při zvětšení.
- Volitelný převod H.265 na H.264 pro prohlížeče bez podpory H.265.
- Automatické obnovení spojení po výpadku.

### Záznamy
- Vyhledání záznamů na NVR a časová osa dne s rozlišením průběžného záznamu a událostí.
- Přehrávání od libovolného času, posun o ±30 s, pozastavení.
- Stažení úseku záznamu.

### Monitoring
- Pravidelná kontrola dostupnosti NVR, stavu kamer, disků (HDD/NAS) a odchylky času.
- Označení kamer, které se mají hlídat; událost a upozornění při výpadku i obnovení.
- Ochrana před planými poplachy (počet selhání před upozorněním).
- Upozornění e-mailem (SMTP) a webhookem.
- Při chybném hesle k NVR se dotazování pozastaví, aby se účet na NVR nezablokoval.

### Správa zařízení
- Přidání NVR, DVR i samostatných IP kamer Hikvision přes ISAPI, test připojení.
- Úprava parametrů streamů kamer (kodek, rozlišení, snímková frekvence, datový tok, GOP) podle schopností kamery.
- Restart zařízení na dálku, přehled disků, firmwaru a času zařízení.

### Zabezpečení
- Povinné dvoufázové ověření (TOTP) s 10 jednorázovými záložními kódy.
- Hesla hashovaná Argon2id, relace na straně serveru, ochrana CSRF a kontrola původu požadavků.
- Omezení pokusů o přihlášení a dočasné zablokování účtu.
- Role pozorovatel, operátor a administrátor.
- Šifrovaná hesla k NVR a SMTP, která se nikdy neposílají do prohlížeče.
- Auditní záznam přihlášení, změn nastavení, přehrávání a stahování záznamů.
- HTTPS přes Caddy, přísné bezpečnostní hlavičky, kontejnery s omezenými oprávněními.

### Aktualizace
- Sledování nových vydání na GitHubu, upozornění na novou verzi.
- Instalace aktualizace přímo z webového rozhraní (služba updater, potvrzení heslem).

### Rozhraní
- Světlý a tmavý motiv, logo „Bdělé oko“ v provedení Noc (tmavý motiv) a Grafit (světlý motiv).
- Responzivní rozvržení pro telefony a tablety.

### Pro vývoj
- Simulátor Hikvision NVR (ISAPI s digest autentizací, RTSP s obrazem kamery a OSD).
- Demo se dvěma NVR a ukázkovými daty (`dev/demo.sh`).

[1.1.0]: https://github.com/Gelluithor/Elenvar/releases/tag/v1.1.0
[1.0.0]: https://github.com/Gelluithor/Elenvar/releases/tag/v1.0.0
