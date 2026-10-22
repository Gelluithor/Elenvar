import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Clock, HardDrive, Plug, Plus, Server, Video } from "lucide-react";
import { useAuth } from "../auth";
import { Alert, EmptyState, Modal, NvrStatusPill, PageHeader, PageLoader, Spinner, Switch, usePolling, useToast } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { formatRelative, hasRole } from "../lib/format";
import type { Nvr } from "../types";

interface FormState {
  name: string;
  host: string;
  http_port: number;
  rtsp_port: number;
  use_https: boolean;
  verify_tls: boolean;
  username: string;
  password: string;
  enabled: boolean;
  transcode: boolean;
  notes: string;
}

const EMPTY: FormState = {
  name: "",
  host: "",
  http_port: 80,
  rtsp_port: 554,
  use_https: false,
  verify_tls: false,
  username: "admin",
  password: "",
  enabled: true,
  transcode: false,
  notes: "",
};

interface TestResult {
  ok: boolean;
  message?: string;
  info?: { model: string; device_type: string; firmware: string; device_name: string };
  channel_count?: number;
}

export function NvrFormModal({ nvr, onClose, onSaved }: { nvr?: Nvr; onClose: () => void; onSaved: (n: Nvr) => void }) {
  const editing = Boolean(nvr);
  const [form, setForm] = useState<FormState>(() =>
    nvr
      ? {
          name: nvr.name,
          host: nvr.host ?? "",
          http_port: nvr.http_port ?? 80,
          rtsp_port: nvr.rtsp_port ?? 554,
          use_https: nvr.use_https ?? false,
          verify_tls: nvr.verify_tls ?? false,
          username: nvr.username ?? "",
          password: "",
          enabled: nvr.enabled,
          transcode: nvr.transcode,
          notes: nvr.notes ?? "",
        }
      : EMPTY,
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [test, setTest] = useState<TestResult | null>(null);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => setForm((f) => ({ ...f, [key]: value }));

  const runTest = async () => {
    setTesting(true);
    setTest(null);
    try {
      const res = await api<TestResult>("/api/nvrs/test", {
        method: "POST",
        body: {
          nvr_id: nvr?.id ?? null,
          host: form.host,
          http_port: form.http_port,
          use_https: form.use_https,
          verify_tls: form.verify_tls,
          username: form.username,
          password: form.password || null,
        },
      });
      setTest(res);
    } catch (err) {
      setTest({ ok: false, message: errorMessage(err) });
    } finally {
      setTesting(false);
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body: Partial<FormState> = { ...form };
      if (editing && !form.password) delete body.password;
      const saved = editing
        ? await api<Nvr>(`/api/nvrs/${nvr!.id}`, { method: "PATCH", body })
        : await api<Nvr>("/api/nvrs", { method: "POST", body });
      onSaved(saved);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <Modal
      title={editing ? `Upravit zařízení ${nvr!.name}` : "Přidat zařízení"}
      onClose={onClose}
      wide
      footer={
        <>
          <button type="button" className="btn btn-ghost" onClick={() => void runTest()} disabled={testing || !form.host || !form.username || (!editing && !form.password)}>
            {testing ? <Spinner size={16} /> : <Plug size={16} />} Otestovat připojení
          </button>
          <span className="toolbar-spacer" />
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Zrušit
          </button>
          <button type="submit" form="nvr-form" className="btn btn-primary" disabled={busy}>
            {busy ? <Spinner size={16} /> : null} Uložit
          </button>
        </>
      }
    >
      <form id="nvr-form" className="form grid-2" onSubmit={submit}>
        <div className="field span-2">
          <label htmlFor="nvr-name">Název</label>
          <input id="nvr-name" className="input" value={form.name} onChange={(e) => set("name", e.target.value)} required maxLength={128} placeholder="např. Sklad – NVR" />
        </div>
        <div className="field">
          <label htmlFor="nvr-host">IP adresa nebo hostname</label>
          <input id="nvr-host" className="input" value={form.host} onChange={(e) => set("host", e.target.value)} required placeholder="192.168.1.64" spellCheck={false} />
        </div>
        <div className="field-row">
          <div className="field">
            <label htmlFor="nvr-http">{form.use_https ? "HTTPS port" : "HTTP port"}</label>
            <input id="nvr-http" className="input" type="number" min={1} max={65535} value={form.http_port} onChange={(e) => set("http_port", Number(e.target.value))} required />
          </div>
          <div className="field">
            <label htmlFor="nvr-rtsp">RTSP port</label>
            <input id="nvr-rtsp" className="input" type="number" min={1} max={65535} value={form.rtsp_port} onChange={(e) => set("rtsp_port", Number(e.target.value))} required />
          </div>
        </div>
        <div className="field">
          <label htmlFor="nvr-user">Uživatel</label>
          <input id="nvr-user" className="input" value={form.username} onChange={(e) => set("username", e.target.value)} required autoComplete="off" spellCheck={false} />
        </div>
        <div className="field">
          <label htmlFor="nvr-pass">Heslo</label>
          <input
            id="nvr-pass"
            className="input"
            type="password"
            value={form.password}
            onChange={(e) => set("password", e.target.value)}
            required={!editing}
            autoComplete="new-password"
            placeholder={editing ? "Ponechat beze změny" : ""}
          />
        </div>
        <div className="span-2 switches">
          <Switch checked={form.use_https} onChange={(v) => { set("use_https", v); if (v && form.http_port === 80) set("http_port", 443); if (!v && form.http_port === 443) set("http_port", 80); }} label="Komunikovat přes HTTPS" description="Šifrované spojení na ISAPI rozhraní NVR." />
          {form.use_https && (
            <Switch checked={form.verify_tls} onChange={(v) => set("verify_tls", v)} label="Ověřovat certifikát" description="Vypněte pro výchozí self-signed certifikát Hikvision." />
          )}
          <Switch checked={form.enabled} onChange={(v) => set("enabled", v)} label="Monitorovat zařízení" description="Pravidelně kontrolovat stav zařízení a kamer." />
          <Switch checked={form.transcode} onChange={(v) => set("transcode", v)} label="Převádět video na H.264" description="Pro kamery s H.265, které prohlížeč neumí přehrát. Zatěžuje server." />
        </div>
        <div className="field span-2">
          <label htmlFor="nvr-notes">Poznámka</label>
          <textarea id="nvr-notes" className="input" rows={2} value={form.notes} onChange={(e) => set("notes", e.target.value)} maxLength={2000} />
        </div>
        <div className="span-2">
          <Alert kind="info">
            Doporučujeme na NVR vytvořit samostatný účet pouze pro Elenvar. Pro úpravu nastavení kamer musí mít oprávnění ke
            konfiguraci, jinak postačí oprávnění k živému obrazu a přehrávání.
          </Alert>
        </div>
        {test && (
          <div className="span-2">
            {test.ok ? (
              <Alert kind="success">
                Připojeno: <strong>{test.info?.model}</strong> ({test.info?.device_type}), firmware {test.info?.firmware}, kamer: {test.channel_count}
              </Alert>
            ) : (
              <Alert>{test.message}</Alert>
            )}
          </div>
        )}
        {error && (
          <div className="span-2">
            <Alert>{error}</Alert>
          </div>
        )}
      </form>
    </Modal>
  );
}

export function DevicesPage() {
  const { user } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const isAdmin = hasRole(user?.role, "admin");
  const [nvrs, setNvrs] = useState<Nvr[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    try {
      setNvrs(await api<Nvr[]>("/api/nvrs"));
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);
  usePolling(() => void load(), 15000);

  if (!nvrs) return error ? <Alert>{error}</Alert> : <PageLoader />;

  return (
    <div className="page">
      <PageHeader
        title="Zařízení"
        subtitle="NVR, DVR a samostatné kamery Hikvision"
        actions={
          isAdmin && (
            <button type="button" className="btn btn-primary" onClick={() => setAdding(true)}>
              <Plus size={16} /> Přidat zařízení
            </button>
          )
        }
      />
      {error && <Alert>{error}</Alert>}
      {nvrs.length === 0 ? (
        <EmptyState icon={<Server size={28} />} title="Zatím žádná zařízení">
          {isAdmin ? "Přidejte první NVR tlačítkem „Přidat zařízení“." : "Požádejte administrátora o přidání zařízení."}
        </EmptyState>
      ) : (
        <div className="panel">
          <div className="table-wrap">
            <table className="table table-click">
              <thead>
                <tr>
                  <th>Název</th>
                  <th>Stav</th>
                  <th>Model</th>
                  {isAdmin && <th>Adresa</th>}
                  <th>Kamery</th>
                  <th>Úložiště</th>
                  <th>Naposledy dostupné</th>
                </tr>
              </thead>
              <tbody>
                {nvrs.map((n) => (
                  <tr key={n.id} onClick={() => navigate(`/devices/${n.id}`)}>
                    <td>
                      <Link to={`/devices/${n.id}`} onClick={(e) => e.stopPropagation()}>
                        <strong>{n.name}</strong>
                      </Link>
                      {n.status_message && n.status !== "online" && <div className="muted small clamp">{n.status_message}</div>}
                    </td>
                    <td>
                      <NvrStatusPill status={n.status} />
                    </td>
                    <td>{n.model || "—"}</td>
                    {isAdmin && (
                      <td className="mono small">
                        {n.host}:{n.http_port}
                      </td>
                    )}
                    <td>
                      <span className={n.camera_monitored_offline ? "tone-bad-text" : ""}>
                        <Video size={14} /> {n.camera_online}/{n.camera_count}
                      </span>
                    </td>
                    <td>
                      <span className={n.disk_problems.length ? "tone-bad-text" : ""}>
                        <HardDrive size={14} /> {n.disk_problems.length ? `${n.disk_problems.length}× problém` : n.disks.length ? "OK" : "—"}
                      </span>
                    </td>
                    <td className="nowrap">
                      <Clock size={14} /> {formatRelative(n.last_seen_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {adding && (
        <NvrFormModal
          onClose={() => setAdding(false)}
          onSaved={(n) => {
            setAdding(false);
            toast(`Zařízení ${n.name} bylo přidáno. Načítám stav…`);
            void load();
            window.setTimeout(() => void load(), 4000);
          }}
        />
      )}
    </div>
  );
}
