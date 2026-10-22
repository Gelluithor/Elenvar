import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { ChevronDown, ExternalLink, RefreshCw } from "lucide-react";
import { api, errorMessage } from "../lib/api";
import { formatDateTime, formatRelative } from "../lib/format";
import { Logo } from "./Logo";
import { Alert, Modal, Spinner, useToast } from "./ui";
import { t } from "../lib/i18n";

interface Release {
  version: string;
  name: string;
  published_at: string | null;
  notes: string;
  url: string;
  prerelease: boolean;
}

interface UpdaterStatus {
  state: "idle" | "running" | "done" | "failed";
  phase: string;
  result: "" | "updated" | "current";
  message: string;
  log: string[];
}

export interface UpdateInfo {
  current: string;
  latest: Release | null;
  update_available: boolean;
  checked_at: string | null;
  error: string;
  repo: string;
  updater_available: boolean;
  updater_error: string;
  updater: UpdaterStatus | null;
}

/** Jednoduché a bezpečné zobrazení poznámek k vydání (Markdown bez HTML). */
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={i}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={i}>{part.slice(1, -1)}</code>;
    return part;
  });
}

function ReleaseNotes({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length) {
      const items = list;
      blocks.push(
        <ul key={`l${blocks.length}`}>
          {items.map((item, i) => (
            <li key={i}>{inline(item)}</li>
          ))}
        </ul>,
      );
      list = [];
    }
  };
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (/^[-*]\s+/.test(line)) {
      list.push(line.replace(/^[-*]\s+/, ""));
      continue;
    }
    flush();
    if (!line) continue;
    const heading = line.match(/^#{1,6}\s+(.*)$/);
    if (heading) blocks.push(<h4 key={blocks.length}>{inline(heading[1])}</h4>);
    else blocks.push(<p key={blocks.length}>{inline(line)}</p>);
  }
  flush();
  return <div className="release-notes">{blocks.length ? blocks : <p className="muted">{t("Bez poznámek k vydání.")}</p>}</div>;
}

function waitForNewVersion(oldVersion: string, onDone: (version: string) => void, onTimeout: () => void): () => void {
  let stopped = false;
  const started = Date.now();
  const tick = async () => {
    if (stopped) return;
    try {
      const res = await fetch("/api/health", { cache: "no-store" });
      if (res.ok) {
        const data = (await res.json()) as { version?: string };
        if (data.version && data.version !== oldVersion) {
          onDone(data.version);
          return;
        }
      }
    } catch {
      /* aplikace se právě restartuje */
    }
    if (Date.now() - started > 5 * 60 * 1000) {
      onTimeout();
      return;
    }
    window.setTimeout(tick, 2000);
  };
  void tick();
  return () => {
    stopped = true;
  };
}

export function UpdatePanel() {
  const toast = useToast();
  const [info, setInfo] = useState<UpdateInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [progress, setProgress] = useState<UpdaterStatus | null>(null);
  const [restarting, setRestarting] = useState(false);
  const [showLog, setShowLog] = useState(false);
  const stopWait = useRef<(() => void) | null>(null);
  const startVersion = useRef<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await api<UpdateInfo>("/api/system/update");
      setInfo(data);
      setError(null);
      return data;
    } catch (err) {
      setError(errorMessage(err));
      return null;
    }
  }, []);

  useEffect(() => {
    void load().then((data) => {
      if (data?.updater?.state === "running") setProgress(data.updater);
    });
    return () => stopWait.current?.();
  }, [load]);

  // Průběh aktualizace: dokud aplikace běží, čte stav updateru; při restartu čeká na novou verzi.
  useEffect(() => {
    if (!progress || progress.state !== "running" || !info) return;
    if (startVersion.current === null) startVersion.current = info.current;
    const finished = (version: string) => {
      toast(t("Elenvar byl aktualizován na verzi {version}.", { version: version }));
      window.setTimeout(() => window.location.reload(), 1200);
    };
    const handle = window.setInterval(async () => {
      try {
        const data = await api<UpdateInfo>("/api/system/update");
        if (data.current !== startVersion.current) {
          // Nová verze naběhla mezi dvěma dotazy.
          window.clearInterval(handle);
          setRestarting(true);
          finished(data.current);
          return;
        }
        setInfo(data);
        if (data.updater) setProgress(data.updater);
      } catch {
        // Aplikace se restartuje – počkáme, až naběhne nová verze.
        window.clearInterval(handle);
        setRestarting(true);
        stopWait.current = waitForNewVersion(
          startVersion.current ?? info.current,
          finished,
          () => {
            setRestarting(false);
            setProgress(null);
            setError(t("Aplikace se po aktualizaci nevrátila do 5 minut. Zkontrolujte stav serveru."));
          },
        );
      }
    }, 2000);
    return () => window.clearInterval(handle);
  }, [progress, info, toast]);

  useEffect(() => {
    if (!progress || progress.state === "running") return;
    if (progress.state === "done" && progress.result === "current") toast(t("Elenvar je aktuální, nebylo co instalovat."), "info");
  }, [progress, toast]);

  const check = async () => {
    setChecking(true);
    try {
      setInfo(await api<UpdateInfo>("/api/system/update/check", { method: "POST" }));
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setChecking(false);
    }
  };

  if (!info) {
    return (
      <section className="panel">{error ? <Alert>{error}</Alert> : <Spinner label={t("Načítám informace o verzi…")} />}</section>
    );
  }

  const running = progress?.state === "running" || restarting;
  const latest = info.latest;

  return (
    <section className="panel update-panel" aria-labelledby="update-title">
      <div className="update-head">
        <Logo size={56} />
        <div className="update-title">
          <h2 id="update-title">{t("Aktualizace softwaru")}</h2>
          <span className="muted">
            {t("Elenvar")} {info.current}
            {info.checked_at ? t(" · zkontrolováno {checked_at}", { checked_at: formatRelative(info.checked_at) }) : ""}
          </span>
        </div>
        <button type="button" className="btn btn-small" onClick={() => void check()} disabled={checking || running}>
          {checking ? <Spinner size={14} /> : <RefreshCw size={14} />} {t("Zkontrolovat")}
        </button>
      </div>

      {error && <Alert>{error}</Alert>}
      {info.error && !error && <Alert kind="warning">{info.error}</Alert>}

      {running ? (
        <div className="update-progress" role="status" aria-live="polite">
          <strong>{restarting ? t("Restartuji Elenvar…") : progress?.phase || t("Připravuji aktualizaci…")}</strong>
          <div className="progress progress-indeterminate">
            <span />
          </div>
          <span className="muted small">{t("Během restartu bude aplikace krátce nedostupná. Stránka se poté sama obnoví.")}</span>
        </div>
      ) : info.update_available && latest ? (
        <div className="update-available">
          <div className="update-version">
            <div>
              <strong>{t("Elenvar")} {latest.version}</strong>
              {latest.prerelease && <span className="pill pill-warn ml">{t("Předběžná verze")}</span>}
              <div className="muted small">{latest.published_at ? t("Vydáno {published_at}", { published_at: formatDateTime(latest.published_at) }) : ""}</div>
            </div>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => setConfirming(true)}
              disabled={!info.updater_available}
              title={info.updater_available ? undefined : info.updater_error}
            >
              {t("Aktualizovat nyní")}
            </button>
          </div>
          <ReleaseNotes text={latest.notes} />
          {latest.url && (
            <a className="link small" href={latest.url} target="_blank" rel="noreferrer noopener">
              {t("Podrobnosti o vydání")} <ExternalLink size={12} />
            </a>
          )}
          {!info.updater_available && (
            <Alert kind="info">
              {t("Aktualizace z webu není dostupná (")}{info.updater_error}{t("). Aktualizujte na serveru příkazem")}{" "}
              <code>docker compose pull &amp;&amp; docker compose up -d</code>.
            </Alert>
          )}
        </div>
      ) : (
        <p className="update-current">
          {info.error && !latest
            ? t("Dostupnost nové verze se nepodařilo ověřit.")
            : latest || info.checked_at
              ? t("Používáte nejnovější verzi Elenvaru.")
              : t("Zatím nebyla provedena kontrola aktualizací.")}
        </p>
      )}

      {progress && progress.state === "failed" && !running && <Alert>{t("Aktualizace selhala:")} {progress.message}</Alert>}

      {progress && progress.log.length > 0 && (
        <div className="update-log">
          <button type="button" className="link-btn" onClick={() => setShowLog((v) => !v)} aria-expanded={showLog}>
            <ChevronDown size={14} className={showLog ? "rot" : ""} /> {showLog ? t("Skrýt podrobnosti") : t("Zobrazit podrobnosti")}
          </button>
          {showLog && <pre>{progress.log.join("\n")}</pre>}
        </div>
      )}

      {confirming && latest && (
        <InstallDialog
          version={latest.version}
          onClose={() => setConfirming(false)}
          onStarted={(data) => {
            setConfirming(false);
            setInfo(data);
            setProgress(data.updater ?? { state: "running", phase: "", result: "", message: "", log: [] });
          }}
        />
      )}
    </section>
  );
}

function InstallDialog({
  version,
  onClose,
  onStarted,
}: {
  version: string;
  onClose: () => void;
  onStarted: (data: UpdateInfo) => void;
}) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onStarted(await api<UpdateInfo>("/api/system/update/install", { method: "POST", body: { password } }));
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };
  return (
    <Modal
      title={t("Aktualizovat na verzi {version}?", { version: version })}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} disabled={busy}>
            {t("Zrušit")}
          </button>
          <button type="submit" form="install-form" className="btn btn-primary" disabled={busy || !password}>
            {busy ? <Spinner size={16} /> : null} {t("Aktualizovat")}
          </button>
        </>
      }
    >
      <form id="install-form" className="form" onSubmit={submit}>
        <p className="confirm-message">
          {t("Elenvar stáhne novou verzi a restartuje se. Záznamy na NVR ani nastavení se nemění; živý obraz se na chvíli přeruší.")}
        </p>
        <div className="field">
          <label htmlFor="install-password">{t("Potvrďte heslem")}</label>
          <input
            id="install-password"
            className="input"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </div>
        {error && <Alert>{error}</Alert>}
      </form>
    </Modal>
  );
}
