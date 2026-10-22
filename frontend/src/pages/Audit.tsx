import { useCallback, useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Search } from "lucide-react";
import { Alert, PageHeader, PageLoader } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { formatDateTime } from "../lib/format";
import type { AuditEntry } from "../types";
import { N_, t } from "../lib/i18n";

const PAGE = 50;

const ACTION_LABELS: Record<string, string> = {
  login_success: N_("Přihlášení"),
  login_failed: N_("Neúspěšné přihlášení"),
  login_locked: N_("Přihlášení k zablokovanému účtu"),
  login_password_ok: N_("Heslo ověřeno"),
  mfa_failed: N_("Neplatný 2FA kód"),
  logout: N_("Odhlášení"),
  "2fa_enabled": N_("Zapnuto 2FA"),
  "2fa_disabled": N_("Vypnuto 2FA"),
  "2fa_disable_failed": N_("Neúspěšné vypnutí 2FA"),
  recovery_codes_regenerated: N_("Nové záložní kódy"),
  recovery_codes_failed: N_("Neúspěšné generování kódů"),
  password_changed: N_("Změna hesla"),
  password_change_failed: N_("Neúspěšná změna hesla"),
  session_revoked: N_("Ukončení relace"),
  user_created: N_("Vytvoření uživatele"),
  user_updated: N_("Úprava uživatele"),
  user_deleted: N_("Smazání uživatele"),
  nvr_created: N_("Přidání zařízení"),
  nvr_updated: N_("Úprava zařízení"),
  nvr_deleted: N_("Smazání zařízení"),
  nvr_reboot: N_("Restart zařízení"),
  stream_settings: N_("Nastavení streamu"),
  camera_monitoring: N_("Monitoring kamery"),
  recording_playback: N_("Přehrání záznamu"),
  recording_download: N_("Stažení záznamu"),
  settings_updated: N_("Změna nastavení"),
  events_ack_all: N_("Potvrzení událostí"),
  update_install: N_("Aktualizace aplikace"),
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
      <PageHeader title={t("Auditní záznam")} subtitle={t("Přihlášení, změny nastavení a přístupy k záznamům")} />
      {error && <Alert>{error}</Alert>}
      <div className="panel">
        <div className="panel-header wrap">
          <div className="search">
            <Search size={16} aria-hidden />
            <input className="input" placeholder={t("Hledat uživatele, akci, IP…")} value={query} onChange={(e) => setQuery(e.target.value)} aria-label={t("Hledat v auditu")} maxLength={100} />
          </div>
          <div className="pager">
            <span className="muted small">
              {total === 0 ? "0" : `${offset + 1}–${Math.min(offset + PAGE, total)}`} {t("z")} {total}
            </span>
            <button type="button" className="icon-btn" onClick={() => setOffset((o) => Math.max(0, o - PAGE))} disabled={offset === 0} aria-label={t("Předchozí")}>
              <ChevronLeft size={18} />
            </button>
            <button type="button" className="icon-btn" onClick={() => setOffset((o) => o + PAGE)} disabled={offset + PAGE >= total} aria-label={t("Další")}>
              <ChevronRight size={18} />
            </button>
          </div>
        </div>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>{t("Čas")}</th>
                <th>{t("Uživatel")}</th>
                <th>{t("IP adresa")}</th>
                <th>{t("Akce")}</th>
                <th>{t("Detail")}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id} className={r.success ? "" : "row-bad"}>
                  <td className="nowrap">{formatDateTime(r.ts)}</td>
                  <td>{r.username || "—"}</td>
                  <td className="mono small">{r.ip || "—"}</td>
                  <td className="nowrap">{ACTION_LABELS[r.action] ? t(ACTION_LABELS[r.action]) : r.action}</td>
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
