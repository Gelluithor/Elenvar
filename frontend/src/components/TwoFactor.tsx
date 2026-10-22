import { useEffect, useState, type FormEvent } from "react";
import { Check, Copy, Download, ShieldCheck } from "lucide-react";
import { api, errorMessage } from "../lib/api";
import type { SessionPayload } from "../types";
import { Alert, Spinner } from "./ui";
import { t } from "../lib/i18n";

interface SetupData {
  secret: string;
  otpauth_uri: string;
  qr: string;
}

interface EnableResult extends Partial<SessionPayload> {
  recovery_codes: string[];
}

/** Průvodce zapnutím TOTP: QR kód, ověření kódu, zobrazení recovery kódů. */
export function TotpSetup({ onEnabled }: { onEnabled: (result: EnableResult) => void }) {
  const [setup, setSetup] = useState<SetupData | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showSecret, setShowSecret] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api<SetupData>("/api/auth/2fa/setup", { method: "POST" })
      .then((data) => !cancelled && setSetup(data))
      .catch((err) => !cancelled && setError(errorMessage(err)));
    return () => {
      cancelled = true;
    };
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api<EnableResult>("/api/auth/2fa/enable", { method: "POST", body: { code: code.trim() } });
      onEnabled(result);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  if (!setup) {
    return error ? <Alert>{error}</Alert> : <Spinner label={t("Připravuji…")} />;
  }
  return (
    <form className="totp-setup" onSubmit={submit}>
      <ol className="steps">
        <li>
          {t("Nainstalujte si ověřovací aplikaci (např.")} <strong>{t("Microsoft Authenticator")}</strong>,{" "}
          <strong>{t("Google Authenticator")}</strong>, <strong>{t("2FAS")}</strong> {t("nebo")} <strong>{t("Bitwarden")}</strong>).
        </li>
        <li>{t("Naskenujte QR kód aplikací.")}</li>
        <li>{t("Zadejte šestimístný kód, který aplikace zobrazí.")}</li>
      </ol>
      <div className="qr-wrap">
        <img src={setup.qr} alt={t("QR kód pro ověřovací aplikaci")} width={200} height={200} />
      </div>
      <button type="button" className="link-btn" onClick={() => setShowSecret((v) => !v)}>
        {showSecret ? t("Skrýt klíč") : t("Nelze skenovat? Zobrazit klíč pro ruční zadání")}
      </button>
      {showSecret && <code className="secret">{setup.secret.match(/.{1,4}/g)?.join(" ")}</code>}
      <div className="field">
        <label htmlFor="totp-code">{t("Ověřovací kód")}</label>
        <input
          id="totp-code"
          className="input code-input"
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9 ]{6,7}"
          maxLength={7}
          value={code}
          onChange={(e) => setCode(e.target.value)}
          required
          autoFocus
        />
      </div>
      {error && <Alert>{error}</Alert>}
      <button type="submit" className="btn btn-primary btn-block" disabled={busy || code.replace(/\s/g, "").length !== 6}>
        {busy ? <Spinner size={16} /> : <ShieldCheck size={16} />} {t("Ověřit a zapnout")}
      </button>
    </form>
  );
}

export function RecoveryCodes({ codes, onDone, doneLabel = t("Mám kódy uložené") }: { codes: string[]; onDone: () => void; doneLabel?: string }) {
  const [copied, setCopied] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const text = codes.join("\n");

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  const download = () => {
    const blob = new Blob(
      [t("Elenvar – záložní kódy pro přihlášení\nKaždý kód lze použít jen jednou.\n\n{text}\n", { text: text })],
      { type: "text/plain;charset=utf-8" },
    );
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "elenvar-zalozni-kody.txt";
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return (
    <div className="recovery">
      <Alert kind="warning">
        {t("Uložte si tyto záložní kódy na bezpečné místo. Použijete je, pokud ztratíte telefon. Každý kód platí jen jednou a")}
        <strong> {t("znovu se už nezobrazí")}</strong>.
      </Alert>
      <ul className="recovery-codes">
        {codes.map((c) => (
          <li key={c}>
            <code>{c}</code>
          </li>
        ))}
      </ul>
      <div className="btn-row">
        <button type="button" className="btn btn-ghost" onClick={copy}>
          {copied ? <Check size={16} /> : <Copy size={16} />} {copied ? t("Zkopírováno") : t("Kopírovat")}
        </button>
        <button type="button" className="btn btn-ghost" onClick={download}>
          <Download size={16} /> {t("Stáhnout")}
        </button>
      </div>
      <label className="check">
        <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
        <span>{t("Kódy jsem si bezpečně uložil(a)")}</span>
      </label>
      <button type="button" className="btn btn-primary btn-block" disabled={!confirmed} onClick={onDone}>
        {doneLabel}
      </button>
    </div>
  );
}
