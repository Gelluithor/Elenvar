import { useEffect, useState, type FormEvent } from "react";
import { Bell, Mail, Save, Send, ShieldCheck, Timer, Webhook } from "lucide-react";
import { useAuth } from "../auth";
import { Alert, PageHeader, PageLoader, Spinner, Switch, useToast } from "../components/ui";
import { UpdatePanel } from "../components/UpdatePanel";
import { api, errorMessage } from "../lib/api";
import type { AppSettings } from "../types";

export function SettingsPage() {
  const { user } = useAuth();
  const toast = useToast();
  const [form, setForm] = useState<AppSettings | null>(null);
  const [smtpPassword, setSmtpPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    api<AppSettings>("/api/settings")
      .then(setForm)
      .catch((err) => setError(errorMessage(err)));
  }, []);

  const set = <K extends keyof AppSettings>(key: K, value: AppSettings[K]) => setForm((f) => (f ? { ...f, [key]: value } : f));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!form) return;
    setBusy(true);
    setError(null);
    try {
      const { smtp_password_set: _ignored, ...rest } = form;
      void _ignored;
      const body: Record<string, unknown> = { ...rest };
      if (smtpPassword) body.smtp_password = smtpPassword;
      const saved = await api<AppSettings>("/api/settings", { method: "PUT", body });
      setForm(saved);
      setSmtpPassword("");
      toast("Nastavení bylo uloženo.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const testNotification = async () => {
    setTesting(true);
    try {
      const res = await api<{ ok: boolean; errors: string[] }>("/api/settings/test-notification", { method: "POST" });
      if (res.ok) toast("Testovací upozornění bylo odesláno.");
      else toast(res.errors.join(" · "), "error");
    } catch (err) {
      toast(errorMessage(err), "error");
    } finally {
      setTesting(false);
    }
  };

  if (!form) return error ? <Alert>{error}</Alert> : <PageLoader />;

  return (
    <div className="page">
      <PageHeader
        title="Nastavení"
        subtitle="Zabezpečení, monitoring a upozornění"
        actions={
          <button type="submit" form="settings-form" className="btn btn-primary" disabled={busy}>
            {busy ? <Spinner size={16} /> : <Save size={16} />} Uložit
          </button>
        }
      />
      {error && <Alert>{error}</Alert>}
      <UpdatePanel />
      <form id="settings-form" className="settings" onSubmit={submit}>
        <section className="panel">
          <h2>
            <ShieldCheck size={18} /> Zabezpečení
          </h2>
          <Switch
            checked={form.require_2fa}
            onChange={(v) => set("require_2fa", v)}
            label="Vyžadovat dvoufázové ověření pro všechny uživatele"
            description={
              user?.totp_enabled
                ? "Uživatelé bez 2FA si ho musí nastavit při příštím přihlášení (jejich relace se ukončí)."
                : "Pro zapnutí si nejprve nastavte 2FA u svého účtu."
            }
            disabled={!form.require_2fa && !user?.totp_enabled}
          />
        </section>

        <section className="panel">
          <h2>
            <Timer size={18} /> Monitoring
          </h2>
          <div className="grid-2">
            <div className="field">
              <label htmlFor="s-poll">Interval kontroly (s)</label>
              <input id="s-poll" className="input" type="number" min={15} max={3600} value={form.poll_interval} onChange={(e) => set("poll_interval", Number(e.target.value))} />
              <div className="field-hint">Jak často se zjišťuje stav zařízení a kamer.</div>
            </div>
            <div className="field">
              <label htmlFor="s-th">Počet selhání před upozorněním</label>
              <input id="s-th" className="input" type="number" min={1} max={20} value={form.offline_threshold} onChange={(e) => set("offline_threshold", Number(e.target.value))} />
              <div className="field-hint">Chrání před planými poplachy při krátkém výpadku.</div>
            </div>
            <div className="field">
              <label htmlFor="s-drift">Povolená odchylka času (s)</label>
              <input id="s-drift" className="input" type="number" min={10} max={86400} value={form.time_drift_threshold} onChange={(e) => set("time_drift_threshold", Number(e.target.value))} />
            </div>
            <div className="field">
              <label htmlFor="s-ret">Uchovávat události (dny)</label>
              <input id="s-ret" className="input" type="number" min={1} max={3650} value={form.event_retention_days} onChange={(e) => set("event_retention_days", Number(e.target.value))} />
            </div>
            <div className="field">
              <label htmlFor="s-aret">Uchovávat audit (dny)</label>
              <input id="s-aret" className="input" type="number" min={30} max={3650} value={form.audit_retention_days} onChange={(e) => set("audit_retention_days", Number(e.target.value))} />
            </div>
          </div>
        </section>

        <section className="panel">
          <h2>
            <Mail size={18} /> Upozornění e-mailem
          </h2>
          <Switch checked={form.smtp_enabled} onChange={(v) => set("smtp_enabled", v)} label="Odesílat upozornění e-mailem" />
          {form.smtp_enabled && (
            <div className="grid-2">
              <div className="field">
                <label htmlFor="s-host">SMTP server</label>
                <input id="s-host" className="input" value={form.smtp_host} onChange={(e) => set("smtp_host", e.target.value)} placeholder="smtp.firma.cz" />
              </div>
              <div className="field-row">
                <div className="field">
                  <label htmlFor="s-port">Port</label>
                  <input id="s-port" className="input" type="number" min={1} max={65535} value={form.smtp_port} onChange={(e) => set("smtp_port", Number(e.target.value))} />
                </div>
                <div className="field">
                  <label htmlFor="s-sec">Zabezpečení</label>
                  <select id="s-sec" className="input" value={form.smtp_security} onChange={(e) => set("smtp_security", e.target.value as AppSettings["smtp_security"])}>
                    <option value="starttls">STARTTLS</option>
                    <option value="ssl">SSL/TLS</option>
                    <option value="none">Žádné</option>
                  </select>
                </div>
              </div>
              <div className="field">
                <label htmlFor="s-user">Uživatel</label>
                <input id="s-user" className="input" value={form.smtp_username} onChange={(e) => set("smtp_username", e.target.value)} autoComplete="off" />
              </div>
              <div className="field">
                <label htmlFor="s-pass">Heslo</label>
                <input
                  id="s-pass"
                  className="input"
                  type="password"
                  value={smtpPassword}
                  onChange={(e) => setSmtpPassword(e.target.value)}
                  placeholder={form.smtp_password_set ? "Uloženo – vyplňte jen pro změnu" : ""}
                  autoComplete="new-password"
                />
              </div>
              <div className="field">
                <label htmlFor="s-from">Odesílatel</label>
                <input id="s-from" className="input" value={form.smtp_from} onChange={(e) => set("smtp_from", e.target.value)} placeholder="elenvar@firma.cz" />
              </div>
              <div className="field">
                <label htmlFor="s-to">Příjemci</label>
                <input id="s-to" className="input" value={form.smtp_to} onChange={(e) => set("smtp_to", e.target.value)} placeholder="technik@firma.cz, vedouci@firma.cz" />
              </div>
            </div>
          )}
        </section>

        <section className="panel">
          <h2>
            <Webhook size={18} /> Webhook
          </h2>
          <Switch
            checked={form.webhook_enabled}
            onChange={(v) => set("webhook_enabled", v)}
            label="Odesílat upozornění na webhook"
            description="JSON s poli text/content – funguje se Slackem, Discordem, Mattermostem, Home Assistantem apod."
          />
          {form.webhook_enabled && (
            <div className="field">
              <label htmlFor="s-wh">URL webhooku</label>
              <input id="s-wh" className="input" type="url" value={form.webhook_url} onChange={(e) => set("webhook_url", e.target.value)} placeholder="https://…" />
            </div>
          )}
        </section>

        <section className="panel">
          <h2>
            <Bell size={18} /> Obecné
          </h2>
          <Switch
            checked={form.update_check_enabled}
            onChange={(v) => set("update_check_enabled", v)}
            label="Automaticky kontrolovat aktualizace"
            description="Elenvar jednou za 6 hodin zjistí, zda je k dispozici nová verze, a upozorní na ni."
          />
          <Switch
            checked={form.update_include_prereleases}
            onChange={(v) => set("update_include_prereleases", v)}
            label="Nabízet i předběžné verze"
            description="Testovací verze s novinkami dřív, ale s vyšším rizikem chyb."
          />
          <Switch checked={form.notify_recoveries} onChange={(v) => set("notify_recoveries", v)} label="Upozorňovat i na obnovení provozu" description="Zpráva, když se zařízení nebo kamera opět rozjede." />
          <div className="btn-row">
            <button type="button" className="btn btn-ghost" onClick={() => void testNotification()} disabled={testing}>
              {testing ? <Spinner size={16} /> : <Send size={16} />} Odeslat testovací upozornění
            </button>
            <span className="muted small">Nejprve uložte změny nastavení.</span>
          </div>
        </section>
      </form>
    </div>
  );
}
