import { useState, type FormEvent, type ReactNode } from "react";
import { KeyRound, LogIn, ShieldCheck } from "lucide-react";
import { useAuth } from "../auth";
import { LanguageLinks } from "../components/LanguageSwitch";
import { Logo } from "../components/Logo";
import { RecoveryCodes, TotpSetup } from "../components/TwoFactor";
import { Alert, Spinner } from "../components/ui";
import { api, errorMessage, ApiError } from "../lib/api";
import type { SessionPayload } from "../types";
import { t } from "../lib/i18n";

function AuthCard({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-brand">
          <Logo size={88} animated />
          <span>{t("Elenvar")}</span>
        </div>
        <h1>{title}</h1>
        {subtitle && <p className="auth-subtitle">{subtitle}</p>}
        {children}
      </div>
      <p className="auth-footer">{t("Chráněný přístup · všechny akce jsou auditovány")}</p>
      <LanguageLinks />
    </div>
  );
}

function PasswordStep() {
  const { applySession } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const payload = await api<SessionPayload>("/api/auth/login", { method: "POST", body: { username, password } });
      setPassword("");
      applySession(payload);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <AuthCard title={t("Přihlášení")} subtitle={t("Centrální správa a monitoring kamerových systémů")}>
      <form onSubmit={submit} className="form">
        <div className="field">
          <label htmlFor="login-username">{t("Uživatelské jméno")}</label>
          <input
            id="login-username"
            className="input"
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            autoFocus
          />
        </div>
        <div className="field">
          <label htmlFor="login-password">{t("Heslo")}</label>
          <input
            id="login-password"
            className="input"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </div>
        {error && <Alert>{error}</Alert>}
        <button type="submit" className="btn btn-primary btn-block" disabled={busy || !username || !password}>
          {busy ? <Spinner size={16} /> : <LogIn size={16} />} {t("Přihlásit se")}
        </button>
      </form>
    </AuthCard>
  );
}

function MfaStep() {
  const { applySession, pendingUsername, reset } = useAuth();
  const [code, setCode] = useState("");
  const [useRecovery, setUseRecovery] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [exhausted, setExhausted] = useState<SessionPayload | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const payload = await api<SessionPayload>("/api/auth/mfa", { method: "POST", body: { code: code.trim() } });
      if (payload.recovery_codes_exhausted) {
        setExhausted(payload);
        return;
      }
      applySession(payload);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        reset();
        return;
      }
      setError(errorMessage(err));
      setCode("");
      setBusy(false);
    }
  };

  if (exhausted) {
    return (
      <AuthCard title={t("Poslední záložní kód")} subtitle={t("Použili jste svůj poslední záložní kód.")}>
        <Alert kind="warning">{t("Po přihlášení si v nastavení účtu vygenerujte nové záložní kódy.")}</Alert>
        <button type="button" className="btn btn-primary btn-block" onClick={() => applySession(exhausted)}>
          {t("Pokračovat")}
        </button>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title={t("Dvoufázové ověření")}
      subtitle={useRecovery ? t("Zadejte jeden ze záložních kódů.") : t("Zadejte kód z ověřovací aplikace pro účet {pendingUsername}.", { pendingUsername: pendingUsername })}
    >
      <form onSubmit={submit} className="form">
        <div className="field">
          <label htmlFor="mfa-code">{useRecovery ? t("Záložní kód") : t("Šestimístný kód")}</label>
          <input
            id="mfa-code"
            key={useRecovery ? "recovery" : "totp"}
            className="input code-input"
            inputMode={useRecovery ? "text" : "numeric"}
            autoComplete="one-time-code"
            autoCapitalize="characters"
            spellCheck={false}
            maxLength={useRecovery ? 16 : 7}
            value={code}
            onChange={(e) => setCode(e.target.value)}
            required
            autoFocus
          />
        </div>
        {error && <Alert>{error}</Alert>}
        <button type="submit" className="btn btn-primary btn-block" disabled={busy || code.trim().length < 6}>
          {busy ? <Spinner size={16} /> : <ShieldCheck size={16} />} {t("Ověřit")}
        </button>
        <div className="auth-links">
          <button
            type="button"
            className="link-btn"
            onClick={() => {
              setUseRecovery((v) => !v);
              setCode("");
              setError(null);
            }}
          >
            <KeyRound size={14} /> {useRecovery ? t("Použít ověřovací aplikaci") : t("Použít záložní kód")}
          </button>
          <button type="button" className="link-btn" onClick={() => void api("/api/auth/logout", { method: "POST" }).finally(reset)}>
            {t("Zpět na přihlášení")}
          </button>
        </div>
      </form>
    </AuthCard>
  );
}

function EnrollStep() {
  const { applySession, reset } = useAuth();
  const [result, setResult] = useState<{ codes: string[]; payload: SessionPayload } | null>(null);

  if (result) {
    return (
      <AuthCard title={t("Záložní kódy")} subtitle={t("Dvoufázové ověření je zapnuté.")}>
        <RecoveryCodes codes={result.codes} onDone={() => applySession(result.payload)} doneLabel={t("Pokračovat do aplikace")} />
      </AuthCard>
    );
  }
  return (
    <AuthCard title={t("Nastavení dvoufázového ověření")} subtitle={t("Z bezpečnostních důvodů je pro přístup vyžadováno 2FA.")}>
      <TotpSetup
        onEnabled={(r) => {
          if (r.stage && r.csrf_token) {
            setResult({ codes: r.recovery_codes, payload: r as SessionPayload });
          }
        }}
      />
      <div className="auth-links">
        <button type="button" className="link-btn" onClick={() => void api("/api/auth/logout", { method: "POST" }).finally(reset)}>
          {t("Zrušit a odhlásit")}
        </button>
      </div>
    </AuthCard>
  );
}

export function LoginPage() {
  const { stage } = useAuth();
  if (stage === "mfa") return <MfaStep />;
  if (stage === "enroll") return <EnrollStep />;
  return <PasswordStep />;
}

export function ForcePasswordChange() {
  const { setUser, logout } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (next !== confirm) {
      setError(t("Nová hesla se neshodují."));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await api<{ user: SessionPayload["user"] }>("/api/auth/password", {
        method: "POST",
        body: { current_password: current, new_password: next },
      });
      if (res.user) setUser(res.user);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <AuthCard title={t("Změna hesla")} subtitle={t("Před pokračováním si prosím nastavte vlastní heslo.")}>
      <form onSubmit={submit} className="form">
        <div className="field">
          <label htmlFor="fp-current">{t("Současné heslo")}</label>
          <input id="fp-current" className="input" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required autoFocus />
        </div>
        <div className="field">
          <label htmlFor="fp-new">{t("Nové heslo")}</label>
          <input id="fp-new" className="input" type="password" autoComplete="new-password" minLength={12} value={next} onChange={(e) => setNext(e.target.value)} required />
          <div className="field-hint">{t("Alespoň 12 znaků. Doporučujeme delší frázi.")}</div>
        </div>
        <div className="field">
          <label htmlFor="fp-confirm">{t("Nové heslo znovu")}</label>
          <input id="fp-confirm" className="input" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
        </div>
        {error && <Alert>{error}</Alert>}
        <button type="submit" className="btn btn-primary btn-block" disabled={busy}>
          {busy ? <Spinner size={16} /> : null} {t("Uložit heslo")}
        </button>
        <div className="auth-links">
          <button type="button" className="link-btn" onClick={() => void logout()}>
            {t("Odhlásit se")}
          </button>
        </div>
      </form>
    </AuthCard>
  );
}
