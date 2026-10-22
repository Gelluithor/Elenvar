import { useCallback, useEffect, useState, type FormEvent } from "react";
import { KeyRound, LockOpen, Pencil, Plus, ShieldOff, Trash2, Wand2 } from "lucide-react";
import { useAuth } from "../auth";
import { Alert, ConfirmDialog, Modal, PageHeader, PageLoader, Spinner, Switch, useToast } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { formatRelative, ROLE_LABELS } from "../lib/format";
import type { AdminUser, Role } from "../types";

const ROLE_DESCRIPTIONS: Record<Role, string> = {
  viewer: "Přehled, živý obraz a stav monitoringu.",
  operator: "Navíc přehrávání a stahování záznamů, potvrzování událostí.",
  admin: "Plný přístup včetně zařízení, uživatelů a nastavení.",
};

function generatePassword(): string {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789-_";
  const bytes = new Uint32Array(20);
  window.crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => alphabet[b % alphabet.length]).join("");
}

function PasswordInput({ id, value, onChange }: { id: string; value: string; onChange: (v: string) => void }) {
  return (
    <div className="input-group">
      <input id={id} className="input mono" value={value} onChange={(e) => onChange(e.target.value)} required minLength={12} autoComplete="new-password" spellCheck={false} />
      <button type="button" className="btn btn-ghost" onClick={() => onChange(generatePassword())} title="Vygenerovat silné heslo">
        <Wand2 size={16} />
      </button>
    </div>
  );
}

function UserFormModal({ user, onClose, onSaved }: { user?: AdminUser; onClose: () => void; onSaved: () => void }) {
  const editing = Boolean(user);
  const [username, setUsername] = useState(user?.username ?? "");
  const [fullName, setFullName] = useState(user?.full_name ?? "");
  const [role, setRole] = useState<Role>(user?.role ?? "viewer");
  const [active, setActive] = useState(user?.is_active ?? true);
  const [password, setPassword] = useState(() => (user ? "" : generatePassword()));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (editing) {
        await api(`/api/users/${user!.id}`, { method: "PATCH", body: { full_name: fullName, role, is_active: active } });
      } else {
        await api("/api/users", { method: "POST", body: { username: username.trim().toLowerCase(), full_name: fullName, role, password } });
      }
      onSaved();
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <Modal
      title={editing ? `Upravit uživatele ${user!.username}` : "Nový uživatel"}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Zrušit
          </button>
          <button type="submit" form="user-form" className="btn btn-primary" disabled={busy}>
            {busy ? <Spinner size={16} /> : null} Uložit
          </button>
        </>
      }
    >
      <form id="user-form" className="form" onSubmit={submit}>
        {!editing && (
          <div className="field">
            <label htmlFor="u-name">Uživatelské jméno</label>
            <input id="u-name" className="input" value={username} onChange={(e) => setUsername(e.target.value)} required pattern="[a-zA-Z0-9][a-zA-Z0-9._\-]{2,63}" autoComplete="off" spellCheck={false} />
            <div className="field-hint">3–64 znaků: písmena bez diakritiky, číslice, tečka, pomlčka, podtržítko.</div>
          </div>
        )}
        <div className="field">
          <label htmlFor="u-full">Celé jméno</label>
          <input id="u-full" className="input" value={fullName} onChange={(e) => setFullName(e.target.value)} maxLength={128} />
        </div>
        <div className="field">
          <label htmlFor="u-role">Role</label>
          <select id="u-role" className="input" value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {(Object.keys(ROLE_LABELS) as Role[]).map((r) => (
              <option key={r} value={r}>
                {ROLE_LABELS[r]}
              </option>
            ))}
          </select>
          <div className="field-hint">{ROLE_DESCRIPTIONS[role]}</div>
        </div>
        {editing ? (
          <Switch checked={active} onChange={setActive} label="Účet je aktivní" description="Neaktivní uživatel se nemůže přihlásit." />
        ) : (
          <div className="field">
            <label htmlFor="u-pass">Dočasné heslo</label>
            <PasswordInput id="u-pass" value={password} onChange={setPassword} />
            <div className="field-hint">Předejte ho uživateli bezpečnou cestou. Při prvním přihlášení si heslo změní a nastaví 2FA.</div>
          </div>
        )}
        {error && <Alert>{error}</Alert>}
      </form>
    </Modal>
  );
}

function ResetPasswordModal({ user, onClose, onSaved }: { user: AdminUser; onClose: () => void; onSaved: () => void }) {
  const [password, setPassword] = useState(generatePassword);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api(`/api/users/${user.id}`, { method: "PATCH", body: { password } });
      onSaved();
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };
  return (
    <Modal
      title={`Nové heslo pro ${user.username}`}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Zrušit
          </button>
          <button type="submit" form="reset-form" className="btn btn-primary" disabled={busy}>
            {busy ? <Spinner size={16} /> : null} Nastavit heslo
          </button>
        </>
      }
    >
      <form id="reset-form" className="form" onSubmit={submit}>
        <div className="field">
          <label htmlFor="rp-pass">Dočasné heslo</label>
          <PasswordInput id="rp-pass" value={password} onChange={setPassword} />
          <div className="field-hint">Uživatel bude odhlášen a při dalším přihlášení si heslo musí změnit.</div>
        </div>
        {error && <Alert>{error}</Alert>}
      </form>
    </Modal>
  );
}

type Dialog =
  | { type: "create" }
  | { type: "edit"; user: AdminUser }
  | { type: "password"; user: AdminUser }
  | { type: "reset2fa"; user: AdminUser }
  | { type: "delete"; user: AdminUser };

export function UsersPage() {
  const { user: me } = useAuth();
  const toast = useToast();
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<Dialog | null>(null);

  const load = useCallback(async () => {
    try {
      setUsers(await api<AdminUser[]>("/api/users"));
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const unlock = async (u: AdminUser) => {
    try {
      await api(`/api/users/${u.id}`, { method: "PATCH", body: { unlock: true } });
      toast(`Účet ${u.username} byl odblokován.`);
      void load();
    } catch (err) {
      toast(errorMessage(err), "error");
    }
  };

  const done = (message: string) => {
    setDialog(null);
    toast(message);
    void load();
  };

  if (!users) return error ? <Alert>{error}</Alert> : <PageLoader />;

  return (
    <div className="page">
      <PageHeader
        title="Uživatelé"
        subtitle="Přístupy do aplikace a jejich role"
        actions={
          <button type="button" className="btn btn-primary" onClick={() => setDialog({ type: "create" })}>
            <Plus size={16} /> Nový uživatel
          </button>
        }
      />
      {error && <Alert>{error}</Alert>}
      <div className="panel">
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Uživatel</th>
                <th>Role</th>
                <th>2FA</th>
                <th>Stav</th>
                <th>Poslední přihlášení</th>
                <th className="right">Akce</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => {
                const self = u.id === me?.id;
                return (
                  <tr key={u.id}>
                    <td>
                      <strong>{u.username}</strong>
                      {self && <span className="pill pill-info ml">vy</span>}
                      {u.full_name && <div className="muted small">{u.full_name}</div>}
                    </td>
                    <td>{ROLE_LABELS[u.role]}</td>
                    <td>{u.totp_enabled ? <span className="pill pill-ok">Zapnuto</span> : <span className="pill pill-muted">Vypnuto</span>}</td>
                    <td>
                      {!u.is_active ? (
                        <span className="pill pill-muted">Neaktivní</span>
                      ) : u.locked ? (
                        <span className="pill pill-bad">Zablokován</span>
                      ) : u.must_change_password ? (
                        <span className="pill pill-warn">Čeká na změnu hesla</span>
                      ) : (
                        <span className="pill pill-ok">Aktivní</span>
                      )}
                    </td>
                    <td>{formatRelative(u.last_login_at)}</td>
                    <td className="right nowrap">
                      {u.locked && (
                        <button type="button" className="icon-btn" title="Odblokovat" onClick={() => void unlock(u)}>
                          <LockOpen size={16} />
                        </button>
                      )}
                      <button type="button" className="icon-btn" title="Upravit" onClick={() => setDialog({ type: "edit", user: u })}>
                        <Pencil size={16} />
                      </button>
                      {!self && (
                        <>
                          <button type="button" className="icon-btn" title="Nastavit nové heslo" onClick={() => setDialog({ type: "password", user: u })}>
                            <KeyRound size={16} />
                          </button>
                          {u.totp_enabled && (
                            <button type="button" className="icon-btn" title="Resetovat 2FA" onClick={() => setDialog({ type: "reset2fa", user: u })}>
                              <ShieldOff size={16} />
                            </button>
                          )}
                          <button type="button" className="icon-btn danger" title="Smazat" onClick={() => setDialog({ type: "delete", user: u })}>
                            <Trash2 size={16} />
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {dialog?.type === "create" && <UserFormModal onClose={() => setDialog(null)} onSaved={() => done("Uživatel byl vytvořen.")} />}
      {dialog?.type === "edit" && <UserFormModal user={dialog.user} onClose={() => setDialog(null)} onSaved={() => done("Uživatel byl uložen.")} />}
      {dialog?.type === "password" && <ResetPasswordModal user={dialog.user} onClose={() => setDialog(null)} onSaved={() => done("Heslo bylo nastaveno.")} />}
      {dialog?.type === "reset2fa" && (
        <ConfirmDialog
          title="Resetovat dvoufázové ověření?"
          message={`Uživatel ${dialog.user.username} bude odhlášen a při dalším přihlášení si 2FA nastaví znovu. Použijte, pokud ztratil telefon.`}
          confirmLabel="Resetovat 2FA"
          danger
          onClose={() => setDialog(null)}
          onConfirm={async () => {
            await api(`/api/users/${dialog.user.id}`, { method: "PATCH", body: { reset_2fa: true } });
            done("2FA bylo resetováno.");
          }}
        />
      )}
      {dialog?.type === "delete" && (
        <ConfirmDialog
          title="Smazat uživatele?"
          message={`Účet ${dialog.user.username} bude trvale odstraněn. Auditní záznamy zůstanou zachovány.`}
          confirmLabel="Smazat"
          danger
          onClose={() => setDialog(null)}
          onConfirm={async () => {
            await api(`/api/users/${dialog.user.id}`, { method: "DELETE" });
            done("Uživatel byl smazán.");
          }}
        />
      )}
    </div>
  );
}
