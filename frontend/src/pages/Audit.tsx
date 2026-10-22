import { useCallback, useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Search } from "lucide-react";
import { Alert, PageHeader, PageLoader } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { formatDateTime } from "../lib/format";
import type { AuditEntry } from "../types";

const PAGE = 50;

const ACTION_LABELS: Record<string, string> = {
  login_success: "Přihlášení",
  login_failed: "Neúspěšné přihlášení",
  login_locked: "Přihlášení k zablokovanému účtu",
  login_password_ok: "Heslo ověřeno",
  mfa_failed: "Neplatný 2FA kód",
  logout: "Odhlášení",
  "2fa_enabled": "Zapnuto 2FA",
  "2fa_disabled": "Vypnuto 2FA",
  "2fa_disable_failed": "Neúspěšné vypnutí 2FA",
  recovery_codes_regenerated: "Nové záložní kódy",
  recovery_codes_failed: "Neúspěšné generování kódů",
  password_changed: "Změna hesla",
  password_change_failed: "Neúspěšná změna hesla",
  session_revoked: "Ukončení relace",
  user_created: "Vytvoření uživatele",
  user_updated: "Úprava uživatele",
  user_deleted: "Smazání uživatele",
  nvr_created: "Přidání zařízení",
  nvr_updated: "Úprava zařízení",
  nvr_deleted: "Smazání zařízení",
  nvr_reboot: "Restart zařízení",
  stream_settings: "Nastavení streamu",
  camera_monitoring: "Monitoring kamery",
  recording_playback: "Přehrání záznamu",
  recording_download: "Stažení záznamu",
  settings_updated: "Změna nastavení",
  events_ack_all: "Potvrzení událostí",
  update_install: "Aktualizace aplikace",
};

export function AuditPage() {
  const [items, setItems] = useState<AuditEntry[] | null>(null);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const [applied, setApplied] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const p = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
      if (applied) p.set("q", applied);
      const res = await api<{ total: number; items: AuditEntry[] }>(`/api/audit?${p.toString()}`);
      setItems(res.items);
      setTotal(res.total);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [offset, applied]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const handle = window.setTimeout(() => {
      setOffset(0);
      setApplied(query.trim());
    }, 350);
    return () => window.clearTimeout(handle);
  }, [query]);

  if (!items) return error ? <Alert>{error}</Alert> : <PageLoader />;

  return (
    <div className="page">
      <PageHeader title="Auditní záznam" subtitle="Přihlášení, změny nastavení a přístupy k záznamům" />
      {error && <Alert>{error}</Alert>}
      <div className="panel">
        <div className="panel-header wrap">
          <div className="search">
            <Search size={16} aria-hidden />
            <input className="input" placeholder="Hledat uživatele, akci, IP…" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Hledat v auditu" maxLength={100} />
          </div>
          <div className="pager">
            <span className="muted small">
              {total === 0 ? "0" : `${offset + 1}–${Math.min(offset + PAGE, total)}`} z {total}
            </span>
            <button type="button" className="icon-btn" onClick={() => setOffset((o) => Math.max(0, o - PAGE))} disabled={offset === 0} aria-label="Předchozí">
              <ChevronLeft size={18} />
            </button>
            <button type="button" className="icon-btn" onClick={() => setOffset((o) => o + PAGE)} disabled={offset + PAGE >= total} aria-label="Další">
              <ChevronRight size={18} />
            </button>
          </div>
        </div>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Čas</th>
                <th>Uživatel</th>
                <th>IP adresa</th>
                <th>Akce</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id} className={r.success ? "" : "row-bad"}>
                  <td className="nowrap">{formatDateTime(r.ts)}</td>
                  <td>{r.username || "—"}</td>
                  <td className="mono small">{r.ip || "—"}</td>
                  <td className="nowrap">{ACTION_LABELS[r.action] ?? r.action}</td>
                  <td className="break">{r.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
