import { useCallback, useEffect, useState, type FormEvent } from "react";
import { KeyRound, LogOut, Monitor, ShieldCheck, ShieldOff } from "lucide-react";
import { useAuth } from "../auth";
import { RecoveryCodes, TotpSetup } from "../components/TwoFactor";
import { Alert, Modal, PageHeader, Spinner, useToast } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { formatDateTime, formatRelative, ROLE_LABELS } from "../lib/format";
import type { SessionInfo, User } from "../types";

function describeAgent(ua: string): string {
  if (!ua) return "Neznámé zařízení";
  const browser = /Edg\//.test(ua) ? "Edge" : /Firefox\//.test(ua) ? "Firefox" : /Chrome\//.test(ua) ? "Chrome" : /Safari\//.test(ua) ? "Safari" : "Prohlížeč";
  const os = /Windows/.test(ua) ? "Windows" : /Android/.test(ua) ? "Android" : /iPhone|iPad/.test(ua) ? "iOS" : /Mac OS X/.test(ua) ? "macOS" : /Linux/.test(ua) ? "Linux" : "";
  return os ? `${browser} · ${os}` : browser;
}

function ReauthModal({
  title,
  action,
  onClose,
  onDone,
}: {
  title: string;
  action: "disable" | "codes";
  onClose: () => void;
  onDone: (codes?: string[]) => void;
}) {
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (action === "disable") {
        await api("/api/auth/2fa/disable", { method: "POST", body: { password, code } });
        onDone();
      } else {
        const res = await api<{ recovery_codes: string[] }>("/api/auth/2fa/recovery-codes", { method: "POST", body: { password, code } });
        onDone(res.recovery_codes);
      }
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };
  return (
    <Modal
      title={title}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Zrušit
          </button>
          <button type="submit" form="reauth-form" className={`btn ${action === "disable" ? "btn-danger" : "btn-primary"}`} disabled={busy}>
            {busy ? <Spinner size={16} /> : null} Potvrdit
          </button>
        </>
      }
    >
      <form id="reauth-form" className="form" onSubmit={submit}>
        <p className="muted">Z bezpečnostních důvodů potvrďte akci heslem a kódem z ověřovací aplikace.</p>
        <div className="field">
          <label htmlFor="ra-pass">Heslo</label>
          <input id="ra-pass" className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </div>
        <div className="field">
          <label htmlFor="ra-code">Kód z aplikace</label>
          <input id="ra-code" className="input code-input" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} required maxLength={16} />
        </div>
        {error && <Alert>{error}</Alert>}
      </form>
    </Modal>
  );
}

export function AccountPage() {
  const { user, require2fa, recoveryCodesLeft, refresh, setUser } = useAuth();
  const toast = useToast();
  const [sessions, setSessions] = useState<SessionInfo[] | null>(null);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [pwError, setPwError] = useState<string | null>(null);
  const [pwBusy, setPwBusy] = useState(false);
  const [enrolling, setEnrolling] = useState(false);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [reauth, setReauth] = useState<"disable" | "codes" | null>(null);

  const loadSessions = useCallback(async () => {
    try {
      setSessions(await api<SessionInfo[]>("/api/auth/sessions"));
    } catch (err) {
      toast(errorMessage(err), "error");
    }
  }, [toast]);

  useEffect(() => {
    void loadSessions();
  }, [loadSessions]);

  const changePassword = async (event: FormEvent) => {
    event.preventDefault();
    if (next !== confirm) {
      setPwError("Nová hesla se neshodují.");
      return;
    }
    setPwBusy(true);
    setPwError(null);
    try {
      const res = await api<{ user: User }>("/api/auth/password", { method: "POST", body: { current_password: current, new_password: next } });
      setUser(res.user);
      setCurrent("");
      setNext("");
      setConfirm("");
      toast("Heslo bylo změněno. Ostatní relace byly odhlášeny.");
      void loadSessions();
    } catch (err) {
      setPwError(errorMessage(err));
    } finally {
      setPwBusy(false);
    }
  };

  const revoke = async (id: number) => {
    try {
      await api(`/api/auth/sessions/${id}`, { method: "DELETE" });
      toast("Relace byla ukončena.");
      void loadSessions();
    } catch (err) {
      toast(errorMessage(err), "error");
    }
  };

  if (!user) return null;

  return (
    <div className="page">
      <PageHeader title="Můj účet" subtitle={`${user.full_name || user.username} · ${ROLE_LABELS[user.role]}`} />

      <div className="detail-grid">
        <section className="panel">
          <h2>
            <KeyRound size={18} /> Změna hesla
          </h2>
          <form className="form" onSubmit={changePassword}>
            <div className="field">
              <label htmlFor="a-cur">Současné heslo</label>
              <input id="a-cur" className="input" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
            </div>
            <div className="field">
              <label htmlFor="a-new">Nové heslo</label>
              <input id="a-new" className="input" type="password" autoComplete="new-password" minLength={12} value={next} onChange={(e) => setNext(e.target.value)} required />
              <div className="field-hint">Alespoň 12 znaků.</div>
            </div>
            <div className="field">
              <label htmlFor="a-conf">Nové heslo znovu</label>
              <input id="a-conf" className="input" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
            </div>
            {pwError && <Alert>{pwError}</Alert>}
            <button type="submit" className="btn btn-primary" disabled={pwBusy}>
              {pwBusy ? <Spinner size={16} /> : null} Změnit heslo
            </button>
          </form>
        </section>

        <section className="panel">
          <h2>
            <ShieldCheck size={18} /> Dvoufázové ověření
          </h2>
          {user.totp_enabled ? (
            <>
              <Alert kind="success">Dvoufázové ověření je zapnuté.</Alert>
              <p className="muted">
                Zbývající záložní kódy: <strong>{recoveryCodesLeft ?? "?"}</strong>
              </p>
              {recoveryCodesLeft !== null && recoveryCodesLeft <= 3 && <Alert kind="warning">Dochází vám záložní kódy – vygenerujte si nové.</Alert>}
              <div className="btn-row">
                <button type="button" className="btn btn-ghost" onClick={() => setReauth("codes")}>
                  <KeyRound size={16} /> Nové záložní kódy
                </button>
                {!require2fa && (
                  <button type="button" className="btn btn-ghost btn-danger-text" onClick={() => setReauth("disable")}>
                    <ShieldOff size={16} /> Vypnout 2FA
                  </button>
                )}
              </div>
            </>
          ) : (
            <>
              <Alert kind="warning">Dvoufázové ověření není zapnuté. Doporučujeme ho zapnout.</Alert>
              <button type="button" className="btn btn-primary" onClick={() => setEnrolling(true)}>
                <ShieldCheck size={16} /> Zapnout 2FA
              </button>
            </>
          )}
        </section>
      </div>

      <section className="panel">
        <div className="panel-header">
          <h2>
            <Monitor size={18} /> Aktivní přihlášení
          </h2>
        </div>
        {!sessions ? (
          <Spinner />
        ) : (
          <ul className="session-list">
            {sessions.map((s) => (
              <li key={s.id}>
                <div>
                  <strong>{describeAgent(s.user_agent)}</strong>
                  {s.current && <span className="pill pill-info ml">toto zařízení</span>}
                  <div className="muted small">
                    IP {s.ip || "—"} · přihlášeno {formatDateTime(s.created_at)} · aktivita {formatRelative(s.last_seen_at)}
                  </div>
                </div>
                {!s.current && (
                  <button type="button" className="btn btn-ghost btn-small" onClick={() => void revoke(s.id)}>
                    <LogOut size={14} /> Odhlásit
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {enrolling && !codes && (
        <Modal title="Zapnout dvoufázové ověření" onClose={() => setEnrolling(false)}>
          <TotpSetup
            onEnabled={(result) => {
              setCodes(result.recovery_codes);
              if (result.stage) void refresh();
            }}
          />
        </Modal>
      )}
      {codes && (
        <Modal title="Záložní kódy" onClose={() => undefined}>
          <RecoveryCodes
            codes={codes}
            onDone={() => {
              setCodes(null);
              setEnrolling(false);
              void refresh();
            }}
          />
        </Modal>
      )}
      {reauth && (
        <ReauthModal
          title={reauth === "disable" ? "Vypnout dvoufázové ověření" : "Vygenerovat nové záložní kódy"}
          action={reauth}
          onClose={() => setReauth(null)}
          onDone={(newCodes) => {
            setReauth(null);
            if (newCodes) setCodes(newCodes);
            else toast("Dvoufázové ověření bylo vypnuto.");
            void refresh();
          }}
        />
      )}
    </div>
  );
}

